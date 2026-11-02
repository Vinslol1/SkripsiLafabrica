"""Penyusunan data master bahan baku dari file Excel majoo, plus nilai sementara untuk data yang belum ada.

Sumber:
  - Ekspor Daftar Bahan Baku (majoo): nama, monitor persediaan, stok minimum, satuan dan konversi, SKU.
  - Ekspor Resep Produk (majoo): sheet "Daftar Bahan" (SKU dan satuan dasar), HPP dan harga jual menu.
  - Stok_Keluar_Harian_Bahan_Baku.xlsx: pemakaian harian, resep yang dipakai, dan penjualan menu harian.

Data yang belum tersedia (harga beli, masa simpan, ukuran kemasan pembelian) diisi nilai sementara dan
ditandai di kolom `asumsi` agar mudah dikoreksi lewat template Excel atau halaman Daftar Bahan Baku.
"""
import re

import numpy as np
import pandas as pd

import config as C
from ml.kebijakan import ukuran_kemasan_bawaan

# (pola nama, kelompok, masa simpan hari, harga sementara per gram, harga sementara per satuan non-gram).
# Urutan aturan penting: aturan pertama yang cocok dipakai.
ATURAN = [
    (r"^fresh milk", "Susu & Olahan", 7, 25, 25000),
    (r"ice cream", "Susu & Olahan", 60, 40, 3000),
    (r"^skm|gold label|mentega|keju", "Susu & Olahan", 30, 60, 2500),
    (r"^beans|biji kopi|powder beans", "Kopi", 30, 250, 250000),
    # resep mencatat 40-60 "Kantung" Jasmine Tea per porsi (kemungkinan ml seduhan), jadi harga per satuan kecil
    (r"jasmine tea", "Teh", 180, 10, 10),
    (r"teh lipton|teh celup|teh bubuk|thai tea|teh bendera", "Teh", 180, 100, 800),
    (r"powder|milo|drip|monin|sirup|madu|gula|sari lemon|saos lava|nuttela|srikaya|biscoff|oreo",
     "Bubuk, Sirup & Pemanis", 90, 100, 1000),
    (r"roti tawar|roti burger|roti hotdog|croissant|sourdough|donut|muffin|garlic bread|bomboloni|brownies|buko"
     r"|cheese cake|mocca|ximilu|roti o", "Roti & Kue", 3, 40, 8000),
    (r"^saos (?!lava)|^saori|^kecap", "Saus & Bumbu", 180, 30, 5000),
    (r"snack|cookies", "Snack Kemasan", 30, 40, 4000),
    (r"pizza|lumpia ayam|mantao|samosa|risol|kebab|burger|churros", "Makanan Beku", 30, 60, 6000),
    (r"leci kaleng", "Buah", 180, 60, 30000),
    (r"lemon kering", "Buah", 60, 60, 1000),
    (r"jeruk|strawberry|alpukat|buah|melon|jambu|pisang", "Buah", 5, 25, 2500),
    (r"indomie", "Bahan Pokok", 180, 15, 3500),
    (r"kwetiau|mie aceh", "Bahan Pokok", 3, 15, 3000),
    (r"beras|tepung|mie telur|bihun|spaghetti|ifuemie|kerupuk|janten", "Bahan Pokok", 180, 15, 3000),
    (r"telur", "Daging, Telur & Seafood", 14, 30, 2500),
    (r"udang kering|teri", "Daging, Telur & Seafood", 60, 120, 5000),
    (r"daging|ayam|cumi|udang|bakso", "Daging, Telur & Seafood", 3, 120, 15000),
    (r"sosis|siomay", "Makanan Beku", 30, 60, 2500),
    (r"tauge|daun mint|sawi hijau|selada|kucai|jamur|tempe", "Sayur & Bumbu Segar", 3, 20, 3000),
    (r"bawang goreng|bawang packing", "Sayur & Bumbu Segar", 60, 40, 10000),
    (r"bawang|bombay|kentang|jahe", "Sayur & Bumbu Segar", 21, 25, 3000),
    (r"wortel|kol|cabe|serai|paprika|timun|sawi|brocoli|tomat|terong|daun pre|parsley|singkong|arcis|acar",
     "Sayur & Bumbu Segar", 5, 20, 3000),
    (r"saos|saori|kecap|minyak|mayonaise|sasa|totole|garam|merica|lada|oregano|bumbu|pasta tomyam|cuka|wijen",
     "Saus & Bumbu", 180, 30, 5000),
    (r"air galon", "Air & Minuman", 365, 1, 20000),
    (r"badak", "Air & Minuman", 365, 6, 6000),
    (r"air mineral|teh botol|fruitea", "Air & Minuman", 365, 6, 3000),
    (r"^air$", "Air & Minuman", 365, 0.05, 1),
    (r"es batu", "Air & Minuman", 1, 1, 1),
    (r"gas", "Lainnya", 3650, 10, 25000),
]
ISI_UMUM = {("galon", "Gram"): 19000.0, ("kg", "Gram"): 1000.0, ("liter", "Gram"): 1000.0, ("papan", "Pcs"): 30.0,
            ("kotak", "Botol"): 24.0}


def _kelompok(nama: str, satuan: str):
    n = nama.lower().strip()
    for pola, kel, tau, h_gram, h_unit in ATURAN:
        if re.search(pola, n):
            return kel, tau, float(h_gram if satuan == "Gram" else h_unit)
    return "Lainnya", 90, (20.0 if satuan == "Gram" else 2000.0)


def baca_ekspor_majoo(path=C.FILE_EKSPOR_BAHAN) -> pd.DataFrame:
    """Baca file ekspor Daftar Bahan Baku majoo (gaya sel file ini rusak untuk openpyxl, jadi pakai calamine)."""
    try:
        ex = pd.read_excel(path, header=3, engine="calamine")
    except Exception:
        ex = pd.read_excel(path, header=3, engine="openpyxl")
    ex = ex[ex.iloc[:, 0].notna() & (ex.iloc[:, 0].astype(str).str.strip() != "")].reset_index(drop=True)
    ex = ex[~ex.iloc[:, 0].astype(str).str.startswith("Powered")]
    cols = ["nama", "monitor", "stokmin", "sat1", "harga1", "sku1"]
    for i in range(2, 6):
        cols += [f"sat{i}", f"konv{i}", f"harga{i}", f"sku{i}"]
    ex = ex.iloc[:, :len(cols)]
    ex.columns = cols[:ex.shape[1]]
    return ex


def satuan_dari_baris(r, sku_dasar: str):
    """Daftar satuan (nama, isi dalam satuan dasar, sku, andal?) dari satu baris ekspor majoo."""
    units = []
    for i in range(1, 6):
        sat, sku = r.get(f"sat{i}"), r.get(f"sku{i}")
        if pd.isna(sat) or pd.isna(sku):
            continue
        konv = 1.0 if i == 1 else float(r.get(f"konv{i}") or 1.0)
        units.append({"no": i, "satuan": str(sat).strip(), "sku": str(sku).strip(), "konv": konv})
    if not units:
        return [], None
    base = next((u for u in units if u["sku"] == sku_dasar), units[0])
    out = []
    for u in units:
        if u is base:
            isi, andal = 1.0, True
        elif base["no"] == 1:
            isi, andal = u["konv"], u["konv"] > 1
        else:
            # satuan dasar bukan satuan #1: konversi majoo tidak bisa pecahan, jadi isi kemasan tidak diketahui
            isi, andal = None, False
        out.append({**u, "isi": isi, "andal": andal})
    return out, base


def susun_master(log=print) -> pd.DataFrame:
    ex = baca_ekspor_majoo()
    dbahan = pd.read_excel(C.FILE_RESEP, sheet_name="Daftar Bahan", header=3, engine="openpyxl")
    dbahan = dbahan[dbahan["Kode SKU"].notna()]
    sku_dasar_dari_nama = {str(n).strip().lower(): (str(s).strip(), str(u).strip())
                           for s, n, u in zip(dbahan["Kode SKU"], dbahan["Nama Bahan"], dbahan["Satuan"])}
    with pd.ExcelFile(C.FILE_STOK_KELUAR, engine="openpyxl") as xl:     # ditutup agar file tidak terkunci di Windows
        long = pd.read_excel(xl, "Stok Keluar (Long)")
        rekap = pd.read_excel(xl, "Rekap Bahan").set_index("SKU Bahan")
        harga_est = estimasi_harga_dari_hpp(xl)
        cs = biaya_kehabisan_dari_resep(xl)
    pakai = long.groupby("SKU Bahan")["Jumlah Keluar"]
    rata_harian = long.groupby("SKU Bahan")["Jumlah Keluar"].mean()

    rows = []
    for _, r in ex.iterrows():
        nama = str(r["nama"]).strip()
        sku_dasar, sat_dasar = sku_dasar_dari_nama.get(nama.lower(), (str(r["sku1"]).strip(), str(r["sat1"]).strip()))
        units, base = satuan_dari_baris(r, sku_dasar)
        sat_dasar = base["satuan"] if base else sat_dasar
        rows.append(_baris(nama, sku_dasar, sat_dasar, units, r, harga_est, cs, rata_harian))
    # bahan yang muncul di resep tetapi tidak ada di Daftar Bahan majoo
    ada = {x["sku"] for x in rows}
    for sku in sorted(set(long["SKU Bahan"]) - ada):
        nm = rekap.loc[sku, "Nama Bahan"] if sku in rekap.index else sku
        sat = rekap.loc[sku, "Satuan"] if sku in rekap.index else "Gram"
        x = _baris(str(nm), sku, str(sat), [{"no": 1, "satuan": str(sat), "sku": sku, "konv": 1.0, "isi": 1.0,
                                             "andal": True}], {"monitor": "T", "stokmin": 0}, harga_est, cs, rata_harian)
        x["catatan"] = "Tidak ada di Daftar Bahan majoo (muncul di resep); tidak dimonitor"
        x["monitor"] = False
        rows.append(x)
    m = pd.DataFrame(rows)
    log(f"Data master: {len(m)} bahan; harga dari HPP: {(m['sumber_harga'] == 'estimasi HPP').sum()}, "
        f"kemasan dari majoo: {(m['sumber_kemasan'] == 'majoo').sum()}")
    return m


def _baris(nama, sku, sat_dasar, units, r, harga_est, cs, rata_harian):
    kel, tau, harga_kel = _kelompok(nama, sat_dasar)
    asumsi = ["masa_simpan", "lead_time"]
    # kemasan pembelian: konversi andal terkecil > 1, lalu isi umum, lalu ukuran sementara dari pemakaian
    cand = [u for u in units if u.get("andal") and u.get("isi") and u["isi"] > 1]
    if cand:
        u = min(cand, key=lambda u: u["isi"])
        kem_nama, kem_isi, sumber_kem = u["satuan"], float(u["isi"]), "majoo"
    else:
        lain = [u for u in units if u["sku"] != sku]
        nm_lain = lain[0]["satuan"] if lain else None
        isi_umum = ISI_UMUM.get(((nm_lain or "").lower(), sat_dasar))
        if isi_umum:
            kem_nama, kem_isi, sumber_kem = nm_lain, isi_umum, "isi umum"
        else:
            kem_isi = ukuran_kemasan_bawaan(float(rata_harian.get(sku, 0.0) or 0.0), sat_dasar, tau)
            kem_nama, sumber_kem = "Kemasan", "asumsi"
            asumsi.append("kemasan")
    h_est = harga_est.get(sku)
    if h_est is not None and harga_kel * 0.25 <= h_est <= harga_kel * 4:
        harga, sumber_harga = float(h_est), "estimasi HPP"
    else:
        harga, sumber_harga = harga_kel, "asumsi kelompok"
    asumsi.append("harga")
    c_s = cs.get(sku)
    sumber_cs = "margin menu"
    if c_s is None or not np.isfinite(c_s) or c_s <= 0:
        c_s, sumber_cs = 2.0 * harga, "2x harga"
    asumsi.append("biaya_kehabisan")
    mon = str(r.get("monitor", "Y")).strip().upper() != "T"
    stokmin = float(r.get("stokmin") or 0) if pd.notna(r.get("stokmin")) else 0.0
    return {
        "sku": sku, "nama": nama, "kategori": kel, "satuan": sat_dasar, "monitor": mon,
        "stok_minimum_majoo": stokmin, "kemasan_nama": kem_nama, "kemasan_isi": float(kem_isi),
        "harga_satuan": round(harga, 4), "harga_kemasan": round(harga * kem_isi, 2), "masa_simpan": int(tau),
        "lead_time": C.LEAD_TIME, "maks_kelipatan": None, "biaya_kehabisan": round(float(c_s), 4),
        "sumber_harga": sumber_harga, "sumber_kemasan": sumber_kem, "sumber_biaya_kehabisan": sumber_cs,
        "asumsi": ",".join(asumsi), "satuan_lain": [u for u in units if u["sku"] != sku], "catatan": "",
    }


def estimasi_harga_dari_hpp(xl: pd.ExcelFile) -> dict:
    """Harga per satuan dasar yang paling konsisten dengan HPP menu (non-negative least squares).

    HPP_menu = sum(qty_bahan_per_porsi * harga_bahan). Hanya estimasi awal; harga asli dari nota tetap diperlukan.
    """
    from scipy.optimize import nnls
    bom = pd.read_excel(xl, "Resep Dipakai")
    r = pd.read_excel(C.FILE_RESEP, sheet_name="Ekspor Resep", header=4, engine="openpyxl")
    r["Nama Produk*"] = r["Nama Produk*"].astype(str).str.strip()
    hpp = r.groupby("Nama Produk*")["HPP*"].first()
    M = bom.pivot_table(index="Produk", columns="SKU Bahan", values="Qty per Porsi", aggfunc="sum").fillna(0)
    y = pd.to_numeric(hpp.reindex(M.index), errors="coerce")
    ok = y.notna() & (y > 0)
    x, _ = nnls(M[ok].values, y[ok].astype(float).values, maxiter=10000)
    return {s: float(v) for s, v in zip(M.columns, x) if v > 0}


def biaya_kehabisan_dari_resep(xl: pd.ExcelFile) -> dict:
    """c_s: margin kontribusi menu yang hilang per satuan bahan (Tabel 5), ditimbang dengan jumlah terjual.

    c_s(b) = sum_p n_p * margin_p / sum_p n_p * qty_{p,b}
    """
    bom = pd.read_excel(xl, "Resep Dipakai")
    jual = pd.read_excel(xl, "Penjualan Menu Harian").groupby("Produk")["Qty Terjual"].sum()
    r = pd.read_excel(C.FILE_RESEP, sheet_name="Ekspor Resep", header=4, engine="openpyxl")
    r["Nama Produk*"] = r["Nama Produk*"].astype(str).str.strip()
    g = r.groupby("Nama Produk*").agg(hpp=("HPP*", "first"), harga=("HARGA JUAL*", "first"))
    margin = (pd.to_numeric(g["harga"], errors="coerce") - pd.to_numeric(g["hpp"], errors="coerce")).clip(lower=0)
    b = bom.groupby(["Produk", "SKU Bahan"])["Qty per Porsi"].sum().reset_index()
    b["n"] = b["Produk"].map(jual).fillna(0)
    b["margin"] = b["Produk"].map(margin)
    b = b[b["margin"].notna() & (b["Qty per Porsi"] > 0)]
    num = (b["n"] * b["margin"]).groupby(b["SKU Bahan"]).sum()
    den = (b["n"] * b["Qty per Porsi"]).groupby(b["SKU Bahan"]).sum()
    return (num / den.replace(0, np.nan)).dropna().to_dict()
