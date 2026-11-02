"""Simulasi pengujian kebijakan K1, K2, K3 (subbab 8.9 dan Tabel 4 proposal).

K1  (K1 statis) ROP statis dari rata-rata dan simpangan baku historis, jumlah tetap min(EOQ, d*tau)
    (kebijakan (s, Q)).
K1A (K1 aktual) barang yang benar-benar diterima cafe menurut catatan barang masuk diputar ulang apa adanya:
    jumlah tiba hari t = barang masuk tercatat hari t (tanpa pembulatan kemasan dan tanpa batas kapasitas).
K2  ROP dinamis dari prediksi XGBoost, jumlah order-up-to (Persamaan 25-26).
K3  Agen Q-Learning dengan state berisi prediksi XGBoost dan status ROP dinamis; state yang belum pernah
    ditemui saat pelatihan memakai aturan cadangan K2 (Gambar 3).

Semua varian memakai data pemakaian, stok awal, dan parameter biaya yang identik. Setiap varian diulang
dengan beberapa stok awal; K3 juga dengan beberapa seed pelatihan.
"""
import math

import numpy as np
import pandas as pd

import config as C
from ml.kebijakan import q_klasik, rop_statis
from ml.lingkungan import Lingkungan
from ml.qlearning import RuangState

STOK_AWAL_TAKSIRAN = -1.0      # label skenario stok awal hasil taksiran (bukan kelipatan rata-rata pemakaian)
METRIK = ["TC", "b_h", "b_s", "b_w", "b_o", "hari_stockout", "FR", "terbuang", "nilai_terbuang", "WR",
          "jumlah_pesan", "total_diterima", "total_pakai", "total_kurang", "cadangan"]


def _ceil_k(x, k):
    return k * np.ceil(np.maximum(x, 0.0) / k - 1e-9)


def _floor_k(x, k):
    with np.errstate(invalid="ignore"):
        return np.where(np.isinf(x), np.inf, k * np.floor(np.maximum(x, 0.0) / k + 1e-9))


def jalankan(varian: str, par: dict, d: np.ndarray, yh1: np.ndarray, yh2: np.ndarray, sigma: np.ndarray,
             stok_awal: np.ndarray, agen=None, ruang: RuangState = None, ia=None, catat_harian=False,
             min_kunjungan=C.QL_MIN_KUNJUNGAN) -> dict:
    """Jalankan satu varian untuk n lingkungan sekaligus.

    d   : [n, T] pemakaian aktual hari 1..T
    yh1 : [n, T] prediksi 1 langkah y_hat_{t+1|t} untuk keputusan akhir hari t = 0..T-1
    yh2 : [n, T] prediksi 2 langkah y_hat_{t+2|t}
    par : dict array [n]: k, tau, c_h, c_s, c_w, c_o, rop1, q1 (K1), kap (kapasitas simpan, opsional),
          q_aktual [n, T] (K1A: barang masuk tercatat yang tiba awal hari t)

    Kapasitas simpan berlaku untuk K1, K2, K3: jumlah pesan dibatasi agar posisi persediaan tidak melebihi kap.
    K1A memutar ulang barang yang benar-benar datang, jadi tidak dibatasi.
    """
    n, T = d.shape
    env = Lingkungan(par["tau"], par["c_h"], par["c_s"], par["c_w"], par["c_o"], n_umur=T + 4)
    env.reset(stok_awal)
    k = par["k"]
    kap = np.asarray(par["kap"], float) if "kap" in par else np.full(n, np.inf)
    zs1 = C.Z_LAYANAN * sigma * math.sqrt(C.LEAD_TIME)
    zs2 = C.Z_LAYANAN * sigma * math.sqrt(C.LEAD_TIME + 1)
    acc = {m: np.zeros(n) for m in ["b_h", "b_s", "b_w", "b_o", "hari_stockout", "terbuang", "jumlah_pesan",
                                    "total_diterima", "total_pakai", "total_kurang", "cadangan"]}
    harian = []
    for t in range(T):
        ip = env.posisi()
        rop = yh1[:, t] + zs1
        out = yh1[:, t] + yh2[:, t] + zs2
        if varian == "K1":
            q = np.where(ip <= par["rop1"], par["q1"], 0.0)
        elif varian == "K1A":
            q = np.asarray(par["q_aktual"], float)[:, t]
        elif varian == "K2":
            q = np.where(ip <= rop, _ceil_k(out - ip, k), 0.0)
        elif varian == "K3":
            e = env.hampir_kedaluwarsa()
            s = ruang.indeks(ip, yh1[:, t], e, ip <= rop)
            a = agen.greedy(s, ia, min_kunjungan, ip)
            cadangan = a < 0
            q = np.where(cadangan, np.where(ip <= rop, _ceil_k(out - ip, k), 0.0), agen.jumlah(np.maximum(a, 0), ia))
            acc["cadangan"] += cadangan
        else:
            raise ValueError(varian)
        if varian != "K1A":
            q = np.minimum(q, _floor_k(kap - ip, k))
        h = env.langkah(q, d[:, t])
        for c in ("b_h", "b_s", "b_w", "b_o"):
            acc[c] += h[c]
        acc["hari_stockout"] += h["S"] > 1e-9
        acc["terbuang"] += h["W"]
        acc["jumlah_pesan"] += q > 0
        acc["total_diterima"] += q
        acc["total_pakai"] += d[:, t]
        acc["total_kurang"] += h["S"]
        if catat_harian:
            harian.append({"ip": ip, "rop": rop, "out": out, "q": q, "W": h["W"], "S": h["S"], "I": h["I"]})
    acc["TC"] = acc["b_h"] + acc["b_s"] + acc["b_w"] + acc["b_o"]
    with np.errstate(divide="ignore", invalid="ignore"):
        acc["FR"] = np.where(acc["total_pakai"] > 0, 1 - acc["total_kurang"] / acc["total_pakai"], 1.0)
        acc["WR"] = np.where(acc["total_diterima"] > 0, acc["terbuang"] / acc["total_diterima"], 0.0)
    acc["nilai_terbuang"] = acc["b_w"]
    if catat_harian:
        acc["harian"] = harian
    return acc


def parameter_k1(d_hist: np.ndarray, par: dict) -> dict:
    """ROP statis (Persamaan 1-2) dan jumlah tetap (Persamaan 3, dibatasi masa simpan) per bahan."""
    d_bar = d_hist.mean(1)
    s_d = d_hist.std(1, ddof=1)
    rop1 = np.array([rop_statis(a, b) for a, b in zip(d_bar, s_d)])
    q1 = np.array([q_klasik(a, co, ch, tau, k) for a, co, ch, tau, k in
                   zip(d_bar, par["c_o"], par["c_h"], par["tau"], par["k"])])
    return {"rop1": rop1, "q1": q1, "d_bar_hist": d_bar, "sigma_d": s_d}


def evaluasi(par: dict, d: np.ndarray, yh1: np.ndarray, yh2: np.ndarray, sigma: np.ndarray,
             agen=None, ruang_list=None, n_seed=1, kelipatan_awal=C.SIM_STOK_AWAL, d_bar=None,
             varian=("K1", "K2", "K3"), min_kunjungan=C.QL_MIN_KUNJUNGAN, indeks_agen=None,
             n_agen=None, stok_awal_tetap=None) -> pd.DataFrame:
    """Jalankan varian kebijakan untuk semua bahan x stok awal (x seed untuk K3). Hasil: satu baris per run.

    indeks_agen, n_agen: bila hanya sebagian bahan yang diuji (K1 aktual), indeks setiap bahan pada agen K3 dan
    jumlah bahan per seed pada agen tersebut.
    stok_awal_tetap: skenario stok awal tambahan [bahan] (mis. taksiran stok awal aktual), dicatat dengan
    stok_awal = STOK_AWAL_TAKSIRAN.
    """
    n_b, T = d.shape
    d_bar = d.mean(1) if d_bar is None else d_bar
    awal = [np.full(n_b, m) * d_bar for m in kelipatan_awal]
    label_awal = [float(m) for m in kelipatan_awal]
    if stok_awal_tetap is not None:
        awal.append(np.asarray(stok_awal_tetap, float))
        label_awal.append(STOK_AWAL_TAKSIRAN)
    I = len(awal)
    idx_ag = np.arange(n_b) if indeks_agen is None else np.asarray(indeks_agen, int)
    n_ag = n_b if n_agen is None else int(n_agen)
    rows = []

    def ulang(x, kali):
        x = np.asarray(x)
        return np.tile(x, kali) if x.ndim == 1 else np.tile(x, (kali, 1))

    for v in varian:
        if (v == "K3" and agen is None) or (v == "K1A" and "q_aktual" not in par):
            continue
        reps = I * (n_seed if v == "K3" else 1)
        p = {key: ulang(val, reps) for key, val in par.items() if key in ("k", "tau", "c_h", "c_s", "c_w", "c_o",
                                                                           "rop1", "q1", "kap", "q_aktual")}
        # urutan lingkungan: [seed][stok awal][bahan]
        s0 = np.concatenate(awal * (reps // I))
        ruang, ia = None, None
        if v == "K3":
            ruang = RuangState(ruang_list * reps)
            # agen tersusun [seed][bahan]; lingkungan tersusun [seed][stok awal][bahan]
            ia = np.array([s * n_ag + idx_ag[b] for s in range(n_seed) for _ in range(I) for b in range(n_b)])
        res = jalankan(v, p, ulang(d, reps), ulang(yh1, reps), ulang(yh2, reps), ulang(sigma, reps), s0,
                       agen=agen if v == "K3" else None, ruang=ruang, ia=ia, min_kunjungan=min_kunjungan)
        for j in range(n_b * reps):
            b = j % n_b
            i = (j // n_b) % I
            s = j // (n_b * I)
            r = {"varian": v, "b": b, "stok_awal": label_awal[i], "seed": s if v == "K3" else -1}
            r.update({m: float(res[m][j]) for m in METRIK})
            rows.append(r)
    return pd.DataFrame(rows)


def ringkas_per_bahan(runs: pd.DataFrame, skus) -> pd.DataFrame:
    g = runs.groupby(["varian", "b"])[METRIK].agg(["mean", "std"])
    g.columns = [f"{a}_{b}" for a, b in g.columns]
    g = g.reset_index()
    g["sku"] = [skus[b] for b in g["b"]]
    return g


def ringkas_total(runs: pd.DataFrame) -> pd.DataFrame:
    """Total seluruh bahan per run (dijumlah antar bahan), lalu rata-rata dan simpangan baku antar-run."""
    per_run = runs.groupby(["varian", "stok_awal", "seed"]).agg(
        TC=("TC", "sum"), b_h=("b_h", "sum"), b_s=("b_s", "sum"), b_w=("b_w", "sum"), b_o=("b_o", "sum"),
        hari_stockout=("hari_stockout", "sum"), terbuang_nilai=("nilai_terbuang", "sum"),
        FR_rata=("FR", "mean"), WR_rata=("WR", "mean"), jumlah_pesan=("jumlah_pesan", "sum"),
        cadangan=("cadangan", "sum")).reset_index()
    out = per_run.groupby("varian").agg(["mean", "std"])
    out = out.drop(columns=[c for c in out.columns if c[0] in ("stok_awal", "seed")])
    out.columns = [f"{a}_{b}" for a, b in out.columns]
    return out


def jendela_aktual(hari, sampai, mulai=None) -> list:
    """Hari yang bisa dipakai K1 aktual: hari berurutan yang punya laporan barang masuk, mulai dari laporan
    pertama (>= mulai) sampai hari terakhir yang juga punya data pemakaian (<= sampai). Rentang berhenti di hari
    pertama tanpa laporan, karena barang masuk hari itu tidak diketahui."""
    out = []
    for h in sorted(pd.Timestamp(x) for x in hari):
        if mulai is not None and h < pd.Timestamp(mulai):
            continue
        if sampai is None or h > pd.Timestamp(sampai):
            break
        if out and (h - out[-1]).days != 1:
            break
        out.append(h)
    return out


def taksir_stok_awal(d: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Stok awal terkecil agar barang masuk aktual q cukup untuk pemakaian aktual d setiap hari.

    Pemakaian di data stok keluar benar-benar terjadi, jadi stok cafe pada pagi hari pertama paling sedikit
    max_t sum_{s<=t} (d_s - q_s). Barang masuk hari t tiba sebelum dipakai hari itu. Kedaluwarsa diabaikan.
    """
    kurang = np.cumsum(np.asarray(d, float) - np.asarray(q, float), axis=1)
    return np.maximum(kurang.max(axis=1), 0.0)
