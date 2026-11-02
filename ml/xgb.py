"""Prediksi pemakaian bahan baku harian dengan satu model XGBoost global.

Port dari notebook model/XGBoost_Prediksi_Bahan_Baku.ipynb (subbab 8.4 dan 8.5 proposal):
fitur lag 1 dan 7, rata-rata dan simpangan baku bergerak 7 hari, hari, akhir pekan, dan
identitas bahan; normalisasi terhadap rata-rata data latih (Persamaan 7); target koreksi MA-7;
grid search 108 kombinasi dengan validasi silang rolling origin 4 lipatan mingguan; sigma_e dari
galat out-of-sample (Persamaan 22-23); prediksi rekursif hingga 7 hari.
"""
import itertools
import time

import numpy as np
import pandas as pd
import xgboost as xgb

import config as C

USAGE_FEATS = [f"lag_{l}" for l in C.LAGS] + [f"roll_mean_{C.ROLL_WINDOW}", f"roll_std_{C.ROLL_WINDOW}"]
FEATURES = USAGE_FEATS + ["hari", "akhir_pekan", "bahan"]
MAX_LAG = max(max(C.LAGS), C.ROLL_WINDOW)
ROLL_STD_DDOF = 0   # notebook memakai ddof=0; Persamaan 6 proposal memakai w-1 (ddof=1)
BASELINES = ["naive_mingguan", "ma_7", "rata_historis"]


class ModelXGB:
    """Model XGBoost lewat API inti (xgboost.train dan Booster), tanpa scikit-learn.

    Setara dengan XGBRegressor(...).fit/predict: parameter yang sama diteruskan ke xgboost.train dengan
    QuantileDMatrix seperti pembungkus scikit-learn untuk tree_method hist, dan prediksi memakai inplace_predict.
    """

    def __init__(self, booster: xgb.Booster):
        self.booster = booster

    @classmethod
    def latih(cls, X: pd.DataFrame, y: np.ndarray, params: dict) -> "ModelXGB":
        p = dict(params)
        n_pohon = int(p.pop("n_estimators"))
        data = xgb.QuantileDMatrix(X, label=y, missing=np.nan, enable_categorical=True, nthread=p.get("n_jobs"))
        return cls(xgb.train(p, data, num_boost_round=n_pohon))

    @classmethod
    def muat(cls, path) -> "ModelXGB":
        b = xgb.Booster()
        b.load_model(str(path))
        return cls(b)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.booster.inplace_predict(X)

    def save_model(self, path):
        self.booster.save_model(str(path))


def rmse(e):
    return float(np.sqrt(np.mean(np.square(e))))


def mae(e):
    return float(np.mean(np.abs(e)))


def tabel_lebar(long: pd.DataFrame, pakai_teras_kota: bool = True) -> pd.DataFrame:
    """Tabel panjang (Tanggal, SKU Bahan, Jumlah Keluar[, Dari Teras Kota]) -> tabel lebar tanggal x bahan.

    Hari tanpa pemakaian diisi 0, sama seperti sel 3 notebook.
    """
    raw = long.copy()
    raw["Tanggal"] = pd.to_datetime(raw["Tanggal"])
    raw["Pakai"] = raw["Jumlah Keluar"].astype(float)
    if not pakai_teras_kota and "Dari Teras Kota" in raw:
        raw["Pakai"] = raw["Pakai"] - raw["Dari Teras Kota"].fillna(0)
    wide = raw.groupby(["Tanggal", "SKU Bahan"])["Pakai"].sum().unstack("SKU Bahan")
    all_days = pd.date_range(wide.index.min(), wide.index.max(), freq="D")
    wide = wide.reindex(all_days).fillna(0.0).clip(lower=0)
    wide.index.name = "Tanggal"
    return wide


def tentukan_split(last_day: pd.Timestamp, first_day: pd.Timestamp, mode: str = C.SPLIT_MODE):
    """Pembagian kronologis latih/validasi/uji (sel 4 notebook)."""
    if mode == "auto":
        mode = "bulan" if last_day >= pd.Timestamp("2026-11-30") else "terakhir"
    if mode == "bulan":
        train_end, val_end = pd.Timestamp("2026-09-30"), pd.Timestamp("2026-10-31")
        test_end = min(last_day, pd.Timestamp("2026-11-30"))
    elif mode == "terakhir":
        test_end = last_day
        val_end = last_day - pd.Timedelta(days=C.TEST_DAYS)
        train_end = val_end - pd.Timedelta(days=C.VAL_DAYS)
    else:
        raise ValueError("SPLIT_MODE harus auto / bulan / terakhir")
    return {"mode": mode, "first_day": first_day, "train_end": train_end, "val_end": val_end, "test_end": test_end}


class PeramalXGB:
    """Membungkus seluruh tahap notebook untuk satu tabel lebar pemakaian."""

    def __init__(self, wide: pd.DataFrame, split: dict, items=None):
        self.split = split
        train_wide = wide.loc[:split["train_end"]]
        if items is None:
            items = train_wide.columns[train_wide.mean() > 0].tolist()
        self.items = list(items)
        self.dropped = sorted(set(wide.columns) - set(self.items))
        self.wide = wide[self.items]
        self.feat = self.buat_fitur(self.wide)

    # ------------------------------------------------------------------ fitur
    def buat_fitur(self, w: pd.DataFrame) -> pd.DataFrame:
        parts = {}
        for l in C.LAGS:
            parts[f"lag_{l}"] = w.shift(l)
        past = w.shift(1)
        parts[f"roll_mean_{C.ROLL_WINDOW}"] = past.rolling(C.ROLL_WINDOW).mean()
        parts[f"roll_std_{C.ROLL_WINDOW}"] = past.rolling(C.ROLL_WINDOW).std(ddof=ROLL_STD_DDOF)
        parts["y"] = w
        df = pd.concat({k: v.stack(future_stack=True) for k, v in parts.items()}, axis=1).reset_index()
        df.columns = ["Tanggal", "bahan"] + list(parts)
        df["hari"] = df["Tanggal"].dt.day_of_week
        df["akhir_pekan"] = df["hari"].isin(C.HARI_AKHIR_PEKAN).astype(int)
        df["bahan"] = pd.Categorical(df["bahan"], categories=self.items)
        df = df[df["Tanggal"] >= w.index.min() + pd.Timedelta(days=MAX_LAG)]
        return df.reset_index(drop=True)

    def skala_dari(self, sampai) -> pd.Series:
        return self.wide.loc[:sampai].mean()

    @staticmethod
    def normalisasi(df: pd.DataFrame, skala: pd.Series) -> pd.DataFrame:
        out = df.copy()
        s = out["bahan"].map(skala).astype(float).values
        s_safe = np.where(s > 0, s, 1.0)
        for c in USAGE_FEATS + ["y"]:
            out[c] = out[c].values / s_safe
        out["skala"] = s
        return out[s > 0]

    # ------------------------------------------------------------------ model
    @staticmethod
    def basis(df: pd.DataFrame) -> np.ndarray:
        if C.TARGET_MODE == "koreksi_ma":
            return df[f"roll_mean_{C.ROLL_WINDOW}"].values
        if C.TARGET_MODE == "langsung":
            return np.zeros(len(df))
        raise ValueError("TARGET_MODE harus koreksi_ma / langsung")

    @classmethod
    def latih(cls, df_train: pd.DataFrame, params: dict) -> ModelXGB:
        return ModelXGB.latih(df_train[FEATURES], df_train["y"].values - cls.basis(df_train),
                              {**params, **C.FIXED_PARAMS, "n_jobs": -1})

    @classmethod
    def prediksi_norm(cls, model, df: pd.DataFrame) -> np.ndarray:
        return np.clip(model.predict(df[FEATURES]) + cls.basis(df), 0, None)

    @classmethod
    def prediksi(cls, model, df: pd.DataFrame) -> np.ndarray:
        return cls.prediksi_norm(model, df) * df["skala"].values

    def _ambil(self, w: pd.DataFrame, df: pd.DataFrame) -> np.ndarray:
        idx = pd.MultiIndex.from_arrays([df["Tanggal"], df["bahan"].astype(str)])
        return w.stack(future_stack=True).reindex(idx).values

    def tambah_baseline(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["naive_mingguan"] = self._ambil(self.wide.shift(7), df)
        df["ma_7"] = self._ambil(self.wide.shift(1).rolling(7).mean(), df)
        df["rata_historis"] = df["skala"]
        return df

    # ------------------------------------------------------------------ tahap
    def lipatan_cv(self, train_end):
        origins = [train_end - pd.Timedelta(days=C.CV_FOLD_LEN * k - 1) for k in range(C.CV_FOLDS, 0, -1)]
        folds = []
        for o in origins:
            sk = self.skala_dari(o - pd.Timedelta(days=1))
            tr = self.normalisasi(self.feat[self.feat["Tanggal"] < o], sk)
            va = self.normalisasi(self.feat[(self.feat["Tanggal"] >= o)
                                            & (self.feat["Tanggal"] < o + pd.Timedelta(days=C.CV_FOLD_LEN))], sk)
            folds.append((o, tr, va))
        return folds

    def grid_search(self, folds, log=print):
        keys = list(C.PARAM_GRID)
        combos = [dict(zip(keys, v)) for v in itertools.product(*C.PARAM_GRID.values())]
        hasil, t0 = [], time.time()
        for i, p in enumerate(combos, 1):
            scores = []
            for _, tr, va in folds:
                m = self.latih(tr, p)
                scores.append(rmse(self.prediksi_norm(m, va) - va["y"].values))
            hasil.append({**p, "rmse_cv": float(np.mean(scores)), "rmse_std": float(np.std(scores))})
            if i % 27 == 0 or i == len(combos):
                log(f"  grid search {i}/{len(combos)} ({time.time() - t0:.0f} detik)")
        grid = pd.DataFrame(hasil).sort_values("rmse_cv", kind="stable").reset_index(drop=True)
        best = {k: (int(grid.loc[0, k]) if k in ("n_estimators", "max_depth") else float(grid.loc[0, k])) for k in keys}
        return best, grid

    @staticmethod
    def evaluasi_per_bahan(df: pd.DataFrame, kolom) -> pd.DataFrame:
        rows = []
        for b, g in df.groupby("bahan", observed=True):
            r = {"bahan": b}
            for k in kolom:
                e = g[k].values - g["y_asli"].values
                r[f"MAE_{k}"], r[f"RMSE_{k}"] = mae(e), rmse(e)
            rows.append(r)
        return pd.DataFrame(rows).set_index("bahan")

    def prediksi_rekursif(self, model, riwayat: pd.DataFrame, skala: pd.Series, mulai, horizon=C.HORIZON,
                          metode: pd.Series = None) -> pd.DataFrame:
        return prediksi_rekursif(model, self.items, riwayat, skala, mulai, horizon, metode)

    def jalankan(self, pakai_grid_search=True, best_params=None, log=print) -> dict:
        sp = self.split
        train_end, val_end, test_end = sp["train_end"], sp["val_end"], sp["test_end"]
        log(f"Bahan dimodelkan XGBoost: {len(self.items)} | tidak dimodelkan: {len(self.dropped)}")
        folds = self.lipatan_cv(train_end)
        grid = None
        if best_params is None:
            if pakai_grid_search:
                best_params, grid = self.grid_search(folds, log=log)
            else:
                best_params = dict(C.MANUAL_PARAMS)
        log(f"Hiperparameter terpilih: {best_params}")

        # validasi
        sk_train = self.skala_dari(train_end)
        tr_full = self.normalisasi(self.feat[self.feat["Tanggal"] <= train_end], sk_train)
        va_df = self.normalisasi(self.feat[(self.feat["Tanggal"] > train_end) & (self.feat["Tanggal"] <= val_end)], sk_train)
        model_val = self.latih(tr_full, best_params)
        va_df = self.tambah_baseline(va_df.assign(y_asli=lambda d: d["y"] * d["skala"]))
        va_df["xgboost"] = self.prediksi(model_val, va_df)
        kolom = ["xgboost"] + BASELINES
        met_val = self.evaluasi_per_bahan(va_df, kolom)
        rmse_cols = [f"RMSE_{k}" for k in kolom]
        met_val["metode_terbaik"] = met_val[rmse_cols].idxmin(axis=1).str.replace("RMSE_", "")

        # sigma_e dari 4 lipatan CV + data validasi (Persamaan 22-23)
        err_cv = []
        for _, tr, va in folds:
            m = self.latih(tr, best_params)
            e = self.prediksi(m, va) - va["y"].values * va["skala"].values
            err_cv.append(pd.DataFrame({"bahan": va["bahan"].astype(str).values, "galat": e}))
        err_val = pd.DataFrame({"bahan": va_df["bahan"].astype(str).values,
                                "galat": va_df["xgboost"].values - va_df["y_asli"].values})
        galat_cv = pd.concat(err_cv)
        sigma_cv = galat_cv.groupby("bahan")["galat"].std(ddof=1)            # untuk tahap validasi agen
        galat = pd.concat(err_cv + [err_val])
        sigma_e = galat.groupby("bahan")["galat"].agg(n_galat="count", rata_galat="mean",
                                                      sigma_e=lambda x: x.std(ddof=1))

        # model akhir (latih + validasi) dan uji
        sk_final = self.skala_dari(val_end)
        trval = self.normalisasi(self.feat[self.feat["Tanggal"] <= val_end], sk_final)
        te_df = self.normalisasi(self.feat[(self.feat["Tanggal"] > val_end) & (self.feat["Tanggal"] <= test_end)], sk_final)
        model_final = self.latih(trval, best_params)
        te_df = self.tambah_baseline(te_df.assign(y_asli=lambda d: d["y"] * d["skala"]))
        te_df["xgboost"] = self.prediksi(model_final, te_df)
        pilih = met_val["metode_terbaik"].reindex(te_df["bahan"].astype(str)).fillna("xgboost").values
        te_df["hibrida"] = te_df[kolom].to_numpy()[np.arange(len(te_df)), [kolom.index(p) for p in pilih]]
        kolom_uji = kolom + ["hibrida"]
        met_test = self.evaluasi_per_bahan(te_df, kolom_uji)
        err_test = pd.DataFrame({"bahan": te_df["bahan"].astype(str).values,
                                 "galat": te_df["xgboost"].values - te_df["y_asli"].values})
        sigma_prod = pd.concat(err_cv + [err_val, err_test]).groupby("bahan")["galat"].std(ddof=1)

        skala_b = sk_final.reindex(met_test.index)

        def ringkas(met, kol):
            rows = []
            for k in kol:
                rows.append({
                    "Metode": k,
                    "nMAE rata-rata": float((met[f"MAE_{k}"] / skala_b).mean()),
                    "nRMSE rata-rata": float((met[f"RMSE_{k}"] / skala_b).mean()),
                    "nRMSE median": float((met[f"RMSE_{k}"] / skala_b).median()),
                    "XGBoost menang (bahan)": (int((met["RMSE_xgboost"] < met[f"RMSE_{k}"]).sum())
                                               if k != "xgboost" else None),
                })
            return pd.DataFrame(rows).set_index("Metode")

        ringkasan = ringkas(met_test, kolom_uji)
        ringkasan_val = ringkas(met_val.reindex(met_test.index), kolom)
        log("Ringkasan data uji (nRMSE median): " + ", ".join(
            f"{k}={ringkasan.loc[k, 'nRMSE median']:.3f}" for k in kolom_uji))

        # galat per horizon rekursif pada data uji
        test_days = self.wide.loc[val_end + pd.Timedelta(days=1):test_end].index
        err_h = {h: [] for h in range(1, C.HORIZON + 1)}
        for o in test_days:
            if o + pd.Timedelta(days=C.HORIZON - 1) > test_end:
                break
            p = self.prediksi_rekursif(model_final, self.wide.loc[:o - pd.Timedelta(days=1)], sk_final, o)
            act = self.wide.loc[p.index]
            ne = ((p - act) / sk_final.replace(0, np.nan)).abs()
            for h in range(1, C.HORIZON + 1):
                err_h[h].append(ne.iloc[h - 1])
        mae_h = pd.Series({h: float(pd.concat(v, axis=1).mean(axis=1).mean()) for h, v in err_h.items()}, name="nMAE")

        self.best_params = best_params
        self.model_val, self.model_final = model_val, model_final
        self.sk_train, self.sk_final = sk_train, sk_final
        self.met_val = met_val
        return {
            "best_params": best_params, "grid": grid, "met_val": met_val, "met_test": met_test,
            "ringkasan": ringkasan, "ringkasan_val": ringkasan_val, "sigma_e": sigma_e,
            "sigma_cv": sigma_cv, "sigma_prod": sigma_prod, "mae_h": mae_h,
            "te_df": te_df[["Tanggal", "bahan", "y_asli"] + kolom_uji],
            "sk_train": sk_train, "sk_final": sk_final,
        }

    # ------------------------------------------------------------------ untuk agen dan aplikasi
    def model_semua_data(self, best_params=None):
        """Model produksi: dilatih ulang pada seluruh data yang ada (dipakai aplikasi)."""
        best_params = best_params or self.best_params
        last = self.wide.index.max()
        sk = self.skala_dari(last)
        df = self.normalisasi(self.feat, sk)
        return self.latih(df, best_params), sk

    def prakiraan_2_langkah(self, model, skala, origins, metode=None) -> dict:
        """Untuk setiap hari asal o: prediksi o+1 (1 langkah) dan o+2 (2 langkah) dari riwayat aktual s.d. o."""
        f1, f2 = {}, {}
        for o in origins:
            p = self.prediksi_rekursif(model, self.wide.loc[:o], skala, o + pd.Timedelta(days=1), horizon=2,
                                       metode=metode)
            f1[o + pd.Timedelta(days=1)] = p.iloc[0]
            f2[o + pd.Timedelta(days=2)] = p.iloc[1]
        return {"f1": pd.DataFrame(f1).T, "f2": pd.DataFrame(f2).T}

    def prakiraan_oos_mingguan(self, best_params, sampai, min_hari=C.OOS_MIN_HARI, log=print, metode=None) -> dict:
        """Prediksi out-of-sample expanding window yang dilatih ulang tiap Senin (subbab 8.7).

        Model untuk hari asal o adalah model terakhir yang titik latih ulangnya r <= o+1 dan
        dilatih dengan data < r, sehingga prediksi 1 dan 2 langkah dari o tidak pernah melihat data setelah o.
        """
        first = self.wide.index.min()
        r = first + pd.Timedelta(days=min_hari)
        while r.day_of_week != 0:
            r += pd.Timedelta(days=1)
        points = []
        while r <= sampai:
            points.append(r)
            r += pd.Timedelta(days=7)
        f1, f2 = {}, {}
        for i, r in enumerate(points):
            sk = self.skala_dari(r - pd.Timedelta(days=1))
            tr = self.normalisasi(self.feat[self.feat["Tanggal"] < r], sk)
            m = self.latih(tr, best_params)
            nxt = points[i + 1] if i + 1 < len(points) else sampai + pd.Timedelta(days=1)
            o = r - pd.Timedelta(days=1)
            while o + pd.Timedelta(days=1) < nxt and o < sampai:
                p = self.prediksi_rekursif(m, self.wide.loc[:o], sk, o + pd.Timedelta(days=1), horizon=2, metode=metode)
                f1[o + pd.Timedelta(days=1)] = p.iloc[0]
                f2[o + pd.Timedelta(days=2)] = p.iloc[1]
                o += pd.Timedelta(days=1)
        log(f"Prediksi out-of-sample mingguan: {len(points)} model, {points[0].date()} s.d. {sampai.date()}")
        return {"f1": pd.DataFrame(f1).T, "f2": pd.DataFrame(f2).T, "titik_latih": points}


def prediksi_rekursif(model, items, riwayat: pd.DataFrame, skala: pd.Series, mulai, horizon=C.HORIZON,
                      metode: pd.Series = None) -> pd.DataFrame:
    """Prediksi rekursif `horizon` hari mulai `mulai` dari riwayat satuan asli (sampai hari sebelum `mulai`).

    Dipakai saat evaluasi dan oleh aplikasi untuk prediksi 7 hari. `metode` (opsional, per bahan) mengganti
    XGBoost dengan baseline untuk prediksi hibrida.
    """
    hist = riwayat[items].copy()
    s = skala.reindex(items).fillna(0).values
    s_safe = np.where(s > 0, s, 1.0)
    out = []
    for h in range(horizon):
        d = mulai + pd.Timedelta(days=h)
        X = pd.DataFrame({f"lag_{l}": hist.iloc[-l].values / s_safe for l in C.LAGS})
        win = hist.iloc[-C.ROLL_WINDOW:]
        X[f"roll_mean_{C.ROLL_WINDOW}"] = win.mean().values / s_safe
        X[f"roll_std_{C.ROLL_WINDOW}"] = win.std(ddof=ROLL_STD_DDOF).values / s_safe
        X["hari"] = d.day_of_week
        X["akhir_pekan"] = int(d.day_of_week in C.HARI_AKHIR_PEKAN)
        X["bahan"] = pd.Categorical(items, categories=items)
        yhat = PeramalXGB.prediksi_norm(model, X) * s
        if metode is not None:
            mt = metode.reindex(items).fillna("xgboost").values
            naive = hist.iloc[-7].values
            ma = win.mean().values
            yhat = np.where(mt == "naive_mingguan", naive, yhat)
            yhat = np.where(mt == "ma_7", ma, yhat)
            yhat = np.where(mt == "rata_historis", s, yhat)
        hist.loc[d] = yhat
        out.append(pd.Series(yhat, index=items, name=d))
    return pd.DataFrame(out)
