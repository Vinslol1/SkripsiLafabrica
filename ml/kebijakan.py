"""Rumus persediaan: ROP statis dan EOQ (K1), ROP dinamis dan order-up-to (K2), serta diskretisasi state.

Penomoran persamaan mengikuti proposal (v4):
  (1)  ROP = d*L + SS            (2)  SS = Z * sigma_d * sqrt(L)       (3)  EOQ = sqrt(2*d*c_o / c_h)
  (20) D_hat = sum_{j=1..L} y_hat_{t+j}                               (21) ROP_t = D_hat + Z * sigma_e * sqrt(L)
  (25) OUT_t = sum_{j=1..L+1} y_hat_{t+j} + Z * sigma_e * sqrt(L+1)
  (26) q_t = 1(IP_t <= ROP_t) * k * ceil((OUT_t - IP_t) / k)
  (27) s_t = (b(IP_t), b(D_hat), b(E_t), 1(IP_t <= ROP_t))

Linimasa yang dipakai (konsisten dengan Persamaan 29): keputusan dibuat pada akhir hari t setelah
pemakaian hari t tercatat, pesanan tiba awal hari t+1 (lead time 1 hari), sehingga y_hat_{t+1} adalah
prediksi pemakaian besok.
"""
import math

import numpy as np

import config as C

UKURAN_GRAM = [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000]
UKURAN_PCS = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]
MASA_SIMPAN_TAHAN_LAMA = 30


def ukuran_kemasan_bawaan(rata_harian: float, satuan: str = "Gram", masa_simpan: float = None) -> float:
    """Ukuran kemasan sementara untuk bahan yang ukuran kemasannya belum diketahui.

    Bahan cepat rusak (masa simpan < 30 hari) biasanya dibeli harian: angka bulat terbesar yang tidak melebihi
    rata-rata pemakaian sehari. Bahan tahan lama dibeli dalam kemasan toko: angka bulat terbesar yang tidak
    melebihi pemakaian dua minggu, minimal 100 gram untuk bahan bersatuan gram.
    """
    deret = UKURAN_GRAM if satuan == "Gram" else UKURAN_PCS
    tahan_lama = masa_simpan is not None and masa_simpan >= MASA_SIMPAN_TAHAN_LAMA
    batas = rata_harian * (14 if tahan_lama else 1)
    pilih = [u for u in deret if u <= batas]
    k = float(pilih[-1] if pilih else deret[0])
    if tahan_lama and satuan == "Gram":
        k = max(k, 100.0)
    return k


def rop_statis(d_bar: float, sigma_d: float, L: int = C.LEAD_TIME, Z: float = C.Z_LAYANAN) -> float:
    """Persamaan (1) dan (2)."""
    return d_bar * L + Z * sigma_d * math.sqrt(L)


def eoq(d_bar: float, c_o: float, c_h: float) -> float:
    """Persamaan (3)."""
    if c_h <= 0 or d_bar <= 0:
        return 0.0
    return math.sqrt(2.0 * d_bar * c_o / c_h)


def q_klasik(d_bar: float, c_o: float, c_h: float, tau: float, k: float) -> float:
    """Jumlah pesanan tetap K1: min(EOQ, d*tau) dibulatkan ke atas ke kelipatan kemasan (minimal 1 kemasan)."""
    q = min(eoq(d_bar, c_o, c_h), d_bar * tau)
    return max(k, k * math.ceil(q / k - 1e-9)) if k > 0 else q


def rop_dinamis(prediksi, sigma_e: float, L: int = C.LEAD_TIME, Z: float = C.Z_LAYANAN) -> float:
    """Persamaan (20) dan (21); `prediksi` = [y_hat_{t+1}, y_hat_{t+2}, ...]."""
    return float(np.sum(prediksi[:L])) + Z * sigma_e * math.sqrt(L)


def stok_target(prediksi, sigma_e: float, L: int = C.LEAD_TIME, Z: float = C.Z_LAYANAN) -> float:
    """Persamaan (25)."""
    return float(np.sum(prediksi[:L + 1])) + Z * sigma_e * math.sqrt(L + 1)


def q_order_up_to(ip: float, rop: float, out: float, k: float) -> float:
    """Persamaan (26)."""
    if ip > rop:
        return 0.0
    return max(0.0, k * math.ceil((out - ip) / k - 1e-9))


# ---------------------------------------------------------------- diskretisasi state (Persamaan 27)
EPS = 1e-9


def tepi_bin(d_latih: np.ndarray, f1_latih: np.ndarray, n_ip=C.QL_BIN_IP, n_d=C.QL_BIN_D, n_e=C.QL_BIN_E) -> dict:
    """Batas interval b(.) dari data latih satu bahan.

    - prediksi kebutuhan: kuantil prediksi out-of-sample pada periode latih,
    - posisi persediaan: 0, kuantil kebutuhan L+1 hari pada periode latih, lalu 1,5x dan 2,5x kuantil 90%,
    - stok hampir kedaluwarsa: 0 lalu 0,25 / 0,5 / 1 kali rata-rata pemakaian harian.
    """
    d = np.asarray(d_latih, float)
    d2 = d[:-1] + d[1:] if len(d) > 1 else d
    qs = np.linspace(0.1, 0.9, n_ip - 4)
    q_ip = np.quantile(d2, qs) if len(d2) else np.zeros(len(qs))
    top = q_ip[-1] if len(q_ip) else 0.0
    ip_edges = np.unique(np.concatenate([[EPS], q_ip[q_ip > EPS], [1.5 * top, 2.5 * top]]))
    ip_edges = ip_edges[ip_edges > 0]
    qd = np.linspace(0, 1, n_d + 1)[1:-1]
    f = np.asarray(f1_latih, float)
    d_edges = np.unique(np.quantile(f, qd)) if len(f) else np.array([])
    dbar = float(d.mean()) if len(d) else 0.0
    e_edges = np.unique(np.array([EPS] + [x * dbar for x in (0.25, 0.5, 1.0)][: n_e - 2]))
    e_edges = e_edges[e_edges > 0]
    return {"ip": ip_edges.tolist(), "d": d_edges.tolist(), "e": e_edges.tolist()}


def indeks_bin(x: float, edges) -> int:
    return int(np.sum(x > np.asarray(edges, float))) if len(edges) else 0


def indeks_state(ip: float, d_hat: float, e: float, flag: int, edges: dict,
                 n_d=C.QL_BIN_D, n_e=C.QL_BIN_E) -> int:
    bi, bd, be = indeks_bin(ip, edges["ip"]), indeks_bin(d_hat, edges["d"]), indeks_bin(e, edges["e"])
    return ((bi * n_d + bd) * n_e + be) * 2 + int(flag)


def jumlah_state(n_ip=C.QL_BIN_IP, n_d=C.QL_BIN_D, n_e=C.QL_BIN_E) -> int:
    return n_ip * n_d * n_e * 2
