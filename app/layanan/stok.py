"""Buku stok harian dan umur batch.

Urutan kejadian dalam satu hari t (sama dengan lingkungan simulasi):
  stok masuk (pesanan tiba awal hari) -> stok keluar (pemakaian) -> stok terbuang -> stok opname (hitung fisik akhir hari).
Stok akhir hari t = stok akhir t-1 + masuk - keluar - terbuang; bila ada opname, stok akhir = hasil hitung fisik.
Sebelum opname pertama, stok awal suatu bahan tidak diketahui dan dianggap 0 (seperti Daftar Stok majoo).
"""
from collections import deque
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Bahan, MutasiStok, PencatatanHarian, Pesanan, PesananItem, StokKeluar

EPS = 1e-9


@dataclass
class Buku:
    tanggal: pd.DatetimeIndex
    bahan_ids: list
    keluar: np.ndarray
    masuk: np.ndarray
    terbuang: np.ndarray
    opname: np.ndarray        # NaN bila tidak ada opname
    selisih: np.ndarray       # hasil opname dikurangi stok tercatat
    akhir: np.ndarray
    diketahui: np.ndarray     # sudah pernah diopname pada/sebelum hari itu

    def __post_init__(self):
        self._kol = {b: j for j, b in enumerate(self.bahan_ids)}

    def kolom(self, bahan_id) -> int:
        return self._kol[bahan_id]

    def _idx(self, t: date) -> int:
        """Indeks hari terakhir <= t (-1 bila t sebelum data pertama)."""
        if len(self.tanggal) == 0:
            return -1
        return int(self.tanggal.searchsorted(pd.Timestamp(t), side="right")) - 1

    def akhir_pada(self, t: date) -> np.ndarray:
        i = self._idx(t)
        return np.zeros(len(self.bahan_ids)) if i < 0 else self.akhir[i]

    def diketahui_pada(self, t: date) -> np.ndarray:
        i = self._idx(t)
        return np.zeros(len(self.bahan_ids), bool) if i < 0 else self.diketahui[i]

    def ringkas(self, mulai: date, sampai: date) -> pd.DataFrame:
        """Kolom Daftar Stok: AWAL, MASUK, KELUAR, TERBUANG, SELISIH OPNAME, AKHIR untuk rentang [mulai, sampai]."""
        sel = (self.tanggal >= pd.Timestamp(mulai)) & (self.tanggal <= pd.Timestamp(sampai))
        awal = self.akhir_pada(mulai - timedelta(days=1))
        df = pd.DataFrame({
            "awal": awal,
            "masuk": self.masuk[sel].sum(0),
            "keluar": self.keluar[sel].sum(0),
            "terbuang": self.terbuang[sel].sum(0),
            "selisih": self.selisih[sel].sum(0),
            "akhir": self.akhir_pada(sampai),
            "diketahui": self.diketahui_pada(sampai),
        }, index=pd.Index(self.bahan_ids, name="bahan_id"))
        return df


def _pivot(rows, tanggal, bahan_ids, agg="sum", isi=0.0):
    if not rows:
        return np.full((len(tanggal), len(bahan_ids)), isi)
    df = pd.DataFrame(rows, columns=["bahan_id", "tanggal", "jumlah"])
    df["tanggal"] = pd.to_datetime(df["tanggal"])
    p = df.pivot_table(index="tanggal", columns="bahan_id", values="jumlah", aggfunc=agg)
    out = p.reindex(index=tanggal, columns=bahan_ids).values.astype(float)
    return out if np.isnan(isi) else np.nan_to_num(out, nan=isi)


def susun_buku(db: Session, sampai: date, bahan_ids=None, mulai_paling_awal: date = None) -> Buku:
    if bahan_ids is None:
        bahan_ids = [b for (b,) in db.query(Bahan.id).order_by(Bahan.id).all()]
    bahan_ids = list(bahan_ids)
    q_k = db.query(StokKeluar.bahan_id, StokKeluar.tanggal, StokKeluar.jumlah).filter(StokKeluar.tanggal <= sampai)
    q_m = db.query(MutasiStok.bahan_id, MutasiStok.tanggal, MutasiStok.jenis, MutasiStok.jumlah, MutasiStok.id) \
        .filter(MutasiStok.tanggal <= sampai)
    keluar_rows = q_k.all()
    mut = q_m.order_by(MutasiStok.id).all()
    semua_tgl = [r[1] for r in keluar_rows] + [r[1] for r in mut]
    awal = min(semua_tgl) if semua_tgl else sampai
    if mulai_paling_awal:
        awal = min(awal, mulai_paling_awal)
    tanggal = pd.date_range(awal, sampai, freq="D")
    keluar = _pivot([tuple(r) for r in keluar_rows], tanggal, bahan_ids)
    masuk = _pivot([(r[0], r[1], r[3]) for r in mut if r[2] == "masuk"], tanggal, bahan_ids)
    terbuang = _pivot([(r[0], r[1], r[3]) for r in mut if r[2] == "terbuang"], tanggal, bahan_ids)
    opname = _pivot([(r[0], r[1], r[3]) for r in mut if r[2] == "opname"], tanggal, bahan_ids, agg="last",
                    isi=np.nan)
    T, n = keluar.shape
    akhir = np.zeros((T, n))
    selisih = np.zeros((T, n))
    diketahui = np.zeros((T, n), bool)
    prev = np.zeros(n)
    tahu = np.zeros(n, bool)
    for i in range(T):
        hitung = prev + masuk[i] - keluar[i] - terbuang[i]
        ada = ~np.isnan(opname[i])
        selisih[i] = np.where(ada, np.nan_to_num(opname[i]) - hitung, 0.0)
        akhir[i] = np.where(ada, np.nan_to_num(opname[i]), hitung)
        tahu = tahu | ada
        diketahui[i] = tahu
        prev = akhir[i]
    return Buku(tanggal, bahan_ids, keluar, masuk, terbuang, opname, selisih, akhir, diketahui)


def batch_fifo(buku: Buku, bahan_id: int, sampai: date) -> list:
    """Sisa batch [(tanggal terima, jumlah)] pada akhir hari `sampai`, dipakai dan dibuang secara FIFO.

    Stok dari opname pertama (atau kelebihan hasil opname) diberi tanggal penerimaan terakhir sebelum opname,
    atau tanggal opname bila belum pernah ada penerimaan.
    """
    j = buku.kolom(bahan_id)
    akhir_i = buku._idx(sampai)
    batches = deque()
    defisit = 0.0
    terima_terakhir = None
    for i in range(akhir_i + 1):
        tgl = buku.tanggal[i].date()
        m = buku.masuk[i, j]
        if m > EPS:
            bayar = min(defisit, m)
            defisit -= bayar
            m -= bayar
            terima_terakhir = tgl
            if m > EPS:
                batches.append([tgl, m])
        pakai = buku.keluar[i, j] + buku.terbuang[i, j]
        while pakai > EPS and batches:
            ambil = min(pakai, batches[0][1])
            batches[0][1] -= ambil
            pakai -= ambil
            if batches[0][1] <= EPS:
                batches.popleft()
        defisit += max(pakai, 0.0)
        op = buku.opname[i, j]
        if not np.isnan(op):
            defisit = 0.0
            ada = sum(b[1] for b in batches)
            if op < ada:
                buang = ada - op
                while buang > EPS and batches:
                    ambil = min(buang, batches[0][1])
                    batches[0][1] -= ambil
                    buang -= ambil
                    if batches[0][1] <= EPS:
                        batches.popleft()
            elif op > ada + EPS:
                batches.append([terima_terakhir or tgl, op - ada])
                batches = deque(sorted(batches, key=lambda b: b[0]))
    return [(b[0], float(b[1])) for b in batches if b[1] > EPS]


def umur_stok(batches, t: date, masa_simpan: int, lead_time: int = 1) -> dict:
    """E_t (stok yang habis masa simpannya sebelum dipakai esok hari) dan stok yang sudah lewat masa simpan.

    Batch yang diterima hari r dapat dipakai pada hari r .. r+tau-1, jadi pada akhir hari t batch berumur
    t-r >= tau-L akan terbuang sebelum pesanan berikutnya tiba (sama dengan Lingkungan.hampir_kedaluwarsa).
    """
    e = sum(q for r, q in batches if (t - r).days >= masa_simpan - lead_time)
    lewat = sum(q for r, q in batches if (t - r).days >= masa_simpan)
    return {"hampir_kedaluwarsa": float(e), "kedaluwarsa": float(lewat)}


def dalam_perjalanan(db: Session, sampai: date) -> dict:
    """Jumlah pesanan yang sudah dibuat sampai hari `sampai` tetapi belum dicatat diterima, per bahan."""
    rows = db.query(PesananItem.bahan_id, func.sum(PesananItem.jumlah)) \
        .join(Pesanan, Pesanan.id == PesananItem.pesanan_id) \
        .filter(Pesanan.status == "dipesan", Pesanan.tanggal_pesan <= sampai) \
        .group_by(PesananItem.bahan_id).all()
    return {b: float(q or 0) for b, q in rows}


def hari_tercatat(db: Session) -> set:
    return {t for (t,) in db.query(PencatatanHarian.tanggal).all()}


def tanggal_tercatat_terakhir(db: Session):
    return db.query(func.max(PencatatanHarian.tanggal)).scalar()


def tanggal_tercatat_pertama(db: Session):
    return db.query(func.min(PencatatanHarian.tanggal)).scalar()


def hari_belum_tercatat(db: Session, t: date, n: int = 7) -> list:
    ada = hari_tercatat(db)
    return [t - timedelta(days=i) for i in range(n - 1, -1, -1) if (t - timedelta(days=i)) not in ada]


def riwayat_pemakaian(db: Session, skus, sampai: date, hari: int) -> pd.DataFrame:
    """Tabel lebar pemakaian (tanggal x sku) untuk `hari` hari terakhir sampai `sampai`, hari kosong = 0."""
    mulai = sampai - timedelta(days=hari - 1)
    rows = db.query(StokKeluar.tanggal, Bahan.sku, StokKeluar.jumlah).join(Bahan, Bahan.id == StokKeluar.bahan_id) \
        .filter(StokKeluar.tanggal >= mulai, StokKeluar.tanggal <= sampai).all()
    idx = pd.date_range(mulai, sampai, freq="D")
    if not rows:
        return pd.DataFrame(0.0, index=idx, columns=list(skus))
    df = pd.DataFrame(rows, columns=["tanggal", "sku", "jumlah"])
    df["tanggal"] = pd.to_datetime(df["tanggal"])
    w = df.pivot_table(index="tanggal", columns="sku", values="jumlah", aggfunc="sum")
    return w.reindex(index=idx, columns=list(skus)).fillna(0.0).clip(lower=0)


def tabel_panjang_stok_keluar(db: Session) -> pd.DataFrame:
    """Seluruh stok keluar dalam format panjang yang sama dengan file data (untuk pelatihan ulang)."""
    rows = db.query(StokKeluar.tanggal, Bahan.sku, StokKeluar.jumlah).join(Bahan, Bahan.id == StokKeluar.bahan_id) \
        .all()
    df = pd.DataFrame(rows, columns=["Tanggal", "SKU Bahan", "Jumlah Keluar"])
    df["Tanggal"] = pd.to_datetime(df["Tanggal"])
    tutup = {t for (t,) in db.query(PencatatanHarian.tanggal).filter(PencatatanHarian.status == "tutup").all()}
    df.attrs["hari_tutup"] = sorted(tutup)
    return df
