"""Uji satuan rumus persediaan (Persamaan 1-3, 20-28), lingkungan FIFO, dan agen Q-Learning."""
import math

import numpy as np
import pytest

from ml import simulasi as SIM
from ml.kebijakan import (eoq, indeks_bin, indeks_state, jumlah_state, q_klasik, q_order_up_to, rop_dinamis,
                          rop_statis, stok_target, ukuran_kemasan_bawaan)
from ml.lingkungan import Lingkungan
from ml.qlearning import KumpulanAgen, jadwal_epsilon


def test_rop_statis_dan_eoq():
    assert rop_statis(10, 2, L=1, Z=1.65) == pytest.approx(13.3)
    assert eoq(10, 2000, 0.4) == pytest.approx(math.sqrt(2 * 10 * 2000 / 0.4))
    assert eoq(0, 2000, 0.4) == 0


def test_q_klasik_dibatasi_masa_simpan_dan_kemasan():
    # EOQ = 1000 tetapi pemakaian selama masa simpan hanya 30 -> 30, dibulatkan ke atas ke kemasan 25 -> 50
    assert q_klasik(10, 2000, 0.04, 3, 25) == 50
    # paling sedikit satu kemasan
    assert q_klasik(0.1, 2000, 0.04, 1, 100) == 100


def test_rop_dinamis_dan_stok_target():
    yh = [10, 12, 11]
    assert rop_dinamis(yh, 2, L=1, Z=1.65) == pytest.approx(10 + 1.65 * 2)
    assert stok_target(yh, 2, L=1, Z=1.65) == pytest.approx(22 + 1.65 * 2 * math.sqrt(2))


def test_order_up_to():
    assert q_order_up_to(ip=20, rop=13.3, out=26.7, k=5) == 0          # di atas ROP: tidak pesan
    assert q_order_up_to(ip=10, rop=13.3, out=26.7, k=5) == 20         # ceil(16,7 / 5) x 5
    assert q_order_up_to(ip=13.3, rop=13.3, out=26.7, k=1) == 14       # tepat di ROP tetap memesan


def test_indeks_state_dalam_rentang():
    ed = {"ip": [1e-9, 5, 10, 20], "d": [3, 6], "e": [1e-9, 2]}
    n = jumlah_state()
    for ip in (-5, 0, 7, 100):
        for d in (0, 4, 50):
            for e in (0, 1, 9):
                for f in (0, 1):
                    assert 0 <= indeks_state(ip, d, e, f, ed) < n
    assert [indeks_bin(x, ed["ip"]) for x in (0, 7, 100)] == [0, 2, 4]
    assert indeks_state(7, 4, 0, 1, ed) == indeks_state(7, 4, 0, 0, ed) + 1


def test_ukuran_kemasan_bawaan():
    assert ukuran_kemasan_bawaan(240, "Gram", 3) == 200      # cepat rusak: tidak melebihi pemakaian sehari
    assert ukuran_kemasan_bawaan(20, "Gram", 180) == 250     # tahan lama: tidak melebihi pemakaian 14 hari
    assert ukuran_kemasan_bawaan(1, "Gram", 180) == 100      # tahan lama bersatuan gram: minimal 100 g
    assert ukuran_kemasan_bawaan(3, "Pcs", 3) == 2


def test_lingkungan_kedaluwarsa_kehabisan_dan_biaya():
    env = Lingkungan(tau=[2], c_h=[1.0], c_s=[10.0], c_w=[3.0], c_o=[100.0])
    env.reset([10])                       # 10 unit di tangan pada akhir hari ini (umur 0)
    h = env.langkah([0], [3])             # besok: pakai 3
    assert (h["W"][0], h["S"][0], h["I"][0]) == (0, 0, 7)
    assert h["biaya"][0] == pytest.approx(7 * 1.0)
    h = env.langkah([5], [2])             # lusa: sisa 7 melewati masa simpan dan dibuang, pesanan 5 tiba, pakai 2
    assert (h["W"][0], h["I"][0]) == (7, 3)
    assert h["biaya"][0] == pytest.approx(3 * 1.0 + 7 * 3.0 + 100.0)
    h = env.langkah([0], [5])             # pemakaian 5, stok 3: kurang 2
    assert (h["S"][0], h["I"][0]) == (2, 0)
    assert h["biaya"][0] == pytest.approx(2 * 10.0)


def test_lingkungan_fifo_dan_hampir_kedaluwarsa():
    env = Lingkungan(tau=[5], c_h=[0], c_s=[0], c_w=[1], c_o=[0])
    env.reset([4])
    env.langkah([6], [5])                 # batch lama (4) habis dulu, lalu 1 dari batch baru
    assert env.stok[0, 0] == 5 and env.stok[0, 1:].sum() == 0
    env = Lingkungan(tau=[3], c_h=[0], c_s=[0], c_w=[1], c_o=[0])
    env.reset([10])
    env.langkah([0], [0])
    assert env.hampir_kedaluwarsa()[0] == 0
    env.langkah([0], [0])
    assert env.hampir_kedaluwarsa()[0] == 10   # dibuang besok pagi
    assert env.langkah([0], [0])["W"][0] == 10


def test_pembaruan_q_persamaan_17():
    ag = KumpulanAgen(k=[5], m=[2])
    ag.Q[0, 3, :] = [-1.0, -2.0, -4.0]
    ag.perbarui(np.array([1]), np.array([2]), np.array([-10.0]), np.array([3]), alpha=0.1, gamma=0.9)
    # Q(1, 2) = 0 + 0,1 x (-10 + 0,9 x max(-1, -2, -4) - 0) = -1,09
    assert ag.Q[0, 1, 2] == pytest.approx(-1.09)
    assert ag.N[0, 1, 2] == 1


def test_kapasitas_simpan_membatasi_aksi():
    ag = KumpulanAgen(k=[10], m=[5], kap=[30])
    assert ag.layak(np.array([12.0]))[0].tolist() == [True, True, False, False, False, False]
    assert ag.layak(np.array([45.0]))[0].tolist() == [True, False, False, False, False, False]
    ag.Q[0, 0] = [-5, -4, -3, -1, -1, -1]
    ag.N[0, 0] = 1
    assert ag.greedy(np.array([0]), ip=np.array([12.0]))[0] == 1     # aksi 3..5 lebih murah tetapi tidak muat
    assert ag.greedy(np.array([0]))[0] == 3                           # tanpa batas kapasitas
    assert ag.greedy(np.array([7]))[0] == -1                          # state belum pernah ditemui -> cadangan K2


def test_jadwal_epsilon():
    assert jadwal_epsilon(0, 5000) == pytest.approx(1.0)
    assert jadwal_epsilon(4000, 5000) == pytest.approx(0.01)
    assert jadwal_epsilon(4999, 5000) == pytest.approx(0.01)
    assert 0.01 < jadwal_epsilon(2000, 5000) < 1.0


def _par(**ubah):
    par = {"k": np.array([10.0]), "tau": np.array([5.0]), "c_h": np.array([0.1]), "c_s": np.array([5.0]),
           "c_w": np.array([1.0]), "c_o": np.array([2.0]), "rop1": np.array([15.0]), "q1": np.array([100.0])}
    par.update({k: np.array([v], float) for k, v in ubah.items()})
    return par


def test_simulasi_k2_dengan_prediksi_sempurna_tanpa_kehabisan():
    d = np.full((1, 14), 10.0)
    res = SIM.jalankan("K2", _par(), d, d, d, np.zeros(1), np.array([0.0]))
    assert res["FR"][0] == pytest.approx(1.0)
    assert res["hari_stockout"][0] == 0
    assert res["TC"][0] == pytest.approx(res["b_h"][0] + res["b_s"][0] + res["b_w"][0] + res["b_o"][0])


def test_simulasi_menghormati_kapasitas_simpan():
    d = np.full((1, 10), 10.0)
    res = SIM.jalankan("K1", _par(kap=40), d, d, d, np.zeros(1), np.array([0.0]), catat_harian=True)
    assert max(h["q"][0] for h in res["harian"]) <= 40           # Q tetap K1 = 100 dipangkas ke kapasitas
    res = SIM.jalankan("K1", _par(), d, d, d, np.zeros(1), np.array([0.0]), catat_harian=True)
    assert max(h["q"][0] for h in res["harian"]) == 100


def _par_k1a(n, kap=np.inf):
    return {"k": np.ones(n), "tau": np.full(n, 5.0), "c_h": np.ones(n), "c_s": np.full(n, 10.0),
            "c_w": np.full(n, 5.0), "c_o": np.full(n, 100.0), "rop1": np.zeros(n), "q1": np.zeros(n),
            "kap": np.full(n, kap)}


def test_k1_aktual_memutar_ulang_barang_masuk_tanpa_batas_kapasitas():
    par = _par_k1a(2, kap=1.0)
    par["q_aktual"] = np.array([[10.0, 0, 0, 5], [0, 0, 0, 0]])
    d = np.array([[3.0, 3, 3, 3], [1, 1, 1, 1]])
    r = SIM.jalankan("K1A", par, d, d, d, np.zeros(2), np.array([0.0, 2.0]))
    assert r["total_diterima"].tolist() == [15, 0]          # kapasitas 1 tidak memotong barang yang benar-benar datang
    assert r["jumlah_pesan"].tolist() == [2, 0]
    assert r["total_kurang"].tolist() == [0, 2]             # bahan kedua: stok awal 2 habis pada hari ketiga
    assert r["TC"][0] == pytest.approx(7 + 4 + 1 + 3 + 2 * 100)


def test_taksiran_stok_awal_aktual():
    d = np.array([[3.0, 3, 3, 3], [5, 5, 0, 0]])
    q = np.array([[10.0, 0, 0, 5], [0, 3, 0, 0]])
    assert SIM.taksir_stok_awal(d, q).tolist() == [0, 7]
    par = _par_k1a(2)
    par["q_aktual"] = q
    r = SIM.jalankan("K1A", par, d, d, d, np.zeros(2), SIM.taksir_stok_awal(d, q))
    assert r["total_kurang"].tolist() == [0, 0]             # dari taksiran stok awal, K1 aktual tidak kehabisan stok


def test_jendela_aktual_berhenti_di_hari_tanpa_laporan():
    hari = ["2026-10-24", "2026-10-25", "2026-10-26", "2026-10-28"]
    assert [str(h.date()) for h in SIM.jendela_aktual(hari, "2026-11-01")] == ["2026-10-24", "2026-10-25", "2026-10-26"]
    assert [str(h.date()) for h in SIM.jendela_aktual(hari, "2026-10-25")] == ["2026-10-24", "2026-10-25"]
    assert SIM.jendela_aktual(hari, "2026-10-20") == []


def test_evaluasi_aktual_memilih_bahan_dan_skenario_stok_awal():
    import pandas as pd

    from ml.pipeline import evaluasi_aktual
    sp = {"val_end": pd.Timestamp("2026-10-20"), "test_end": pd.Timestamp("2026-10-26")}   # uji 21-26 Okt
    skus = ["A", "B", "C"]
    par = {**_par_k1a(3), "sigma": np.zeros(3), "d_bar": np.full(3, 2.0), "edges": [None] * 3}
    d = np.full((3, 6), 2.0)
    baris = pd.DataFrame({"tanggal": pd.to_datetime(["2026-10-24", "2026-10-25", "2026-10-24", "2026-10-24"]),
                          "sku": ["A", "A", "B", "X"], "jumlah": [4.0, 2.0, np.nan, 1.0]})
    hari = pd.to_datetime(["2026-10-24", "2026-10-25", "2026-10-26", "2026-10-27"])
    a = evaluasi_aktual({"baris": baris, "hari": hari}, sp, skus, par, d, d, d, None, 1, log=lambda *_: None)
    assert a["status"] == "ok" and a["n_hari"] == 3 and a["periode"] == ["2026-10-24", "2026-10-26"]
    assert a["skus"] == ["A"] and a["q"].tolist() == [[4.0, 2.0, 0.0]]
    assert {x["sku"]: x["alasan"] for x in a["dikecualikan"]} == {
        "B": "jumlah barang masuk belum diketahui (isi kemasan)"}
    assert a["n_luar_cakupan"] == 1                          # X punya barang masuk tetapi tidak dimodelkan
    assert a["n_tanpa_masuk"] == 1 and a["tanpa_masuk"] == ["C"]   # C terpakai tetapi tidak punya barang masuk
    assert a["stok_awal"].tolist() == [0.0]                  # 4 + 2 cukup untuk 2 + 2 + 2
    runs = a["runs"]
    assert set(runs["varian"]) == {"K1A", "K1", "K2"}        # tanpa agen, K3 dilewati
    assert sorted(runs["stok_awal"].unique()) == [SIM.STOK_AWAL_TAKSIRAN, 0.0, 0.5, 1.0, 2.0, 3.0]
    k1a = runs[(runs["varian"] == "K1A") & (runs["stok_awal"] == SIM.STOK_AWAL_TAKSIRAN)].iloc[0]
    assert k1a["total_kurang"] == 0 and k1a["total_diterima"] == 6


def test_rincian_harian_sama_dengan_total_run_dan_neraca_seimbang():
    """Catatan harian setiap run (barang datang, terbuang, kekurangan, sisa stok akhir hari) menghasilkan kembali
    setiap komponen biaya run itu, dan neraca barang seimbang setiap hari maupun seluruh periode."""
    import pandas as pd

    from ml import rincian as RC
    n, T = 2, 12
    d = np.random.default_rng(3).integers(0, 15, size=(n, T)).astype(float)
    par = {**_par_k1a(n), "k": np.array([5.0, 1.0]), "tau": np.array([3.0, 10.0]), "rop1": np.array([12.0, 4.0]),
           "q1": np.array([20.0, 6.0]), "c_h": np.array([0.2, 0.05])}
    harian = {}
    runs = SIM.evaluasi(par, d, d, d, np.ones(n), varian=("K1", "K2"), d_bar=d.mean(1), harian=harian)
    assert set(harian) == {"K1", "K2"} and harian["K1"]["I"].shape == (n * len(SIM.C.SIM_STOK_AWAL), T)
    bag = {"skus": ["A", "B"], "tanggal": [str(x.date()) for x in pd.date_range("2026-10-06", periods=T)], "d": d,
           "par": {p: np.asarray(par[p], float) for p in ("c_h", "c_s", "c_w", "c_o")}, "runs": harian}
    for r in runs.itertuples():
        df = RC.harian_run(bag, r.varian, r.b, r.stok_awal)
        t = RC.ringkas_run(df)
        assert t["biaya"] == pytest.approx(r.TC, rel=1e-5)
        for a, b in (("b_h", "b_h"), ("b_s", "b_s"), ("b_w", "b_w"), ("b_o", "b_o"), ("sisa_akhir", "sisa_akhir"),
                     ("datang", "total_diterima"), ("kurang", "total_kurang"), ("terbuang", "terbuang"),
                     ("stok_harian", "stok_harian"), ("stok_awal", "jumlah_awal"), ("pesan", "jumlah_pesan")):
            assert t[a] == pytest.approx(getattr(r, b), rel=1e-5, abs=1e-4), (r.varian, r.b, a)
        assert np.allclose(df["stok_sebelum"] - df["terbuang"] + df["datang"] - df["terpenuhi"], df["sisa_akhir"],
                           atol=1e-4)
        assert r.jumlah_awal + r.total_diterima == pytest.approx(r.total_pakai - r.total_kurang + r.terbuang
                                                                 + r.sisa_akhir)
        assert r.nilai_awal + r.nilai_diterima == pytest.approx(r.nilai_terpakai + r.nilai_terbuang + r.nilai_sisa)
    assert runs["terbuang"].sum() > 0 and runs["total_kurang"].sum() > 0   # contoh ini memuat kedua kejadian
