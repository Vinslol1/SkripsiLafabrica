"""Rincian hasil simulasi pada model bawaan: catatan harian setiap run cocok dengan laporan, dan halaman rincian
per bahan menampilkan asal biaya, neraca barang, serta sisa stok setiap hari."""
import pandas as pd
import pytest


def _model(db):
    from app.layanan import model_aktif as MA
    return MA.ambil(db)


def test_catatan_harian_model_bawaan_cocok_dengan_semua_run(aplikasi, db):
    from pathlib import Path

    from ml import rincian as RC
    m = _model(db)
    R = RC.muat(m.folder)
    assert R is not None, "artefak model bawaan belum memuat simulasi_harian.npz"
    runs = pd.read_excel(Path(m.folder) / "simulasi_K1_K2_K3.xlsx", sheet_name="Semua Run", engine="calamine")
    u = R["uji"]
    for sku in u["skus"][:: max(1, len(u["skus"]) // 6)]:
        b = u["skus"].index(sku)
        for v in RC.VARIAN_UJI:
            for awal in RC.pilihan_run(u, v)["awal"]:
                t = RC.ringkas_run(RC.harian_run(u, v, b, awal, 0))
                r = runs[(runs["sku"] == sku) & (runs["varian"] == v) & (runs["stok_awal"] == awal)
                         & (runs["seed"] == (0 if v == "K3" else -1))].iloc[0]
                assert t["biaya"] == pytest.approx(r["TC"], rel=1e-5, abs=0.05), (sku, v, awal)
                assert t["sisa_akhir"] == pytest.approx(r["sisa_akhir"], rel=1e-5, abs=1e-3)
    ev = m.evaluasi()
    for kel in ("utama", "semua"):
        for v, d in ev["kebijakan"][kel]["total"].items():   # neraca nilai barang seimbang di tingkat kelompok
            assert d["nilai_awal_mean"] + d["nilai_diterima_mean"] == pytest.approx(
                d["nilai_terpakai_mean"] + d["terbuang_nilai_mean"] + d["nilai_sisa_mean"], rel=1e-9)
            assert d["TC_mean"] == pytest.approx(d["b_h_mean"] + d["b_s_mean"] + d["b_w_mean"] + d["b_o_mean"])


def test_halaman_rincian_per_bahan(admin, db):
    ev = _model(db).evaluasi()
    sku = ev["bahan_utama"][0]
    r = admin.get(f"/simulasi/bahan/{sku}")
    assert r.status_code == 200
    for teks in ("Asal biaya", "Neraca barang", "Catatan harian", "Sisa akhir", "stok opname"):
        assert teks in r.text, teks
    assert admin.get(f"/simulasi/bahan/{sku}?awal=0&seed=2&tampil=K1").status_code == 200
    assert admin.get(f"/simulasi/bahan/{sku}?awal=abc&seed=nan&tampil=X").status_code == 200   # nilai salah: bawaan
    ak = [x["sku"] for x in (ev.get("aktual") or {}).get("per_bahan", [])]
    if ak:
        r = admin.get(f"/simulasi/bahan/{ak[0]}?tampil_aktual=K3&awal_aktual=1")
        assert r.status_code == 200 and "Masuk tercatat" in r.text
    assert admin.get("/simulasi/bahan/TIDAK-ADA", follow_redirects=False).status_code == 303
    r = admin.get("/simulasi")
    assert "Asal biaya dan sisa stok" in r.text and f"/simulasi/bahan/{sku}" in r.text
    xl = admin.get(f"/laporan/{_model(db).run_id}/simulasi")
    lembar = pd.ExcelFile(__import__("io").BytesIO(xl.content), engine="calamine").sheet_names
    for nama in ("Cara Membaca Rincian", "Rincian Biaya", "Rincian Per Bahan", "Harian Uji", "Sisa Stok Harian"):
        assert nama in lembar, nama
