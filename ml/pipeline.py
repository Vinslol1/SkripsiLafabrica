"""Alur pelatihan dan pengujian lengkap: praproses cakupan bahan -> XGBoost -> ROP dinamis -> Q-Learning ->
simulasi K1/K2/K3.

Praproses (ml/praproses.py) mengeluarkan bahan yang kosong atau didominasi nilai 0, lalu menetapkan bahan target
penelitian. Model hanya dilatih dan diuji pada bahan yang dimodelkan (bawaan: bahan target).

Selain uji 28 hari (K1 statis, K2, K3), bila ada catatan barang masuk cafe yang beririsan dengan periode uji,
barang yang benar-benar diterima diputar ulang sebagai K1 aktual dan dibandingkan dengan K1 statis, K2, dan K3
pada hari-hari yang sama.

Dipakai oleh aplikasi (menu Pelatihan Ulang) dan dari baris perintah:
    python -m ml.pipeline              # latih + uji, simpan artefak dan laporan Excel
    python -m ml.pipeline --tuning     # sekaligus pilih alpha/gamma Q-Learning pada periode validasi
"""
import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import config as C
from ml import praproses as PR
from ml import rincian as RC
from ml import simulasi as SIM
from ml.kebijakan import tepi_bin
from ml.qlearning import latih_agen
from ml.xgb import PeramalXGB, tabel_lebar, tentukan_split


def minggu_penuh(mulai: pd.Timestamp, sampai: pd.Timestamp):
    """Senin-Senin yang minggunya (7 hari) seluruhnya berada di [mulai, sampai]."""
    d = mulai
    while d.day_of_week != 0:
        d += pd.Timedelta(days=1)
    out = []
    while d + pd.Timedelta(days=6) <= sampai:
        out.append(d)
        d += pd.Timedelta(days=7)
    return out


def susun_parameter(master: pd.DataFrame, skus, biaya: dict) -> dict:
    """Parameter biaya dan kemasan per bahan dari data master (Tabel 5)."""
    m = master.set_index("sku").reindex(skus)
    harga = m["harga_satuan"].astype(float).fillna(0).values
    return {
        "k": m["kemasan_isi"].astype(float).clip(lower=1e-9).fillna(1).values,
        "tau": m["masa_simpan"].astype(float).fillna(365).values,
        "c_w": harga,
        "c_h": harga * biaya["biaya_simpan_persen"] / 100.0,
        "c_s": m["biaya_kehabisan"].astype(float).fillna(0).values,
        "c_o": np.full(len(skus), float(biaya["biaya_pesan"])),
        "m_manual": m["maks_kelipatan"].values if "maks_kelipatan" in m else np.full(len(skus), np.nan),
    }


def data_mingguan(wide, f1, f2, skus, weeks):
    """Array [bahan, minggu, 7] berisi pemakaian aktual dan prediksi out-of-sample (dipasangkan per hari)."""
    D, F1, F2 = [], [], []
    for w in weeks:
        days = pd.date_range(w, periods=7)
        D.append(wide.loc[days, skus].values.T)
        F1.append(f1.reindex(days)[skus].values.T)
        F2.append(f2.reindex(days)[skus].fillna(f1.reindex(days)[skus]).values.T)
    return {"d": np.stack(D, 1), "f1": np.nan_to_num(np.stack(F1, 1)), "f2": np.nan_to_num(np.stack(F2, 1))}


def lengkapi_agen(par, data, sigma, d_hist):
    """Batas interval state, rata-rata pemakaian, parameter K1, ruang aksi (m), dan kapasitas simpan dari data latih.

    m (kelipatan pemesanan maksimum, Tabel 5) disesuaikan dengan kapasitas simpan: bila kapasitas (dalam kemasan)
    sudah diisi di data master, m = kapasitas dan kap = kapasitas x k. Bila belum, kapasitas otomatis dipilih agar
    mencakup stok target order-up-to tertinggi pada data latih (dengan cadangan 20%) dan stok tertinggi K1
    (ROP statis + jumlah pesan), lalu m = kap / k dibatasi QL_M_MAKS.
    """
    n = len(par["k"])
    d = data["d"].reshape(n, -1)
    f1 = data["f1"].reshape(n, -1)
    f2 = data["f2"].reshape(n, -1)
    par["edges"] = [tepi_bin(d[i], f1[i]) for i in range(n)]
    par["d_bar"] = d.mean(1)
    par["sigma"] = np.nan_to_num(sigma)
    par.update(SIM.parameter_k1(d_hist, par))
    out = f1 + f2 + C.Z_LAYANAN * par["sigma"][:, None] * math.sqrt(C.LEAD_TIME + 1)
    k = par["k"]
    U = np.maximum(1.2 * out.max(1), par["rop1"] + par["q1"])
    kap_auto = np.maximum(k * np.ceil(U / k - 1e-9), 2 * k)
    m_auto = np.clip(np.ceil(kap_auto / k - 1e-9), 2, C.QL_M_MAKS).astype(int)
    manual = np.nan_to_num(np.asarray(par.get("m_manual", np.full(n, np.nan)), float), nan=0).astype(int)
    par["m"] = np.where(manual > 0, manual, m_auto)
    par["kap"] = np.where(manual > 0, manual * k, kap_auto)
    par["kap_manual"] = manual > 0
    return par


def prakiraan_periode(pm: PeramalXGB, model, skala, mulai, T, skus, metode=None):
    """yh1/yh2 [bahan, T] untuk keputusan akhir hari mulai+0 .. mulai+T-1."""
    origins = [mulai + pd.Timedelta(days=j) for j in range(T)]
    p = pm.prakiraan_2_langkah(model, skala, origins, metode=metode)
    yh1 = np.array([p["f1"].loc[o + pd.Timedelta(days=1), skus].values for o in origins]).T
    yh2 = np.array([p["f2"].loc[o + pd.Timedelta(days=2), skus].values for o in origins]).T
    return yh1, yh2


VARIAN_AKTUAL = ("K1A", "K1", "K2", "K3")
PASANGAN_UJI = (("K3", "K1"), ("K3", "K2"), ("K2", "K1"))
PASANGAN_AKTUAL = (("K3", "K1A"), ("K2", "K1A"), ("K1", "K1A"), ("K3", "K2"))
MIN_HARI_AKTUAL = 7          # di bawah ini hasil K1 aktual ditandai belum layak disimpulkan


def evaluasi_aktual(masuk: dict | None, sp: dict, skus: list, par: dict, d_test, yh1, yh2, agen, n_seed: int,
                    log=print) -> dict:
    """K1 aktual: barang yang benar-benar diterima cafe diputar ulang pada lingkungan simulasi yang sama.

    masuk : {"baris": DataFrame tanggal, sku, jumlah (satuan dasar, NaN = belum diketahui),
             "hari": tanggal yang punya laporan barang masuk}
    Periode = hari berurutan berlaporan di dalam periode uji. Bahan yang diuji = bahan yang dimodelkan dan punya
    barang masuk tercatat di periode itu; bahan dengan barang masuk yang jumlahnya belum diketahui dikecualikan.
    Barang masuk untuk bahan yang tidak dimodelkan (di luar bahan target) hanya dihitung jumlah bahannya.
    K1 statis, K2, dan K3 dijalankan ulang pada hari dan bahan yang sama dari stok awal yang sama:
      - skenario utama: taksiran stok awal aktual (stok terkecil agar barang masuk aktual cukup untuk pemakaian
        aktual, karena pemakaian di stok keluar benar-benar terjadi), dan
      - 5 tingkat stok awal seperti uji 28 hari, sebagai uji kepekaan.
    """
    uji_mulai = sp["val_end"] + pd.Timedelta(days=1)
    dasar = {"periode_uji": [str(uji_mulai.date()), str(sp["test_end"].date())],
             "pemakaian_sampai": str(sp["test_end"].date()), "min_hari": MIN_HARI_AKTUAL}
    if not masuk or not len(masuk.get("hari", [])):
        return {**dasar, "status": "tidak ada", "pesan": "Belum ada catatan barang masuk cafe."}
    hari = sorted(pd.Timestamp(h) for h in masuk["hari"])
    dasar["catatan"] = [str(hari[0].date()), str(hari[-1].date())]
    jendela = SIM.jendela_aktual(hari, sp["test_end"], mulai=uji_mulai)
    if not jendela:
        return {**dasar, "status": "tidak beririsan", "n_hari": 0,
                "pesan": (f"Barang masuk tercatat {hari[0]:%d/%m/%Y} s.d. {hari[-1]:%d/%m/%Y}, sedangkan data "
                          f"pemakaian model ini sampai {sp['test_end']:%d/%m/%Y}.")}
    t0, T = (jendela[0] - uji_mulai).days, len(jendela)
    b = masuk["baris"].copy()
    b["tanggal"] = pd.to_datetime(b["tanggal"])
    b = b[(b["tanggal"] >= jendela[0]) & (b["tanggal"] <= jendela[-1])]
    pos = {s: i for i, s in enumerate(skus)}
    pakai, dikecualikan, n_luar = [], [], 0
    for sku, g in b.groupby("sku"):
        if sku not in pos:
            n_luar += 1
        elif g["jumlah"].isna().any():
            dikecualikan.append({"sku": sku, "alasan": "jumlah barang masuk belum diketahui (isi kemasan)"})
        else:
            pakai.append(sku)
    d_win = d_test[:, t0:t0 + T]
    tanpa_masuk = [s for i, s in enumerate(skus) if s not in set(b["sku"]) and d_win[i].sum() > 0]
    dasar.update({"periode": [str(jendela[0].date()), str(jendela[-1].date())], "n_hari": T,
                  "dikecualikan": dikecualikan, "n_tanpa_masuk": len(tanpa_masuk), "tanpa_masuk": tanpa_masuk,
                  "n_luar_cakupan": n_luar})
    if not pakai:
        return {**dasar, "status": "tidak ada bahan", "pesan": "Tidak ada bahan dengan barang masuk yang bisa dipakai."}
    idx = np.array([pos[s] for s in pakai])
    Q = np.zeros((len(pakai), T))
    for r in b[b["sku"].isin(pakai)].itertuples(index=False):
        Q[pakai.index(r.sku), (r.tanggal - jendela[0]).days] += float(r.jumlah)
    p = {k: np.asarray(par[k])[idx] for k in ("k", "tau", "c_h", "c_s", "c_w", "c_o", "rop1", "q1", "kap")}
    p["q_aktual"] = Q
    d_pakai = d_test[idx, t0:t0 + T]
    s0 = SIM.taksir_stok_awal(d_pakai, Q)
    harian = {}
    runs = SIM.evaluasi(p, d_pakai, yh1[idx, t0:t0 + T], yh2[idx, t0:t0 + T], par["sigma"][idx],
                        agen=agen, ruang_list=[par["edges"][i] for i in idx], n_seed=n_seed, d_bar=par["d_bar"][idx],
                        varian=VARIAN_AKTUAL, indeks_agen=idx, n_agen=len(skus), stok_awal_tetap=s0, harian=harian)
    runs["sku"] = [pakai[i] for i in runs["b"]]
    log(f"K1 aktual: {T} hari ({jendela[0]:%d/%m} s.d. {jendela[-1]:%d/%m}), {len(pakai)} bahan dengan barang masuk "
        f"tercatat, {len(dikecualikan)} bahan dikecualikan, {len(tanpa_masuk)} bahan tanpa barang masuk tercatat")
    return {**dasar, "status": "ok", "skus": pakai, "runs": runs, "q": Q, "stok_awal": s0, "pakai": d_pakai,
            "hari": [str(h.date()) for h in jendela], "harian": harian}


def jalankan(long: pd.DataFrame, master: pd.DataFrame, biaya: dict = None, tuning=False, n_seed=5,
             n_episode=C.QL_EPISODE, log=print, simpan=True, grid_search=True, best_params=None,
             folder_artefak=None, folder_laporan=None, ql_params=None, masuk: dict | None = None) -> dict:
    """masuk: catatan barang masuk cafe untuk K1 aktual (lihat evaluasi_aktual), boleh None."""
    t_mulai = time.time()
    biaya = biaya or {"biaya_pesan": C.BIAYA_PESAN, "biaya_simpan_persen": C.BIAYA_SIMPAN_PERSEN}
    wide = tabel_lebar(long)
    sp = tentukan_split(wide.index.max(), wide.index.min())
    log(f"Data {wide.index.min().date()} s.d. {wide.index.max().date()} ({len(wide)} hari, {wide.shape[1]} bahan); "
        f"latih s.d. {sp['train_end'].date()}, validasi s.d. {sp['val_end'].date()}, uji s.d. {sp['test_end'].date()}")

    # ---------------- 0. praproses: saringan bahan kosong / banyak nilai 0 dan bahan target penelitian
    pemilihan = PR.susun_pemilihan(wide, master, sp["train_end"], sp["val_end"])
    items = [s for s in wide.columns if pemilihan.loc[s, "dimodelkan"]]
    rp = PR.ringkas(pemilihan, sp["val_end"])
    log(f"Praproses: {rp['n_data']} bahan di data, {rp['n_kosong']} kosong dan {rp['n_banyak_nol']} banyak nilai 0 "
        f"dikeluarkan (ADI > {C.ADI_MAKS:g}), {rp['n_lolos']} lolos saringan, {rp['n_layak']} di antaranya cepat rusak")
    log(f"Bahan target ({len(rp['target'])}): " + ", ".join(str(pemilihan.loc[s, 'nama']) for s in rp["target"]))
    if rp["beda_dari_otomatis"]:
        log("Catatan: daftar bahan target yang dikunci di config berbeda dari peringkat otomatis data ini untuk "
            + ", ".join(rp["beda_dari_otomatis"]))
    if not items:
        raise ValueError("Tidak ada bahan yang lolos praproses; periksa data stok keluar dan BAHAN_TARGET di config.")

    # ---------------- 1. XGBoost
    pm = PeramalXGB(wide, sp, items=items)
    res = pm.jalankan(pakai_grid_search=grid_search, best_params=best_params, log=log)
    best = res["best_params"]
    metode = res["met_val"]["metode_terbaik"] if C.PREDIKSI_INTEGRASI == "hibrida" else None
    oos = pm.prakiraan_oos_mingguan(best, sampai=wide.index.max(), log=log, metode=metode)

    skus = [s for s in pm.items if s in set(master["sku"])]
    par0 = susun_parameter(master, skus, biaya)
    sig_cv = res["sigma_cv"].reindex(skus).fillna(0).values
    sig_e = res["sigma_e"]["sigma_e"].reindex(skus).fillna(0).values
    sig_prod = res["sigma_prod"].reindex(skus).fillna(0).values
    oos_mulai = oos["titik_latih"][0]

    hasil = {"split": {k: str(v.date()) if hasattr(v, "date") else v for k, v in sp.items()}, "best_params": best,
             "pemilihan": pemilihan}

    # ---------------- 2. (opsional) pilih alpha, gamma pada periode validasi
    ql_params = ql_params or {}
    alpha, gamma = float(ql_params.get("alpha", C.QL_ALPHA)), float(ql_params.get("gamma", C.QL_GAMMA))
    tuning_rows = []
    T_val = (sp["val_end"] - sp["train_end"]).days
    if tuning:
        wk = minggu_penuh(oos_mulai, sp["train_end"])
        data = data_mingguan(wide, oos["f1"], oos["f2"], skus, wk)
        par = lengkapi_agen(dict(par0), data, sig_cv, wide.loc[:sp["train_end"], skus].values.T)
        d_val = wide.loc[sp["train_end"] + pd.Timedelta(days=1):sp["val_end"], skus].values.T
        yh1, yh2 = prakiraan_periode(pm, pm.model_val, pm.sk_train, sp["train_end"], T_val, skus, metode)
        log(f"Tuning Q-Learning pada validasi ({len(wk)} minggu latih)")
        for a_ in C.QL_TUNING_GRID["alpha"]:
            for g_ in C.QL_TUNING_GRID["gamma"]:
                agen, _ = latih_agen(par, data, seeds=C.SIM_SEED[:2], n_episode=n_episode, alpha=a_, gamma=g_,
                                     log=lambda *_: None)
                runs = SIM.evaluasi(par, d_val, yh1, yh2, par["sigma"], agen=agen, ruang_list=par["edges"],
                                    n_seed=2, d_bar=par["d_bar"], varian=("K3",))
                tc = runs.groupby(["stok_awal", "seed"])["TC"].sum().mean()
                tuning_rows.append({"alpha": a_, "gamma": g_, "TC_validasi": float(tc)})
                log(f"  alpha={a_} gamma={g_}: total biaya validasi Rp {tc:,.0f}")
        best_t = min(tuning_rows, key=lambda r: r["TC_validasi"])
        alpha, gamma = best_t["alpha"], best_t["gamma"]
        log(f"Parameter Q-Learning terpilih: alpha={alpha}, gamma={gamma}")
    hasil["ql_params"] = {"alpha": alpha, "gamma": gamma, "episode": n_episode}
    hasil["tuning"] = tuning_rows

    # ---------------- 3. agen akhir (latih s.d. akhir validasi) dan uji K1/K2/K3 pada data uji
    wk = minggu_penuh(oos_mulai, sp["val_end"])
    data = data_mingguan(wide, oos["f1"], oos["f2"], skus, wk)
    par = lengkapi_agen(dict(par0), data, sig_e, wide.loc[:sp["val_end"], skus].values.T)
    T_test = (sp["test_end"] - sp["val_end"]).days
    d_test = wide.loc[sp["val_end"] + pd.Timedelta(days=1):sp["test_end"], skus].values.T
    yh1, yh2 = prakiraan_periode(pm, pm.model_final, pm.sk_final, sp["val_end"], T_test, skus, metode)
    log(f"Melatih agen Q-Learning: {len(skus)} bahan x {n_seed} seed, {n_episode} episode, {len(wk)} minggu latih")
    t0 = time.time()
    agen, kurva = latih_agen(par, data, seeds=C.SIM_SEED[:n_seed], n_episode=n_episode, alpha=alpha, gamma=gamma,
                             log=log)
    log(f"Pelatihan agen selesai ({time.time() - t0:.0f} detik)")
    harian = {}
    runs = SIM.evaluasi(par, d_test, yh1, yh2, par["sigma"], agen=agen, ruang_list=par["edges"], n_seed=n_seed,
                        d_bar=par["d_bar"], harian=harian)
    runs["sku"] = [skus[b] for b in runs["b"]]
    hasil["aktual"] = evaluasi_aktual(masuk, sp, skus, par, d_test, yh1, yh2, agen, n_seed, log=log)
    if hasil["aktual"]["status"] != "ok" and masuk:
        log(f"K1 aktual belum dihitung: {hasil['aktual'].get('pesan', '')}")
    hasil.update({"runs": runs, "harian": harian, "d_test": d_test, "kurva": kurva, "skus": skus, "par_uji": par,
                  "res_xgb": res,
                  "periode_uji": [str((sp["val_end"] + pd.Timedelta(days=1)).date()), str(sp["test_end"].date())],
                  "minggu_latih_agen": [str(w.date()) for w in wk]})

    # ---------------- 4. model produksi: XGBoost semua data + agen dari semua minggu OOS
    model_prod, sk_prod = pm.model_semua_data(best)
    wk_all = minggu_penuh(oos_mulai, wide.index.max())
    data_all = data_mingguan(wide, oos["f1"], oos["f2"], skus, wk_all)
    par_p = lengkapi_agen(dict(par0), data_all, sig_prod, wide[skus].values.T)
    log(f"Melatih agen produksi ({len(wk_all)} minggu latih)")
    agen_p, kurva_p = latih_agen(par_p, data_all, seeds=[C.SIM_SEED[0]], n_episode=n_episode, alpha=alpha,
                                 gamma=gamma, log=log)
    hasil.update({"model_prod": model_prod, "sk_prod": sk_prod, "agen_prod": agen_p, "par_prod": par_p,
                  "kurva_prod": kurva_p, "pm": pm, "sigma_prod": sig_prod})
    hasil["durasi_detik"] = time.time() - t_mulai
    if simpan:
        simpan_artefak(hasil, master, folder=folder_artefak, log=log)
        tulis_laporan(hasil, master, folder=folder_laporan or folder_artefak, log=log)
    log(f"Selesai dalam {hasil['durasi_detik']:.0f} detik")
    return hasil


# ---------------------------------------------------------------------- simpan
def simpan_artefak(h: dict, master: pd.DataFrame, folder=None, log=print):
    folder = Path(folder or C.ARTEFAK)
    folder.mkdir(parents=True, exist_ok=True)
    h["model_prod"].save_model(str(folder / "xgb_model.json"))
    pm, par, agen = h["pm"], h["par_prod"], h["agen_prod"]
    meta = {
        "dibuat": datetime.now().isoformat(timespec="seconds"),
        "data_sampai": str(pm.wide.index.max().date()), "data_mulai": str(pm.wide.index.min().date()),
        "items": pm.items, "skala": {k: float(v) for k, v in h["sk_prod"].items()},
        "sigma_e": {s: float(v) for s, v in zip(h["skus"], h["sigma_prod"])},
        "best_params": h["best_params"], "split": h["split"], "ql_params": h["ql_params"],
        "target_mode": C.TARGET_MODE, "prediksi_integrasi": C.PREDIKSI_INTEGRASI,
        "metode_terbaik_validasi": h["res_xgb"]["met_val"]["metode_terbaik"].to_dict(),
    }
    (folder / "xgb_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    q_meta = {}
    for i, s in enumerate(h["skus"]):
        q_meta[s] = {"edges": par["edges"][i], "k": float(par["k"][i]), "m": int(par["m"][i]),
                     "kap": float(par["kap"][i]), "kap_manual": bool(par["kap_manual"][i]),
                     "d_bar": float(par["d_bar"][i]), "rop_k1": float(par["rop1"][i]), "q_k1": float(par["q1"][i])}
    np.savez_compressed(folder / "qtable.npz", Q=agen.Q, N=agen.N, skus=np.array(h["skus"]))
    (folder / "qtable_meta.json").write_text(json.dumps(q_meta, indent=1), encoding="utf-8")
    ev = ringkasan_evaluasi(h, master)
    (folder / "evaluasi.json").write_text(json.dumps(ev, indent=1, default=float), encoding="utf-8")
    if h.get("harian"):
        RC.simpan(h, folder)
    log(f"Artefak tersimpan di {folder}")


def _bahan_utama(h, master) -> list:
    """Bahan utama pada laporan = bahan target penelitian (ml/praproses.py) yang dimodelkan."""
    p = h.get("pemilihan")
    if p is None:
        return []
    return [s for s in h["skus"] if s in p.index and bool(p.loc[s, "target"])]


def _banding(runs: pd.DataFrame, skus: list, utama: list, nama: dict, varian, pasangan) -> tuple:
    """Tabel per bahan (rata-rata semua run) dan uji Wilcoxon satu arah per pasangan kebijakan."""
    from scipy.stats import wilcoxon

    def total(df):
        t = SIM.ringkas_total(df)
        return {v: {c: float(t.loc[v, c]) for c in t.columns} for v in t.index}

    per_b = SIM.ringkas_per_bahan(runs, skus)
    tabel = []
    for s in skus:
        row = {"sku": s, "nama": nama.get(s, s), "utama": s in utama}
        for v in varian:
            r = per_b[(per_b["sku"] == s) & (per_b["varian"] == v)]
            if len(r):
                r = r.iloc[0]
                for c in ("TC", "FR", "hari_stockout", "nilai_terbuang", "WR", "b_s", "b_w", "jumlah_pesan",
                          "total_diterima", "total_pakai", "b_h", "b_o", "total_kurang", "terbuang", "jumlah_awal",
                          "sisa_akhir", "stok_harian", "nilai_sisa", "nilai_diterima"):
                    row[f"{v}_{c}"] = float(r[f"{c}_mean"])
                row[f"{v}_TC_sd"] = float(r["TC_std"])
        tabel.append(row)
    tb = pd.DataFrame(tabel)

    def menang(df, a, b):
        return int((df[f"{a}_TC"] < df[f"{b}_TC"] - 1e-9).sum())

    uji = {}
    for label, df_runs, df_tb in (("utama", runs[runs["sku"].isin(utama)], tb[tb["utama"]] if len(tb) else tb),
                                  ("semua", runs, tb)):
        if not len(df_tb):
            uji[label] = {"total": {}, "banding": {}, "n_bahan": 0}
            continue
        w = {}
        for a, b in pasangan:
            if f"{a}_TC" not in df_tb or f"{b}_TC" not in df_tb:
                continue
            x, y = df_tb[f"{a}_TC"].values, df_tb[f"{b}_TC"].values
            try:
                p = float(wilcoxon(x, y, alternative="less").pvalue) if np.any(x != y) else 1.0
            except ValueError:
                p = 1.0
            w[f"{a}_vs_{b}"] = {"menang": menang(df_tb, a, b), "dari": int(len(df_tb)), "p_wilcoxon": p,
                                "rasio_median": float(np.nanmedian(x / np.where(y > 0, y, np.nan)))
                                if np.any(y > 0) else None}
        uji[label] = {"total": total(df_runs), "banding": w, "n_bahan": int(len(df_tb))}
    return tb, uji


def ringkas_aktual(h: dict, master: pd.DataFrame, utama: list) -> dict | None:
    a = h.get("aktual")
    if not a:
        return None
    out = {k: v for k, v in a.items() if k not in ("runs", "q", "stok_awal", "pakai", "harian")}
    nama = master.set_index("sku")["nama"].to_dict()
    for x in out.get("dikecualikan", []):
        x["nama"] = nama.get(x["sku"], x["sku"])
    out["tanpa_masuk"] = [{"sku": s, "nama": nama.get(s, s)} for s in out.get("tanpa_masuk", [])]
    if a.get("status") != "ok":
        return out
    runs = a["runs"]
    taksir = runs["stok_awal"] == SIM.STOK_AWAL_TAKSIRAN
    tb, uji = _banding(runs[taksir], a["skus"], utama, nama, VARIAN_AKTUAL, PASANGAN_AKTUAL)
    tb5, uji5 = _banding(runs[~taksir], a["skus"], utama, nama, VARIAN_AKTUAL, PASANGAN_AKTUAL)
    tb["diterima_aktual"] = a["q"].sum(1)
    tb["pakai_aktual"] = a["pakai"].sum(1)
    tb["stok_awal_taksiran"] = a["stok_awal"]
    for v in VARIAN_AKTUAL:
        if f"{v}_TC" in tb5:
            tb[f"{v}_TC_5awal"] = tb5[f"{v}_TC"].values
    out.update({"kebijakan": uji, "kebijakan_5awal": uji5,
                "per_bahan": tb.where(tb.notna(), None).to_dict(orient="records"),
                "layak": a["n_hari"] >= MIN_HARI_AKTUAL})
    return out


def ringkasan_evaluasi(h: dict, master: pd.DataFrame) -> dict:
    res = h["res_xgb"]
    utama = _bahan_utama(h, master)
    nama = master.set_index("sku")["nama"].to_dict()
    tb, uji = _banding(h["runs"], h["skus"], utama, nama, ("K1", "K2", "K3"), PASANGAN_UJI)

    rk = res["ringkasan"].reset_index()
    return {
        "dibuat": datetime.now().isoformat(timespec="seconds"),
        "split": h["split"], "periode_uji": h["periode_uji"], "best_params": h["best_params"],
        "ql_params": h["ql_params"], "tuning": h["tuning"], "minggu_latih_agen": h["minggu_latih_agen"],
        "xgb_ringkasan": rk.where(rk.notna(), None).to_dict(orient="records"),
        "xgb_ringkasan_val": res["ringkasan_val"].reset_index().where(lambda d: d.notna(), None).to_dict(orient="records"),
        "xgb_horizon": {int(k): float(v) for k, v in res["mae_h"].items()},
        "xgb_menang_ma7": int((res["met_test"]["RMSE_xgboost"] < res["met_test"]["RMSE_ma_7"]).sum()),
        "xgb_n_bahan": int(len(res["met_test"])),
        "pemilihan": PR.ringkas(h["pemilihan"], h["split"]["val_end"]) if h.get("pemilihan") is not None else None,
        "kebijakan": uji, "bahan_utama": utama, "aktual": ringkas_aktual(h, master, utama),
        "per_bahan": tb.where(tb.notna(), None).to_dict(orient="records"),
        "kurva": {"titik": list(range(50, 50 * (len(h["kurva"]) + 1), 50)),
                  "rata": h["kurva"].mean(1).tolist() if len(h["kurva"]) else []},
        "biaya": {"biaya_pesan": float(h["par_uji"]["c_o"][0]) if len(h["par_uji"]["c_o"]) else None},
        "durasi_detik": h.get("durasi_detik"),
    }


def tulis_laporan(h: dict, master: pd.DataFrame, folder=None, log=print):
    """Laporan Excel untuk Bab 4 skripsi: evaluasi XGBoost dan simulasi K1/K2/K3."""
    folder = Path(folder or C.LAPORAN)
    folder.mkdir(parents=True, exist_ok=True)
    res = h["res_xgb"]
    info = master.set_index("sku")[["nama", "satuan", "kategori"]]
    with pd.ExcelWriter(folder / "evaluasi_xgboost.xlsx") as w:
        res["ringkasan"].to_excel(w, sheet_name="Ringkasan Uji")
        res["ringkasan_val"].to_excel(w, sheet_name="Ringkasan Validasi")
        met = info.join(res["met_test"], how="right").join(res["met_val"][["metode_terbaik"]]).join(res["sigma_e"])
        met.insert(3, "rata_pemakaian", res["sk_final"].reindex(met.index).values)
        met.to_excel(w, sheet_name="Per Bahan (Uji)")
        res["mae_h"].rename("nMAE").to_frame().to_excel(w, sheet_name="Horizon Rekursif")
        if res["grid"] is not None:
            res["grid"].to_excel(w, sheet_name="Grid Search", index=False)
        res["te_df"].to_excel(w, sheet_name="Prediksi Uji", index=False)
        if h.get("pemilihan") is not None:
            tulis_lembar_pemilihan(w, h)
    ev = ringkasan_evaluasi(h, master)
    runs = h["runs"].copy()
    runs["nama"] = runs["sku"].map(info["nama"])
    with pd.ExcelWriter(folder / "simulasi_K1_K2_K3.xlsx") as w:
        rows = []
        for label in ("utama", "semua"):
            for v, d in ev["kebijakan"][label]["total"].items():
                rows.append({"kelompok bahan": label, "varian": v, **d})
        pd.DataFrame(rows).to_excel(w, sheet_name="Ringkasan", index=False)
        rows = []
        for label in ("utama", "semua"):
            for k, d in ev["kebijakan"][label]["banding"].items():
                rows.append({"kelompok bahan": label, "perbandingan": k, **d})
        pd.DataFrame(rows).to_excel(w, sheet_name="Perbandingan", index=False)
        pd.DataFrame(ev["per_bahan"]).to_excel(w, sheet_name="Per Bahan", index=False)
        runs.to_excel(w, sheet_name="Semua Run", index=False)
        par = h["par_uji"]
        pd.DataFrame({"sku": h["skus"], "nama": [info["nama"].get(s, s) for s in h["skus"]],
                      "k": par["k"], "m": par["m"], "kapasitas": par["kap"], "masa_simpan": par["tau"],
                      "c_h": par["c_h"], "c_s": par["c_s"], "c_w": par["c_w"], "c_o": par["c_o"],
                      "sigma_e": par["sigma"], "d_bar": par["d_bar"], "ROP_K1": par["rop1"], "Q_K1": par["q1"]}
                     ).to_excel(w, sheet_name="Parameter", index=False)
        if h["tuning"]:
            pd.DataFrame(h["tuning"]).to_excel(w, sheet_name="Tuning Validasi", index=False)
        k = h["kurva"]
        if len(k):
            pd.DataFrame({"episode": ev["kurva"]["titik"], "rata_reward_semua_agen": k.mean(1)}).to_excel(
                w, sheet_name="Kurva Pelatihan", index=False)
        tulis_lembar_aktual(w, h, ev, info)
        if h.get("harian"):
            RC.tulis_lembar(w, h, ev, info)
    log(f"Laporan Excel tersimpan di {folder}")


def tulis_lembar_pemilihan(w, h: dict):
    """Lembar praproses pada laporan evaluasi: aturan, bahan target, dan tabel pemilihan semua bahan."""
    rp = PR.ringkas(h["pemilihan"], h["split"]["val_end"])
    a = rp["aturan"]
    aturan = [
        ("Data yang dipakai untuk memilih", f"latih + validasi, s.d. {a['data_sampai']} ({a['n_hari']} hari)"),
        ("Bahan di data stok keluar", rp["n_data"]),
        ("Dikeluarkan: kosong (tidak pernah terpakai pada periode itu)", rp["n_kosong"]),
        (f"Dikeluarkan: banyak nilai 0 (ADI > {a['adi_maks']:g}, nilai 0 pada > {a['proporsi_nol_maks']:.1%} hari)",
         rp["n_banyak_nol"]),
        ("Lolos saringan data", rp["n_lolos"]),
        (f"Layak jadi bahan target (masa simpan <= {a['masa_simpan_maks']} hari, bukan "
         f"{', '.join(a['kelompok_dikecualikan'])})", rp["n_layak"]),
        ("Peringkat", "rata-rata peringkat frekuensi pemakaian dan peringkat nilai pemakaian per hari (Rp)"),
        ("Jumlah bahan target", len(rp["target"])),
        ("Daftar bahan target dikunci di config", "ya" if a["target_dikunci"] else "tidak (otomatis)"),
        ("Bahan yang dimodelkan", f"{rp['n_dimodelkan']} ({'bahan target saja' if a['cakupan_model'] == 'target' else 'semua bahan lolos saringan'})"),
    ]
    pd.DataFrame(aturan, columns=["keterangan", "nilai"]).to_excel(w, sheet_name="Aturan Pemilihan", index=False)
    t = pd.DataFrame(rp["tabel"])
    judul = {"sku": "SKU", "nama": "Nama", "kategori": "Kategori", "satuan": "Satuan", "masa_simpan": "Masa simpan (hari)",
             "hari_terpakai": "Hari terpakai", "proporsi_nol": "Proporsi hari bernilai 0", "adi": "ADI",
             "rata_harian": "Rata-rata pemakaian per hari", "harga_satuan": "Harga satuan (Rp)",
             "sumber_harga": "Sumber harga", "nilai_harian": "Nilai pemakaian per hari (Rp)",
             "lolos": "Lolos saringan data", "alasan": "Alasan dikeluarkan", "layak": "Layak jadi target",
             "peringkat_frekuensi": "Peringkat frekuensi", "peringkat_nilai": "Peringkat nilai", "skor": "Skor",
             "peringkat": "Peringkat", "target": "Bahan target", "target_otomatis": "Target menurut peringkat",
             "dimodelkan": "Dimodelkan"}
    for k in ("lolos", "layak", "target", "target_otomatis", "dimodelkan"):
        t[k] = t[k].map({True: "ya", False: "tidak"})
    t.rename(columns=judul).to_excel(w, sheet_name="Pemilihan Bahan", index=False)


def tulis_lembar_aktual(w, h: dict, ev: dict, info: pd.DataFrame):
    """Lembar K1 aktual pada laporan simulasi: ringkasan, perbandingan, per bahan, barang masuk, semua run."""
    a, ra = h.get("aktual") or {}, ev.get("aktual") or {}
    keterangan = [
        ("K1 aktual", "barang yang benar-benar diterima cafe (catatan barang masuk WhatsApp) diputar ulang apa adanya"),
        ("K1 statis", "ROP statis + EOQ, dihitung dari data historis (sama seperti uji 28 hari)"),
        ("Catatan barang masuk", " s.d. ".join(ra.get("catatan", [])) or "-"),
        ("Data pemakaian sampai", ra.get("pemakaian_sampai", "-")),
        ("Periode K1 aktual", " s.d. ".join(ra.get("periode", [])) or "-"),
        ("Jumlah hari", ra.get("n_hari", 0)),
        ("Status", ra.get("status", "tidak ada") + (f": {ra['pesan']}" if ra.get("pesan") else "")),
    ]
    if ra.get("status") == "ok" and not ra.get("layak"):
        keterangan.append(("Peringatan", f"periode kurang dari {ra['min_hari']} hari; hasil belum layak disimpulkan"))
    rows = [{"keterangan": k, "nilai": v} for k, v in keterangan]
    for x in ra.get("dikecualikan", []):
        rows.append({"keterangan": f"Dikecualikan: {x['sku']} {x.get('nama', '')}", "nilai": x["alasan"]})
    if ra.get("n_tanpa_masuk"):
        rows.append({"keterangan": "Bahan terpakai tanpa barang masuk tercatat (tidak diuji)",
                     "nilai": ra["n_tanpa_masuk"]})
    pd.DataFrame(rows).to_excel(w, sheet_name="K1 Aktual Info", index=False)
    if ra.get("status") != "ok":
        return
    rows, rows_b = [], []
    for skenario, kunci in (("taksiran stok awal aktual", "kebijakan"), ("rata-rata 5 tingkat stok awal",
                                                                         "kebijakan_5awal")):
        for label in ("utama", "semua"):
            kb = ra[kunci][label]
            for v, d in kb["total"].items():
                rows.append({"stok awal": skenario, "kelompok bahan": label, "varian": v, **d})
            for k, d in kb["banding"].items():
                rows_b.append({"stok awal": skenario, "kelompok bahan": label, "perbandingan": k, **d})
    pd.DataFrame(rows).to_excel(w, sheet_name="K1 Aktual Ringkasan", index=False)
    pd.DataFrame(rows_b).to_excel(w, sheet_name="K1 Aktual Perbandingan", index=False)
    pd.DataFrame(ra["per_bahan"]).to_excel(w, sheet_name="K1 Aktual Per Bahan", index=False)
    q = pd.DataFrame(a["q"], columns=[pd.Timestamp(t).strftime("%d/%m/%Y") for t in a["hari"]])
    q.insert(0, "satuan", [info["satuan"].get(s, "") for s in a["skus"]])
    q.insert(0, "nama", [info["nama"].get(s, s) for s in a["skus"]])
    q.insert(0, "sku", a["skus"])
    q["total masuk"] = a["q"].sum(1)
    q["total pakai"] = a["pakai"].sum(1)
    q["taksiran stok awal"] = a["stok_awal"]
    q.to_excel(w, sheet_name="K1 Aktual Barang Masuk", index=False)
    runs = a["runs"].copy()
    runs["nama"] = runs["sku"].map(info["nama"])
    runs.to_excel(w, sheet_name="K1 Aktual Semua Run", index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tuning", action="store_true", help="pilih alpha/gamma Q-Learning pada periode validasi")
    ap.add_argument("--episode", type=int, default=C.QL_EPISODE)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--tanpa-grid", action="store_true", help="pakai hiperparameter XGBoost terbaik yang tersimpan")
    a = ap.parse_args()
    from app.layanan import catatan_manual as CM
    from ml.master import susun_master
    long = pd.read_excel(C.FILE_STOK_KELUAR, sheet_name="Stok Keluar (Long)", engine="openpyxl")
    master = susun_master()
    catatan, _ = CM.dari_folder(C.FOLDER_CATATAN, CM.Master.dari_tabel(master))
    jalankan(long, master, tuning=a.tuning, n_seed=a.seed, n_episode=a.episode,
             grid_search=not a.tanpa_grid, best_params=C.MANUAL_PARAMS if a.tanpa_grid else None,
             masuk=CM.data_k1_aktual(catatan))
