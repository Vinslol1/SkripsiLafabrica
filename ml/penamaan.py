"""Penamaan varian kebijakan dan konversi artefak model lama.

Sejak penamaan versi 2 (November 2026):
    K1 = barang masuk aktual cafe diputar ulang (dulu "K1 aktual", kode K1A)
    K2 = ROP statis + EOQ dari data historis (dulu "K1 statis", kode K1; K1 pada proposal)
    K3 = ROP dinamis + order-up-to (dulu K2)
    K4 = ROP dinamis + Q-Learning (dulu K3)

Artefak model yang dilatih sebelum perubahan ini (evaluasi.json, simulasi_harian.npz, ringkasan run di basis data)
tidak memiliki penanda PENANDA, sehingga kodenya diterjemahkan saat dibaca agar riwayat model lama tetap tampil benar.
"""
import re

PENANDA = "penamaan_varian"
VERSI = 2
LAMA_KE_BARU = {"K1A": "K1", "K1": "K2", "K2": "K3", "K3": "K4"}
_TOKEN = re.compile(r"(?<![A-Za-z0-9])K(1A|[123])(?![0-9A-Za-z])")


def kode_baru(teks: str) -> str:
    """Ganti setiap kode varian lama di dalam teks (mis. "K3_vs_K1A" -> "K4_vs_K1", "uji_K1_q" -> "uji_K2_q")."""
    return _TOKEN.sub(lambda m: LAMA_KE_BARU["K" + m.group(1)], teks)


def perlu_konversi(obj) -> bool:
    return isinstance(obj, dict) and obj.get(PENANDA, 1) < VERSI


def konversi(obj):
    """Salinan obj dengan kode varian lama pada kunci dict dan nilai teks diganti ke penamaan baru."""
    if isinstance(obj, dict):
        return {(kode_baru(k) if isinstance(k, str) else k): konversi(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [konversi(v) for v in obj]
    if isinstance(obj, str):
        return kode_baru(obj)
    return obj


def seragamkan(obj):
    """Hasil evaluasi atau ringkasan run dalam penamaan baru (dikonversi bila dibuat sebelum penamaan versi 2)."""
    if not isinstance(obj, dict):
        return obj
    if perlu_konversi(obj):
        obj = konversi(obj)
    obj[PENANDA] = VERSI
    return obj
