"""Penamaan varian K1-K4: artefak model lama (kode K1A/K1/K2/K3) dibaca dengan nomor baru."""
import numpy as np

from ml import penamaan as PN


def test_kode_lama_diganti_ke_nomor_baru():
    assert PN.kode_baru("K3_vs_K1A K1_TC uji_K1_q aktual_K1A_q K2 K12") == "K4_vs_K1 K2_TC uji_K2_q aktual_K1_q K3 K12"
    lama = {"kebijakan": {"utama": {"total": {"K1": {"TC_mean": 1}, "K2": {"TC_mean": 2}, "K3": {"TC_mean": 3}}}},
            "aktual": {"per_bahan": [{"K1A_TC": 5, "K1_TC": 6}], "kebijakan": {"semua": {"banding": {"K3_vs_K1A": {}}}}}}
    baru = PN.seragamkan(lama)
    assert set(baru["kebijakan"]["utama"]["total"]) == {"K2", "K3", "K4"}
    assert baru["aktual"]["per_bahan"][0] == {"K1_TC": 5, "K2_TC": 6}
    assert "K4_vs_K1" in baru["aktual"]["kebijakan"]["semua"]["banding"]
    # sudah memakai penamaan baru: tidak dikonversi dua kali
    assert PN.seragamkan(baru) == baru


def test_rincian_harian_model_lama_dibaca_dengan_nomor_baru(tmp_path):
    from ml import rincian as RC
    n, T = 2, 3
    z = {"skus": np.array(["A", "B"]), "tanggal": np.array(["2026-01-01", "2026-01-02", "2026-01-03"]),
         "d": np.ones((n, T))}
    for v in ("K1", "K2", "K3"):
        for c in ("q", "W", "S", "I", "rop", "cad"):
            z[f"uji_{v}_{c}"] = np.zeros((n, T), np.float32)
        z[f"uji_{v}_b"] = np.arange(n, dtype=np.int16)
        z[f"uji_{v}_stok_awal"] = np.ones(n, np.float32)
        z[f"uji_{v}_seed"] = np.full(n, -1, np.int16)
    np.savez_compressed(tmp_path / RC.BERKAS, **z)
    assert set(RC.muat(tmp_path)["uji"]["runs"]) == {"K2", "K3", "K4"}
