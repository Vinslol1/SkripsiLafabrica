"""Agen Q-Learning tabular, satu Q-table per bahan (subbab 8.6, 9.9, 9.10 proposal).

Pelatihan dijalankan serentak untuk banyak agen (bahan x seed) dengan NumPy. Setiap agen punya
Q-table, lingkungan, data, dan generator acak sendiri, jadi hasilnya sama dengan melatih satu per satu.

Episode = 4 blok minggu (Senin-Minggu) yang dipilih acak dengan pengembalian dari minggu-minggu
pelatihan (bootstrap blok); setiap blok berisi pemakaian aktual dan prediksi XGBoost out-of-sample.
Stok awal episode acak. Q-table diawali 0, epsilon turun eksponensial 1,0 -> 0,01.
"""
import math
import time

import numpy as np

import config as C
from ml.kebijakan import jumlah_state
from ml.lingkungan import Lingkungan

N_IP, N_D, N_E = C.QL_BIN_IP, C.QL_BIN_D, C.QL_BIN_E


def _pad(list_of_lists, fill=np.inf):
    n = max((len(x) for x in list_of_lists), default=0)
    out = np.full((len(list_of_lists), max(n, 1)), fill)
    for i, x in enumerate(list_of_lists):
        out[i, :len(x)] = x
    return out


class RuangState:
    """Diskretisasi Persamaan (27) yang tervektorisasi untuk banyak agen."""

    def __init__(self, edges_list):
        self.ip = _pad([e["ip"] for e in edges_list])
        self.d = _pad([e["d"] for e in edges_list])
        self.e = _pad([e["e"] for e in edges_list])

    def indeks(self, ip, d_hat, e, flag):
        bi = (ip[:, None] > self.ip).sum(1)
        bd = (d_hat[:, None] > self.d).sum(1)
        be = (e[:, None] > self.e).sum(1)
        return ((bi * N_D + bd) * N_E + be) * 2 + flag.astype(int)


def jadwal_epsilon(ep, n_ep, awal=C.QL_EPS_AWAL, akhir=C.QL_EPS_AKHIR, sampai=C.QL_EPS_SAMPAI):
    """Epsilon turun eksponensial dari `awal` hingga `akhir` pada episode ke sampai*n_ep, lalu tetap."""
    t = min(ep / max(sampai * n_ep, 1), 1.0)
    return float(awal * (akhir / awal) ** t)


class KumpulanAgen:
    """Q-table untuk n agen. Aksi ke-i memesan i * k, i = 0..m (Persamaan 28).

    mode_alpha "tetap"    : Persamaan (17) dengan learning rate tetap alpha.
    mode_alpha "tak_bias" : learning rate beta_n = alpha / (1 - (1 - alpha)^n) untuk kunjungan ke-n pada pasangan
                            (s, a) (unbiased constant step size, Sutton & Barto 2018, subbab 2.5). beta_1 = 1 dan
                            beta_n turun ke alpha, sehingga nilai awal Q0 = 0 tidak lagi membuat aksi yang jarang
                            dicoba tampak murah; untuk n besar pembaruannya sama dengan Persamaan (17).
    """

    def __init__(self, k, m, n_aksi_maks=None, mode_alpha="tetap", kap=None):
        self.k = np.asarray(k, float)
        self.m = np.asarray(m, int)
        self.n = len(self.k)
        self.n_aksi = int(n_aksi_maks or (self.m.max() + 1))
        self.n_state = jumlah_state()
        self.Q = np.zeros((self.n, self.n_state, self.n_aksi))
        self.N = np.zeros((self.n, self.n_state, self.n_aksi), dtype=np.int32)
        self._a = np.arange(self.n_aksi)[None, :]
        self.valid = self._a <= self.m[:, None]
        self.kap = np.full(self.n, np.inf) if kap is None else np.nan_to_num(np.asarray(kap, float), nan=np.inf)
        self.idx = np.arange(self.n)
        self.mode_alpha = mode_alpha

    def jumlah(self, a, ia=None):
        ia = self.idx if ia is None else ia
        return a * self.k[ia]

    def layak(self, ip, ia=None):
        """Aksi Persamaan (28) yang tidak membuat posisi persediaan melebihi kapasitas simpan (aksi 0 selalu layak).

        Aksi layak selalu berurutan 0..a_maks karena posisi setelah memesan naik seiring i.
        """
        ia = self.idx if ia is None else ia
        muat = np.asarray(ip, float)[:, None] + self._a * self.k[ia, None] <= self.kap[ia, None] + 1e-9
        return self.valid[ia] & (muat | (self._a == 0))

    def pilih_eps(self, s, eps, u_explore, u_aksi, ip=None):
        ok = self.valid if ip is None else self.layak(ip)
        qs = np.where(ok, self.Q[self.idx, s], -np.inf)
        greedy = qs.argmax(1)
        n_ok = ok.sum(1)
        acak = np.minimum((u_aksi * n_ok).astype(int), n_ok - 1)
        return np.where(u_explore < eps, acak, greedy)

    def perbarui(self, s, a, r, s2, alpha, gamma, ip2=None):
        ok2 = self.valid if ip2 is None else self.layak(ip2)
        q_next = np.where(ok2, self.Q[self.idx, s2], -np.inf).max(1)
        self.N[self.idx, s, a] += 1
        if self.mode_alpha == "tak_bias":
            n = self.N[self.idx, s, a]
            beta = alpha / (1.0 - (1.0 - alpha) ** n)
        else:
            beta = alpha
        lama = self.Q[self.idx, s, a]
        self.Q[self.idx, s, a] = lama + beta * (r + gamma * q_next - lama)

    def greedy(self, s, ia=None, min_kunjungan=1, ip=None):
        """Aksi terbaik di antara aksi layak yang pernah dicoba pada state s; -1 jika state belum pernah ditemui.

        `ia` memetakan setiap lingkungan ke agennya (dipakai saat satu agen diuji dengan beberapa stok awal).
        """
        ia = self.idx if ia is None else ia
        n_sa = self.N[ia, s]
        ok = self.valid[ia] if ip is None else self.layak(ip, ia)
        dicoba = (n_sa >= min_kunjungan) & ok
        qs = np.where(dicoba, self.Q[ia, s], -np.inf)
        a = qs.argmax(1)
        return np.where(dicoba.any(1), a, -1)


def latih_agen(par: dict, data: dict, seeds, n_episode=C.QL_EPISODE, alpha=C.QL_ALPHA, gamma=C.QL_GAMMA,
               panjang=C.QL_PANJANG_EPISODE, log=print, catat_kurva_setiap=50, mode_alpha=C.QL_MODE_ALPHA):
    """Latih satu agen per (seed, bahan).

    par  : dict array per bahan: k, m, kap, tau, c_h, c_s, c_w, c_o, sigma, d_bar, edges(list)
    data : dict array [bahan, minggu, 7]: d, f1, f2 (minggu Senin-Minggu out-of-sample)
    Mengembalikan KumpulanAgen berukuran len(seeds) * n_bahan (urutan: seed lalu bahan) dan kurva reward.
    """
    n_b = len(par["k"])
    S = len(seeds)
    rep = lambda x: np.tile(np.asarray(x), S) if np.ndim(x) == 1 else np.tile(x, (S, 1))
    gens = [np.random.default_rng(s) for s in seeds]

    def acak(*shape):
        return np.concatenate([g.random((n_b,) + shape) for g in gens])

    def acak_int(hi, *shape):
        return np.concatenate([g.integers(0, hi, size=(n_b,) + shape) for g in gens])

    agen = KumpulanAgen(rep(par["k"]), rep(par["m"]), mode_alpha=mode_alpha,
                        kap=rep(par["kap"]) if "kap" in par else None)
    env = Lingkungan(rep(par["tau"]), rep(par["c_h"]), rep(par["c_s"]), rep(par["c_w"]), rep(par["c_o"]),
                     n_umur=panjang + 4)
    ruang = RuangState(list(par["edges"]) * S)
    sig = rep(par["sigma"]) * C.Z_LAYANAN * math.sqrt(C.LEAD_TIME)
    dbar = rep(par["d_bar"])
    mat = np.tile(np.arange(n_b), S)
    D, F1 = data["d"], data["f1"]
    n_week = D.shape[1]
    n_blok = int(math.ceil((panjang + 1) / 7))
    kurva, buf, t0 = [], [], time.time()
    for ep in range(n_episode):
        eps = jadwal_epsilon(ep, n_episode)
        wk = acak_int(n_week, n_blok)
        d_ep = D[mat[:, None], wk].reshape(len(mat), -1)[:, :panjang + 1]
        f1_ep = F1[mat[:, None], wk].reshape(len(mat), -1)[:, :panjang + 1]
        env.reset(acak() * 3.0 * dbar)
        ip = env.posisi()
        e = env.hampir_kedaluwarsa()
        dh = f1_ep[:, 0]
        s = ruang.indeks(ip, dh, e, ip <= dh + sig)
        total = np.zeros(len(mat))
        for t in range(panjang):
            a = agen.pilih_eps(s, eps, acak(), acak(), ip)
            hasil = env.langkah(agen.jumlah(a), d_ep[:, t])
            r = -hasil["biaya"]
            ip = env.posisi()
            e = env.hampir_kedaluwarsa()
            dh = f1_ep[:, t + 1]
            s2 = ruang.indeks(ip, dh, e, ip <= dh + sig)
            agen.perbarui(s, a, r, s2, alpha, gamma, ip)
            s = s2
            total += r
        buf.append(total)
        if (ep + 1) % catat_kurva_setiap == 0:
            kurva.append(np.mean(buf, axis=0))
            buf = []
        if (ep + 1) % 1000 == 0:
            log(f"  Q-Learning episode {ep + 1}/{n_episode} (epsilon {eps:.3f}, {time.time() - t0:.0f} detik)")
    return agen, np.array(kurva)  # kurva: [titik, agen]
