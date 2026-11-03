"""Rincian hasil simulasi K1/K2/K3 dan K1 aktual: dari mana setiap komponen biaya berasal, neraca barang, dan
sisa stok akhir setiap hari (setara hasil stok opname di akhir hari, setelah pemakaian hari itu).

Komponen biaya hari t (Persamaan 31), dijumlah selama periode menjadi total biaya (Persamaan 34):
  biaya simpan     b_h = c_h  x sisa stok akhir hari        c_h = harga x biaya simpan (% per hari)
  biaya kehabisan  b_s = c_s  x pemakaian yang tidak terpenuhi
  biaya terbuang   b_w = harga x jumlah yang melewati masa simpan
  biaya pesan      b_o = c_o  x 1(ada barang datang dari pesanan)
Neraca barang setiap run: stok awal + barang datang = terpakai + terbuang + sisa stok akhir periode.

Rincian harian semua run disimpan di artefak model (simulasi_harian.npz) dan dibaca halaman Simulasi aplikasi.
Laporan Excel memuat rincian per bahan (rata-rata semua run) dan catatan harian satu run contoh.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from ml import simulasi as SIM

BERKAS = "simulasi_harian.npz"
PARAMETER = ("k", "tau", "c_h", "c_s", "c_w", "c_o", "rop1", "q1", "kap", "d_bar", "sigma")
VARIAN_UJI = ("K1", "K2", "K3")
VARIAN_AKTUAL = ("K1A", "K1", "K2", "K3")
NAMA_VARIAN = {"K1A": "K1 aktual", "K1": "K1 statis", "K2": "K2", "K3": "K3"}
AWAL_CONTOH = 1.0       # run contoh: stok awal 1 x rata-rata pemakaian harian (tingkat tengah dari 5)
SEED_CONTOH = 0         # run contoh K3: seed pertama


# ------------------------------------------------------------------------------------------- simpan dan muat
def tanggal_periode(mulai, sampai) -> list:
    return [str(t.date()) for t in pd.date_range(mulai, sampai)]


def simpan(h: dict, folder) -> Path:
    """Simpan rincian harian semua run uji 28 hari (dan K1 aktual bila ada) ke folder artefak."""
    par = h["par_uji"]
    out = {"skus": np.array(h["skus"]), "tanggal": np.array(tanggal_periode(*h["periode_uji"])),
           "d": np.asarray(h["d_test"], float)}
    for p in PARAMETER:
        out[f"par_{p}"] = np.asarray(par[p], float)
    for v, x in h["harian"].items():
        for c, arr in x.items():
            out[f"uji_{v}_{c}"] = arr
    a = h.get("aktual") or {}
    if a.get("status") == "ok" and a.get("harian"):
        pos = {s: i for i, s in enumerate(h["skus"])}
        out["aktual_idx"] = np.array([pos[s] for s in a["skus"]], np.int32)
        out["aktual_tanggal"] = np.array(a["hari"])
        out["aktual_d"] = np.asarray(a["pakai"], float)
        out["aktual_masuk"] = np.asarray(a["q"], float)
        out["aktual_stok_taksiran"] = np.asarray(a["stok_awal"], float)
        for v, x in a["harian"].items():
            for c, arr in x.items():
                out[f"aktual_{v}_{c}"] = arr
    f = Path(folder) / BERKAS
    np.savez_compressed(f, **out)
    return f


def _runs(z, awalan: str, varian) -> dict:
    out = {}
    for key in z.files:
        if not key.startswith(awalan):
            continue
        sisa = key[len(awalan):]
        v, _, c = sisa.partition("_")
        if v in varian and c:
            out.setdefault(v, {})[c] = z[key]
    return out


def muat(folder) -> dict | None:
    """{"uji": bagian, "aktual": bagian atau None}; bagian = skus, tanggal, d [bahan, hari], par, runs."""
    f = Path(folder) / BERKAS
    if not f.exists():
        return None
    with np.load(f, allow_pickle=False) as z:
        skus = z["skus"].tolist()
        par = {p: z[f"par_{p}"] for p in PARAMETER if f"par_{p}" in z.files}
        uji = {"skus": skus, "tanggal": z["tanggal"].tolist(), "d": z["d"], "par": par,
               "runs": _runs(z, "uji_", VARIAN_UJI)}
        aktual = None
        if "aktual_idx" in z.files:
            idx = z["aktual_idx"].astype(int)
            aktual = {"skus": [skus[i] for i in idx], "tanggal": z["aktual_tanggal"].tolist(), "d": z["aktual_d"],
                      "masuk": z["aktual_masuk"], "stok_taksiran": z["aktual_stok_taksiran"],
                      "par": {p: v[idx] for p, v in par.items()}, "runs": _runs(z, "aktual_", VARIAN_AKTUAL)}
    return {"uji": uji, "aktual": aktual}


# ------------------------------------------------------------------------------------------- satu run
def pilihan_run(bagian: dict, v: str) -> dict:
    """Tingkat stok awal dan seed yang tersedia untuk varian v."""
    x = bagian["runs"].get(v)
    if x is None:
        return {"awal": [], "seed": []}
    return {"awal": sorted({float(a) for a in x["stok_awal"]}), "seed": sorted({int(s) for s in x["seed"] if s >= 0})}


def indeks_run(bagian: dict, v: str, b: int, awal: float, seed: int = 0) -> int | None:
    x = bagian["runs"].get(v)
    if x is None:
        return None
    m = (x["b"] == b) & np.isclose(x["stok_awal"], awal)
    if v == "K3":
        m &= x["seed"] == seed
    j = np.flatnonzero(m)
    return int(j[0]) if len(j) else None


def harian_run(bagian: dict, v: str, b: int, awal: float, seed: int = 0) -> pd.DataFrame | None:
    """Catatan harian satu run: stok sebelum hari itu, ROP, barang datang, terbuang, pemakaian, kekurangan, sisa stok
    akhir hari, dan biaya per komponen. Setiap baris memenuhi
    stok sebelum - terbuang + datang - terpenuhi = sisa akhir."""
    j = indeks_run(bagian, v, b, awal, seed)
    if j is None:
        return None
    x = bagian["runs"][v]
    q, W, S, I = (np.asarray(x[c][j], float) for c in ("q", "W", "S", "I"))
    d = np.asarray(bagian["d"][b], float)
    p = {k: float(val[b]) for k, val in bagian["par"].items()}
    df = pd.DataFrame({
        "tanggal": bagian["tanggal"],
        "stok_sebelum": np.concatenate([[float(x["jumlah_awal"][j])], I[:-1]]),
        "rop": np.asarray(x["rop"][j], float),
        "datang": q, "terbuang": W, "pemakaian": d, "terpenuhi": d - S, "kurang": S, "sisa_akhir": I,
        "b_h": p["c_h"] * I, "b_s": p["c_s"] * S, "b_w": p["c_w"] * W, "b_o": p["c_o"] * (q > 0),
        "cadangan": np.asarray(x["cad"][j]) > 0,
    })
    df["biaya"] = df[["b_h", "b_s", "b_w", "b_o"]].sum(axis=1)
    if "masuk" in bagian:
        df.insert(4, "masuk_tercatat", np.asarray(bagian["masuk"][b], float))
    return df


def ringkas_run(df: pd.DataFrame) -> dict:
    """Total satu run dari catatan hariannya."""
    pakai = float(df["pemakaian"].sum())
    return {"stok_awal": float(df["stok_sebelum"].iloc[0]), "datang": float(df["datang"].sum()),
            "terbuang": float(df["terbuang"].sum()), "pemakaian": pakai, "terpenuhi": float(df["terpenuhi"].sum()),
            "kurang": float(df["kurang"].sum()), "sisa_akhir": float(df["sisa_akhir"].iloc[-1]),
            "stok_harian": float(df["sisa_akhir"].sum()), "pesan": int((df["datang"] > 0).sum()),
            "hari_habis": int((df["kurang"] > 1e-9).sum()),
            "FR": 1 - float(df["kurang"].sum()) / pakai if pakai > 0 else 1.0,
            **{c: float(df[c].sum()) for c in ("b_h", "b_s", "b_w", "b_o", "biaya")}}


# ------------------------------------------------------------------------------------------- laporan Excel
KETERANGAN = [
    ("Biaya simpan (b_h)", "c_h x sisa stok akhir hari, dijumlah selama periode. c_h = harga x biaya simpan per hari."),
    ("Biaya kehabisan (b_s)", "c_s x pemakaian yang tidak terpenuhi karena stok habis (penjualan hilang)."),
    ("Biaya terbuang (b_w)", "harga x jumlah bahan yang dibuang karena melewati masa simpan."),
    ("Biaya pesan (b_o)", "c_o x jumlah hari ada barang datang dari pesanan (satu pesanan per bahan per hari)."),
    ("Total biaya (TC)", "b_h + b_s + b_w + b_o (Persamaan 34). Harga pembelian barang tidak termasuk TC."),
    ("Urutan kejadian satu hari", "pagi: bahan yang melewati masa simpan dibuang, lalu barang pesanan kemarin datang; "
                                 "siang: bahan dipakai FIFO (batch tertua dulu); akhir hari: sisa stok dihitung, lalu "
                                 "kebijakan memutuskan pesanan untuk besok."),
    ("Stok sebelum", "sisa stok akhir hari sebelumnya; hari pertama = stok awal simulasi."),
    ("ROP", "titik pesan ulang yang dipakai saat memutuskan pesanan yang datang hari itu (K1 statis: tetap; K2 dan K3: "
            "dari prediksi XGBoost). K1 aktual tidak memakai ROP."),
    ("Sisa stok akhir hari", "stok yang tersisa setelah pemakaian hari itu, setara hasil stok opname di akhir hari."),
    ("Neraca barang", "stok awal + barang datang = terpakai + terbuang + sisa stok akhir periode (selisih = 0)."),
    ("Nilai (Rp)", "jumlah x harga per satuan dasar."),
    ("Rata-rata semua run", "uji 28 hari: 5 tingkat stok awal (0; 0,5; 1; 2; 3 x rata-rata pemakaian harian), K3 juga 5 "
                            "seed. K1 aktual: taksiran stok awal aktual (K3: 5 seed)."),
    ("Run contoh harian", "uji 28 hari: stok awal 1 x rata-rata pemakaian harian, K3 seed pertama. K1 aktual: taksiran "
                          "stok awal aktual, K3 seed pertama. Total run contoh sama dengan baris run itu di lembar Semua Run."),
]

KOLOM_HARIAN_EXCEL = {
    "tanggal": "Tanggal", "stok_sebelum": "Stok sebelum (sisa kemarin)", "rop": "ROP",
    "masuk_tercatat": "Barang masuk tercatat", "datang": "Barang datang (dipesan kemarin)",
    "terbuang": "Terbuang (lewat masa simpan)", "pemakaian": "Pemakaian", "terpenuhi": "Terpenuhi",
    "kurang": "Kekurangan", "sisa_akhir": "Sisa stok akhir hari (stok opname)", "b_h": "Biaya simpan",
    "b_s": "Biaya kehabisan", "b_w": "Biaya terbuang", "b_o": "Biaya pesan", "biaya": "Total biaya hari ini",
    "cadangan": "K3 memakai aturan cadangan",
}


def _baris_kelompok(total: dict, kelompok: str, n_bahan: int, periode: str) -> list:
    rows = []
    for v in VARIAN_AKTUAL:
        d = total.get(v)
        if not d:
            continue
        tc = d["TC_mean"]
        r = {"Periode": periode, "Kelompok bahan": f"{kelompok} ({n_bahan})", "Kebijakan": NAMA_VARIAN[v]}
        for c, label in (("b_h", "Biaya simpan"), ("b_s", "Biaya kehabisan"), ("b_w", "Biaya terbuang"),
                         ("b_o", "Biaya pesan")):
            r[f"{label} (Rp)"] = d[f"{c}_mean"]
            r[f"{label} (% TC)"] = d[f"{c}_mean"] / tc if tc else None
        r["Total biaya TC (Rp)"] = tc
        r["Jumlah pemesanan"] = d["jumlah_pesan_mean"]
        r["Hari kehabisan (bahan-hari)"] = d["hari_stockout_mean"]
        if "nilai_awal_mean" in d:
            r["Nilai stok awal (Rp)"] = d["nilai_awal_mean"]
            r["Nilai barang datang (Rp)"] = d["nilai_diterima_mean"]
            r["Nilai terpakai (Rp)"] = d["nilai_terpakai_mean"]
            r["Nilai terbuang (Rp)"] = d["terbuang_nilai_mean"]
            r["Nilai sisa stok akhir (Rp)"] = d["nilai_sisa_mean"]
            r["Cek neraca (Rp, harus 0)"] = (d["nilai_awal_mean"] + d["nilai_diterima_mean"] - d["nilai_terpakai_mean"]
                                             - d["terbuang_nilai_mean"] - d["nilai_sisa_mean"])
        rows.append(r)
    return rows


def tabel_per_bahan(runs: pd.DataFrame, par: dict, skus: list, info: pd.DataFrame, utama: set, varian) -> pd.DataFrame:
    """Rata-rata semua run per bahan dan kebijakan, dengan dasar perhitungan setiap komponen biaya."""
    pos = {s: i for i, s in enumerate(skus)}
    g = runs.groupby(["sku", "varian"])[SIM.METRIK].mean().reset_index()
    rows = []
    for s in skus:
        i = pos[s]
        for v in varian:
            r = g[(g["sku"] == s) & (g["varian"] == v)]
            if not len(r):
                continue
            r = r.iloc[0]
            rows.append({
                "SKU": s, "Nama": info["nama"].get(s, s), "Satuan": info["satuan"].get(s, ""),
                "Bahan utama": "ya" if s in utama else "tidak", "Kebijakan": NAMA_VARIAN[v],
                "Harga per satuan (Rp)": par["c_w"][i], "c_h: biaya simpan per satuan per hari (Rp)": par["c_h"][i],
                "c_s: biaya kehabisan per satuan (Rp)": par["c_s"][i], "c_o: biaya pesan (Rp)": par["c_o"][i],
                "Masa simpan (hari)": par["tau"][i], "Isi kemasan": par["k"][i],
                "Stok awal": r["jumlah_awal"], "Barang datang": r["total_diterima"], "Pemakaian": r["total_pakai"],
                "Terpenuhi": r["total_pakai"] - r["total_kurang"], "Kekurangan": r["total_kurang"],
                "Terbuang": r["terbuang"], "Sisa stok akhir periode": r["sisa_akhir"],
                "Jumlah sisa stok akhir harian": r["stok_harian"], "Jumlah pemesanan": r["jumlah_pesan"],
                "Hari kehabisan": r["hari_stockout"], "Fill rate": r["FR"], "Rasio terbuang": r["WR"],
                "Biaya simpan = c_h x jumlah sisa harian (Rp)": r["b_h"],
                "Biaya kehabisan = c_s x kekurangan (Rp)": r["b_s"],
                "Biaya terbuang = harga x terbuang (Rp)": r["b_w"],
                "Biaya pesan = c_o x jumlah pemesanan (Rp)": r["b_o"], "Total biaya TC (Rp)": r["TC"],
                "Nilai barang datang (Rp)": r["nilai_diterima"], "Nilai sisa stok akhir (Rp)": r["nilai_sisa"],
            })
    return pd.DataFrame(rows)


def tabel_harian_contoh(bagian: dict, info: pd.DataFrame, varian, awal: float, seed: int = SEED_CONTOH) -> pd.DataFrame:
    """Catatan harian run contoh untuk semua bahan dan kebijakan (format panjang)."""
    out = []
    for v in varian:
        for b, s in enumerate(bagian["skus"]):
            df = harian_run(bagian, v, b, awal, seed)
            if df is None:
                continue
            df.insert(0, "Hari ke-", np.arange(1, len(df) + 1))
            df.insert(0, "Satuan", info["satuan"].get(s, ""))
            df.insert(0, "Nama", info["nama"].get(s, s))
            df.insert(0, "SKU", s)
            df.insert(0, "Kebijakan", NAMA_VARIAN[v])
            if v != "K3":
                df["cadangan"] = None
            else:
                df["cadangan"] = np.where(df["cadangan"], "ya", "")
            if v == "K1A":
                df["rop"] = None
            out.append(df)
    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True).rename(columns=KOLOM_HARIAN_EXCEL)


def tabel_sisa_harian(bagian: dict, info: pd.DataFrame, varian, awal: float, seed: int = SEED_CONTOH) -> pd.DataFrame:
    """Sisa stok akhir setiap hari (stok opname simulasi) run contoh: satu baris per bahan dan kebijakan."""
    rows = []
    label = [pd.Timestamp(t).strftime("%d/%m") for t in bagian["tanggal"]]
    for b, s in enumerate(bagian["skus"]):
        for v in varian:
            df = harian_run(bagian, v, b, awal, seed)
            if df is None:
                continue
            r = {"SKU": s, "Nama": info["nama"].get(s, s), "Satuan": info["satuan"].get(s, ""),
                 "Kebijakan": NAMA_VARIAN[v], "Stok awal": df["stok_sebelum"].iloc[0]}
            r.update(dict(zip(label, df["sisa_akhir"].values)))
            r["Nilai sisa akhir (Rp)"] = float(df["sisa_akhir"].iloc[-1]) * float(bagian["par"]["c_w"][b])
            rows.append(r)
    return pd.DataFrame(rows)


def _tulis(w, df: pd.DataFrame, nama: str, beku_kolom: int = 0, lebar_min: float = 12, lebar: dict = None):
    """Tulis satu lembar, bekukan baris judul (dan beberapa kolom pertama), dan atur lebar kolom dari judulnya.
    Berlaku untuk mesin Excel openpyxl maupun xlsxwriter."""
    df.to_excel(w, sheet_name=nama, index=False)
    ws = w.sheets[nama]
    lebar = lebar or {}
    ukuran = [lebar.get(c, max(lebar_min, min(40.0, 0.9 * len(str(c))))) for c in df.columns]
    if w.engine == "xlsxwriter":
        ws.freeze_panes(1, beku_kolom)
        for i, u in enumerate(ukuran):
            ws.set_column(i, i, u)
    else:
        from openpyxl.utils import get_column_letter
        ws.freeze_panes = f"{get_column_letter(beku_kolom + 1)}2"
        for i, u in enumerate(ukuran, start=1):
            ws.column_dimensions[get_column_letter(i)].width = u


def tulis_lembar(w, h: dict, ev: dict, info: pd.DataFrame):
    """Lembar rincian pada laporan simulasi."""
    utama = set(ev.get("bahan_utama", []))
    _tulis(w, pd.DataFrame(KETERANGAN, columns=["Istilah", "Arti"]), "Cara Membaca Rincian",
           lebar={"Istilah": 30, "Arti": 120})

    periode = " s.d. ".join(h["periode_uji"])
    rows = []
    for label, nama in (("utama", "Bahan utama"), ("semua", "Semua bahan")):
        kb = ev["kebijakan"][label]
        rows += _baris_kelompok(kb["total"], nama, kb["n_bahan"], f"Uji 28 hari ({periode})")
    ra = ev.get("aktual") or {}
    if ra.get("status") == "ok":
        p_a = " s.d. ".join(ra["periode"])
        for label, nama in (("utama", "Bahan utama"), ("semua", "Semua bahan")):
            kb = ra["kebijakan"][label]
            if kb["n_bahan"]:
                rows += _baris_kelompok(kb["total"], nama, kb["n_bahan"], f"K1 aktual ({p_a}), taksiran stok awal")
    _tulis(w, pd.DataFrame(rows), "Rincian Biaya", beku_kolom=3)

    par = h["par_uji"]
    _tulis(w, tabel_per_bahan(h["runs"], par, h["skus"], info, utama, VARIAN_UJI), "Rincian Per Bahan",
           beku_kolom=5, lebar={"Nama": 28})

    bag = {"skus": h["skus"], "tanggal": tanggal_periode(*h["periode_uji"]), "d": h["d_test"],
           "par": {p: np.asarray(par[p], float) for p in PARAMETER}, "runs": h["harian"]}
    _tulis(w, tabel_harian_contoh(bag, info, VARIAN_UJI, AWAL_CONTOH), "Harian Uji", beku_kolom=6,
           lebar={"Nama": 28})
    _tulis(w, tabel_sisa_harian(bag, info, VARIAN_UJI, AWAL_CONTOH), "Sisa Stok Harian", beku_kolom=4,
           lebar_min=8, lebar={"Nama": 28, "Nilai sisa akhir (Rp)": 18})

    a = h.get("aktual") or {}
    if a.get("status") == "ok" and a.get("harian"):
        idx = [h["skus"].index(s) for s in a["skus"]]
        bag_a = {"skus": a["skus"], "tanggal": a["hari"], "d": a["pakai"], "masuk": a["q"],
                 "stok_taksiran": a["stok_awal"], "par": {p: np.asarray(par[p], float)[idx] for p in PARAMETER},
                 "runs": a["harian"]}
        runs_a = a["runs"][a["runs"]["stok_awal"] == SIM.STOK_AWAL_TAKSIRAN]
        _tulis(w, tabel_per_bahan(runs_a, bag_a["par"], a["skus"], info, utama, VARIAN_AKTUAL), "Rincian K1 Aktual",
               beku_kolom=5, lebar={"Nama": 28})
        _tulis(w, tabel_harian_contoh(bag_a, info, VARIAN_AKTUAL, SIM.STOK_AWAL_TAKSIRAN), "Harian K1 Aktual",
               beku_kolom=6, lebar={"Nama": 28})
