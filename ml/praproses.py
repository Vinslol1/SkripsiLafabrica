"""Praproses cakupan bahan: saringan bahan kosong / didominasi nilai 0 dan pemilihan bahan target penelitian.

Dua tahap, keduanya dihitung dari data sebelum periode uji (latih + validasi) supaya data uji tidak ikut
menentukan bahan mana yang diteliti:

1. Saringan data. Bahan dikeluarkan dari dataset bila
     - kosong: tidak pernah terpakai pada periode itu, atau
     - didominasi nilai 0: jarak rata-rata antarhari pemakaian (ADI, average demand interval) > 1,32, artinya
       pemakaiannya 0 pada lebih dari kira-kira 24% hari. Batas 1,32 adalah batas pola permintaan intermiten pada
       klasifikasi Syntetos, Boylan & Croston (2005).
2. Bahan target penelitian. Dari bahan yang lolos saringan diambil bahan yang relevan dengan masalah penelitian
   (cepat rusak: masa simpan <= 30 hari sesuai batasan masalah; bukan kelompok Air & Minuman), lalu diurutkan
   menurut rata-rata dua peringkat: seberapa sering dipakai (proporsi hari terpakai) dan seberapa besar nilainya
   (rata-rata pemakaian per hari x harga satuan). Sepuluh teratas menjadi bahan target.

Daftar bahan target bisa dikunci di config.BAHAN_TARGET supaya tidak bergeser ketika data bertambah; tabel
pemilihan tetap dihitung ulang setiap pelatihan dan disimpan di evaluasi.json serta laporan Excel.
"""
import numpy as np
import pandas as pd

import config as C

KELOMPOK_DIKECUALIKAN = ("Air & Minuman",)


def profil_bahan(wide: pd.DataFrame, master: pd.DataFrame, latih_sampai, sampai) -> pd.DataFrame:
    """Statistik pemakaian tiap bahan pada data s.d. `sampai` (akhir validasi) dan data masternya."""
    m = master.set_index("sku")
    w = wide.loc[:sampai]
    n = len(w)
    terpakai = (w > 0).sum()
    p = pd.DataFrame({
        "nama": m["nama"].reindex(w.columns),
        "kategori": m["kategori"].reindex(w.columns),
        "satuan": m["satuan"].reindex(w.columns),
        "masa_simpan": pd.to_numeric(m["masa_simpan"].reindex(w.columns), errors="coerce"),
        "n_hari": n,
        "hari_terpakai": terpakai.astype(int),
        "proporsi_nol": 1 - terpakai / n,
        "adi": (n / terpakai.where(terpakai > 0)).astype(float),
        "rata_harian": w.mean(),
        "rata_latih": wide.loc[:latih_sampai].mean(),
        "harga_satuan": pd.to_numeric(m["harga_satuan"].reindex(w.columns), errors="coerce"),
        "sumber_harga": m["sumber_harga"].reindex(w.columns) if "sumber_harga" in m else "",
    })
    p["nilai_harian"] = p["rata_harian"] * p["harga_satuan"].fillna(0)
    p.index.name = "sku"
    return p


def saring(p: pd.DataFrame, adi_maks: float = None) -> pd.DataFrame:
    """Tahap 1: tandai bahan yang lolos saringan data (kolom lolos) dan alasan bahan yang dikeluarkan."""
    adi_maks = C.ADI_MAKS if adi_maks is None else adi_maks
    p = p.copy()
    alasan = pd.Series("", index=p.index)
    kosong = p["hari_terpakai"] == 0
    banyak_nol = ~kosong & (~(p["adi"] <= adi_maks) | ~(p["rata_latih"] > 0))
    tanpa_master = p["nama"].isna()
    alasan[kosong] = "kosong: tidak pernah terpakai pada periode latih dan validasi"
    alasan[banyak_nol] = [f"banyak nilai 0: {x:.0%} hari tanpa pemakaian (ADI {a:.2f} > {adi_maks:g})"
                          for x, a in zip(p.loc[banyak_nol, "proporsi_nol"], p.loc[banyak_nol, "adi"])]
    alasan[tanpa_master & (alasan == "")] = "tidak ada di data bahan"
    p["lolos"] = alasan == ""
    p["alasan"] = alasan
    return p


def pilih_target(p: pd.DataFrame, n: int = None, tetap=None) -> pd.DataFrame:
    """Tahap 2: peringkat bahan yang layak dan penanda bahan target.

    tetap: daftar SKU yang dikunci (config.BAHAN_TARGET). Bila diisi, bahan target = daftar itu (yang ada di data
    dan lolos saringan); kolom peringkat tetap dihitung dari aturan supaya bisa dibandingkan."""
    n = C.JUMLAH_BAHAN_TARGET if n is None else n
    p = p.copy()
    p["layak"] = (p["lolos"] & (p["masa_simpan"] <= C.MASA_SIMPAN_MAKS_TARGET)
                  & ~p["kategori"].isin(KELOMPOK_DIKECUALIKAN))
    k = p[p["layak"]]
    r_frek = (1 - k["proporsi_nol"]).round(6).rank(ascending=False, method="min")
    r_nilai = k["nilai_harian"].rank(ascending=False, method="min")
    skor = (r_frek + r_nilai) / 2
    urut = pd.DataFrame({"skor": skor, "r_nilai": r_nilai}).sort_values(["skor", "r_nilai"]).index
    p["peringkat_frekuensi"] = r_frek.reindex(p.index)
    p["peringkat_nilai"] = r_nilai.reindex(p.index)
    p["skor"] = skor.reindex(p.index)
    p["peringkat"] = pd.Series(np.arange(1, len(urut) + 1), index=urut).reindex(p.index)
    otomatis = list(urut[:n])
    if tetap:
        target = [s for s in tetap if s in p.index and p.loc[s, "lolos"]]
    else:
        target = otomatis
    p["target"] = p.index.isin(target)
    p["target_otomatis"] = p.index.isin(otomatis)
    return p


def susun_pemilihan(wide: pd.DataFrame, master: pd.DataFrame, latih_sampai, sampai) -> pd.DataFrame:
    """Profil + saringan + bahan target, dan bahan mana yang dimodelkan (kolom dimodelkan) sesuai CAKUPAN_MODEL."""
    p = pilih_target(saring(profil_bahan(wide, master, latih_sampai, sampai)), tetap=list(C.BAHAN_TARGET))
    if C.CAKUPAN_MODEL == "target":
        p["dimodelkan"] = p["target"]
    elif C.CAKUPAN_MODEL == "lolos":
        p["dimodelkan"] = p["lolos"]
    else:
        raise ValueError("CAKUPAN_MODEL harus target / lolos")
    return p


def ringkas(p: pd.DataFrame, sampai) -> dict:
    """Ringkasan pemilihan untuk evaluasi.json dan halaman aplikasi."""
    kol = ["nama", "kategori", "satuan", "masa_simpan", "hari_terpakai", "proporsi_nol", "adi", "rata_harian",
           "harga_satuan", "sumber_harga", "nilai_harian", "lolos", "alasan", "layak", "peringkat_frekuensi",
           "peringkat_nilai", "skor", "peringkat", "target", "target_otomatis", "dimodelkan"]
    t = p[kol].reset_index()
    t = t.sort_values(["target", "peringkat", "proporsi_nol"], ascending=[False, True, True])
    alasan = p.loc[~p["lolos"], "alasan"].str.split(":").str[0]
    return {
        "aturan": {"adi_maks": C.ADI_MAKS, "proporsi_nol_maks": 1 - 1 / C.ADI_MAKS,
                   "masa_simpan_maks": C.MASA_SIMPAN_MAKS_TARGET, "jumlah_target": C.JUMLAH_BAHAN_TARGET,
                   "kelompok_dikecualikan": list(KELOMPOK_DIKECUALIKAN), "cakupan_model": C.CAKUPAN_MODEL,
                   "target_dikunci": bool(C.BAHAN_TARGET), "data_sampai": str(pd.Timestamp(sampai).date()),
                   "n_hari": int(p["n_hari"].iloc[0]) if len(p) else 0},
        "n_data": int(len(p)), "n_lolos": int(p["lolos"].sum()), "n_layak": int(p["layak"].sum()),
        "n_kosong": int((alasan == "kosong").sum()), "n_banyak_nol": int((alasan == "banyak nilai 0").sum()),
        "n_dimodelkan": int(p["dimodelkan"].sum()),
        "target": [s for s in t.loc[t["target"], "sku"]],
        "beda_dari_otomatis": sorted(set(p.index[p["target"]]) ^ set(p.index[p["target_otomatis"]])),
        "tabel": t.where(t.notna(), None).to_dict(orient="records"),
    }
