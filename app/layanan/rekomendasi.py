"""Pemrosesan rekomendasi harian (Gambar 3 proposal).

Untuk keputusan akhir hari t (setelah stok keluar hari t tercatat; pesanan tiba awal hari t+1):
 1. cek pemakaian 7 hari terakhir lengkap (fitur lag dan rolling), bila tidak: minta pengelola melengkapi,
 2. XGBoost memprediksi pemakaian t+1 .. t+7,
 3. ROP dinamis (Persamaan 21), posisi persediaan = stok + pesanan belum tiba (Persamaan 24),
    stok hampir kedaluwarsa E_t, dan stok target (Persamaan 25),
 4. state (Persamaan 27) -> aksi terbaik Q-table; state yang belum pernah ditemui -> aturan cadangan K3 (26),
 5. peringatan stok kritis bila posisi <= ROP, jumlah dalam kelipatan kemasan dan tidak melebihi kapasitas
    simpan, simpan sebagai riwayat,
 6. ROP dinamis menjadi Stok Minimum bahan (ikut diekspor pada sheet berformat majoo).
"""
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

import config as C
from app.layanan import model_aktif as MA
from app.layanan import stok as ST
from app.models import Bahan, Rekomendasi
from ml.kebijakan import indeks_state, q_order_up_to, rop_dinamis, stok_target


@dataclass
class HasilRekomendasi:
    tanggal: date
    status: str                                   # ok / belum_lengkap / belum_ada_model
    hari_kurang: list = field(default_factory=list)
    baris: list = field(default_factory=list)     # Rekomendasi tersimpan
    tanpa_opname: list = field(default_factory=list)
    belum_dilatih: list = field(default_factory=list)
    stok_minimum_diubah: int = 0


def aksi_layak(tabel: dict, ip: float) -> np.ndarray:
    """Aksi i = 0..m yang tidak membuat posisi persediaan melebihi kapasitas simpan (aksi 0 selalu layak)."""
    i = np.arange(tabel["Q"].shape[1])
    return (ip + i * float(tabel["k"]) <= float(tabel.get("kap", math.inf)) + 1e-9) | (i == 0)


def batas_kapasitas(tabel: dict, ip: float, k: float) -> float:
    """Jumlah pesan terbesar (kelipatan k) yang masih muat di kapasitas simpan."""
    kap = float(tabel.get("kap", math.inf))
    if math.isinf(kap):
        return math.inf
    return k * math.floor(max(kap - ip, 0.0) / k + 1e-9)


def aksi_q(tabel: dict, ip: float, d_hat: float, e: float, flag: bool):
    """Aksi terbaik di antara aksi layak yang pernah dicoba pada state ini; None bila state belum pernah ditemui."""
    s = indeks_state(ip, d_hat, e, int(flag), tabel["edges"])
    n = tabel["N"][s]
    dicoba = (n >= C.QL_MIN_KUNJUNGAN) & aksi_layak(tabel, ip)
    if not dicoba.any():
        return s, None
    qs = np.where(dicoba, tabel["Q"][s], -np.inf)
    return s, int(np.argmax(qs))


def hitung(db: Session, t: date, simpan: bool = True, perbarui_stok_minimum: bool = True) -> HasilRekomendasi:
    hasil = HasilRekomendasi(tanggal=t, status="ok")
    hasil.hari_kurang = ST.hari_belum_tercatat(db, t, 7)
    if hasil.hari_kurang:
        hasil.status = "belum_lengkap"
        return hasil
    model = MA.ambil(db)
    if model is None:
        hasil.status = "belum_ada_model"
        return hasil

    riwayat = ST.riwayat_pemakaian(db, model.items, t, 14)
    prak = model.prakiraan(riwayat, pd.Timestamp(t) + pd.Timedelta(days=1))
    bahan = db.query(Bahan).filter(Bahan.aktif.is_(True), Bahan.monitor.is_(True)).order_by(Bahan.nama).all()
    buku = ST.susun_buku(db, t, [b.id for b in bahan])
    stok = buku.akhir_pada(t)
    tahu = buku.diketahui_pada(t)
    transit = ST.dalam_perjalanan(db, t)
    lama = {r.bahan_id: r for r in db.query(Rekomendasi).filter(Rekomendasi.tanggal == t).all()}
    z1 = C.Z_LAYANAN
    for j, b in enumerate(bahan):
        tabel = model.q.get(b.sku)
        if tabel is None or b.sku not in model.items:
            hasil.belum_dilatih.append(b)
            continue
        yh = prak[b.sku].values.astype(float)
        sigma = model.sigma_e.get(b.sku, tabel["sigma_e"])
        L = int(b.lead_time or C.LEAD_TIME)
        rop = rop_dinamis(yh, sigma, L=L, Z=z1)
        out = stok_target(yh, sigma, L=L, Z=z1)
        if perbarui_stok_minimum:
            baru = float(math.ceil(rop - 1e-9))
            if abs((b.stok_minimum or 0) - baru) > 1e-9:
                b.stok_minimum = baru
                b.stok_minimum_diubah = datetime.now()
                hasil.stok_minimum_diubah += 1
        if not tahu[j]:
            hasil.tanpa_opname.append(b)
            continue
        ip = float(stok[j]) + transit.get(b.id, 0.0)
        umur = ST.umur_stok(ST.batch_fifo(buku, b.id, t), t, int(b.masa_simpan), L)
        flag = ip <= rop
        s, a = aksi_q(tabel, ip, float(yh[0]), umur["hampir_kedaluwarsa"], flag)
        k_pak = float(b.kemasan_isi or tabel["k"])
        q_k3 = min(q_order_up_to(ip, rop, out, k_pak), batas_kapasitas(tabel, ip, k_pak))
        if a is None:
            sumber, q = "cadangan_k2", q_k3
        else:
            sumber, q = "q_learning", a * float(tabel["k"])
        r = lama.get(b.id) or Rekomendasi(tanggal=t, bahan_id=b.id)
        r.model_run_id = model.run_id
        r.stok, r.dalam_perjalanan, r.posisi = float(stok[j]), transit.get(b.id, 0.0), ip
        r.prediksi = [round(float(x), 4) for x in yh]
        r.rop, r.target, r.sigma_e = float(rop), float(out), float(sigma)
        r.hampir_kedaluwarsa, r.kedaluwarsa = umur["hampir_kedaluwarsa"], umur["kedaluwarsa"]
        r.kritis, r.state, r.sumber, r.jumlah, r.jumlah_k2 = bool(flag), int(s), sumber, float(q), float(q_k3)
        r.dibuat = datetime.now()
        r.bahan = b
        if simpan and r.id is None:
            db.add(r)
        hasil.baris.append(r)
    if simpan:
        db.commit()
    return hasil


def status(db: Session, t: date) -> HasilRekomendasi:
    """Kelengkapan data, model, dan bahan tanpa opname untuk tanggal t tanpa menghitung ulang rekomendasi."""
    hasil = HasilRekomendasi(tanggal=t, status="ok")
    hasil.hari_kurang = ST.hari_belum_tercatat(db, t, 7)
    model = MA.ambil(db)
    if hasil.hari_kurang:
        hasil.status = "belum_lengkap"
    elif model is None:
        hasil.status = "belum_ada_model"
    bahan = db.query(Bahan).filter(Bahan.aktif.is_(True), Bahan.monitor.is_(True)).order_by(Bahan.nama).all()
    dilatih = (set(model.q) & set(model.items)) if model else set()
    hasil.belum_dilatih = [b for b in bahan if b.sku not in dilatih]
    if bahan:
        tahu = ST.susun_buku(db, t, [b.id for b in bahan]).diketahui_pada(t)
        hasil.tanpa_opname = [b for j, b in enumerate(bahan) if b.sku in dilatih and not tahu[j]]
    return hasil


def terakhir(db: Session, t: date = None) -> list:
    """Rekomendasi tersimpan untuk tanggal t (bawaan: tanggal rekomendasi terbaru)."""
    if t is None:
        t = db.query(Rekomendasi.tanggal).order_by(Rekomendasi.tanggal.desc()).limit(1).scalar()
        if t is None:
            return []
    return db.query(Rekomendasi).filter(Rekomendasi.tanggal == t).all()


def tanggal_keputusan_bawaan(db: Session) -> date | None:
    """Hari terakhir yang stok keluarnya sudah tercatat."""
    return ST.tanggal_tercatat_terakhir(db)
