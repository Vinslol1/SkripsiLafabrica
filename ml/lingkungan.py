"""Lingkungan simulasi persediaan bahan cepat rusak (subbab 8.6 proposal).

Stok disimpan per umur (hari sejak tiba), sehingga umur setiap batch dapat dilacak. Banyak lingkungan
(bahan x seed x stok awal) dijalankan serentak dengan NumPy agar pelatihan 5.000 episode cepat.

Urutan kejadian satu langkah (keputusan akhir hari t -> hari t+1), sesuai Persamaan (29)-(31):
  1. pagi hari t+1: batch yang melewati masa simpan dibuang (W),
  2. pesanan q_t tiba sebagai batch baru berumur 0,
  3. pemakaian aktual d_{t+1} diambil dengan aturan FIFO (batch tertua dulu),
  4. permintaan yang tidak terpenuhi dicatat (S),
  5. biaya = c_h*I_akhir + c_s*S + c_w*W + c_o*1(q_t > 0); reward = -biaya.
"""
import numpy as np


class Lingkungan:
    def __init__(self, tau, c_h, c_s, c_w, c_o, n_umur=32):
        self.tau = np.asarray(tau, float)
        self.n = len(self.tau)
        self.A = int(n_umur)
        self.c_h = np.asarray(c_h, float)
        self.c_s = np.asarray(c_s, float)
        self.c_w = np.asarray(c_w, float)
        self.c_o = np.asarray(c_o, float)
        umur = np.arange(self.A)[None, :]
        # batch berumur a pada akhir hari dipakai terakhir kali hari itu jika a >= tau-1
        self.mask_buang = umur >= (self.tau[:, None] - 1)
        self.stok = np.zeros((self.n, self.A))

    def reset(self, stok_awal):
        self.stok = np.zeros((self.n, self.A))
        self.stok[:, 0] = np.asarray(stok_awal, float)

    def posisi(self) -> np.ndarray:
        """Posisi persediaan pada akhir hari = stok di tangan (pesanan L=1 sudah tiba pagi tadi)."""
        return self.stok.sum(1)

    def tersedia_besok(self) -> np.ndarray:
        """Stok yang masih bisa dipakai besok pagi (setelah batch yang melewati masa simpan dibuang)."""
        return (self.stok * ~self.mask_buang).sum(1)

    def hampir_kedaluwarsa(self, L: int = 1) -> np.ndarray:
        """E_t: stok yang melewati masa simpan dalam L hari ke depan."""
        umur = np.arange(self.A)[None, :]
        return (self.stok * (umur >= (self.tau[:, None] - L))).sum(1)

    def langkah(self, q, d) -> dict:
        q = np.asarray(q, float)
        d = np.asarray(d, float)
        buang = (self.stok * self.mask_buang).sum(1)
        st = np.where(self.mask_buang, 0.0, self.stok)
        baru = np.empty_like(st)
        baru[:, 1:] = st[:, :-1]
        baru[:, -1] += st[:, -1]
        baru[:, 0] = q
        rev = baru[:, ::-1]
        cs = np.cumsum(rev, axis=1)
        kurang = np.maximum(d - cs[:, -1], 0.0)
        sisa = np.maximum(cs - d[:, None], 0.0)
        rev2 = np.diff(sisa, axis=1, prepend=0.0)
        self.stok = np.ascontiguousarray(rev2[:, ::-1])
        akhir = self.stok.sum(1)
        b_h = self.c_h * akhir
        b_s = self.c_s * kurang
        b_w = self.c_w * buang
        b_o = self.c_o * (q > 0)
        return {"W": buang, "S": kurang, "I": akhir, "q": q, "d": d,
                "b_h": b_h, "b_s": b_s, "b_w": b_w, "b_o": b_o, "biaya": b_h + b_s + b_w + b_o}
