"""Praproses cakupan bahan: saringan bahan kosong / banyak nilai 0 dan pemilihan bahan target."""
import numpy as np
import pandas as pd

import config as C


def _data():
    hari = pd.date_range("2026-07-01", periods=100)
    pola = {
        "A": np.full(100, 10.0),                                   # tiap hari, cepat rusak, nilai besar
        "B": np.where(np.arange(100) % 10 < 7, 5.0, 0.0),          # nilai 0 pada 30% hari
        "C": np.zeros(100),                                        # kosong
        "D": np.full(100, 50.0),                                   # tiap hari, tetapi tahan lama
        "E": np.where(np.arange(100) % 10 < 9, 4.0, 0.0),          # nilai 0 pada 10% hari, cepat rusak, nilai kecil
        "F": np.full(100, 3.0),                                    # tiap hari, cepat rusak, kelompok Air & Minuman
    }
    wide = pd.DataFrame(pola, index=hari)
    master = pd.DataFrame({
        "sku": list(pola), "nama": [f"Bahan {s}" for s in pola],
        "kategori": ["Kopi", "Buah", "Buah", "Bahan Pokok", "Buah", "Air & Minuman"], "satuan": "Gram",
        "masa_simpan": [7, 3, 3, 180, 5, 7], "harga_satuan": [100.0, 10.0, 10.0, 10.0, 1.0, 10.0],
        "sumber_harga": "estimasi HPP",
    })
    return wide, master


def test_saringan_nilai_nol_dan_peringkat_bahan_target():
    from ml import praproses as PR
    wide, master = _data()
    p = PR.pilih_target(PR.saring(PR.profil_bahan(wide, master, wide.index[69], wide.index[-1])), n=2, tetap=[])
    assert p["lolos"].to_dict() == {"A": True, "B": False, "C": False, "D": True, "E": True, "F": True}
    assert p.loc["C", "alasan"].startswith("kosong") and p.loc["B", "alasan"].startswith("banyak nilai 0")
    assert round(p.loc["B", "adi"], 2) == 1.43 and round(p.loc["E", "adi"], 2) == 1.11       # batas ADI 1,32
    # layak = lolos, cepat rusak, bukan Air & Minuman; D tahan lama dan F minuman tidak layak
    assert p["layak"].to_dict() == {"A": True, "B": False, "C": False, "D": False, "E": True, "F": False}
    assert p.loc["A", "peringkat"] == 1 and p.loc["E", "peringkat"] == 2
    assert list(p.index[p["target"]]) == ["A", "E"]
    # daftar yang dikunci mengalahkan peringkat, tetapi bahan yang tidak lolos saringan tetap tidak dipakai
    q = PR.pilih_target(PR.saring(PR.profil_bahan(wide, master, wide.index[69], wide.index[-1])), n=2, tetap=["E", "B"])
    assert list(q.index[q["target"]]) == ["E"] and list(q.index[q["target_otomatis"]]) == ["A", "E"]
    r = PR.ringkas(PR.susun_pemilihan(wide, master, wide.index[69], wide.index[-1]).assign(dimodelkan=q["target"]),
                   wide.index[-1])
    assert (r["n_data"], r["n_kosong"], r["n_banyak_nol"], r["n_lolos"]) == (6, 1, 1, 4)


def test_model_bawaan_memakai_bahan_target(admin, db):
    """Model bawaan dilatih hanya untuk bahan target; halaman menjelaskan dasar pemilihannya."""
    from app.layanan import model_aktif as MA
    model = MA.ambil(db)
    ev = model.evaluasi()
    pm = ev["pemilihan"]
    assert sorted(pm["target"]) == sorted(C.BAHAN_TARGET) and len(pm["target"]) == C.JUMLAH_BAHAN_TARGET
    assert sorted(model.items) == sorted(C.BAHAN_TARGET) and sorted(model.q) == sorted(C.BAHAN_TARGET)
    assert pm["n_data"] == pm["n_kosong"] + pm["n_banyak_nol"] + pm["n_lolos"]
    assert not pm["beda_dari_otomatis"]                    # daftar yang dikunci = peringkat otomatis data ini
    for r in pm["tabel"]:
        if r["target"]:
            assert r["lolos"] and r["masa_simpan"] <= C.MASA_SIMPAN_MAKS_TARGET and r["adi"] <= C.ADI_MAKS
    assert ev["kebijakan"]["utama"]["n_bahan"] == ev["kebijakan"]["semua"]["n_bahan"] == C.JUMLAH_BAHAN_TARGET
    r = admin.get("/evaluasi")
    assert r.status_code == 200 and 'id="pemilihan"' in r.text and "Syntetos" in r.text
    r = admin.get("/simulasi")
    assert r.status_code == 200 and f"{C.JUMLAH_BAHAN_TARGET} bahan target" in r.text
    r = admin.get("/rekomendasi")
    assert r.status_code == 200 and "di luar bahan target" in r.text
    r = admin.get("/laporan/1/evaluasi")
    from io import BytesIO
    xl = pd.ExcelFile(BytesIO(r.content), engine="openpyxl")
    assert {"Aturan Pemilihan", "Pemilihan Bahan"} <= set(xl.sheet_names)
    t = xl.parse("Pemilihan Bahan")
    assert int((t["Bahan target"] == "ya").sum()) == C.JUMLAH_BAHAN_TARGET
