"""Isi basis data demo (python run.py --demo) untuk presentasi.

Stok keluar harian tetap data asli. Yang disimulasikan selama 28 hari terakhir data:
  - stok opname awal = 2 x rata-rata pemakaian harian (dibulatkan ke kemasan),
  - setiap akhir hari rekomendasi dihitung (XGBoost + Q-Learning) lalu langsung dipesan,
    pesanan tiba awal hari berikutnya (L = 1),
  - stok yang melewati masa simpan dicatat terbuang (FIFO),
  - bila pemakaian asli melebihi stok, kekurangannya dicatat sebagai pembelian darurat.
Rekomendasi hari terakhir sengaja belum dipesan agar alur pemesanan bisa dicoba.
Semua catatan simulasi diberi keterangan "(simulasi demo)" dan dibuat oleh pengguna "demo".
"""
import math
from datetime import timedelta

from app.db import SesiLokal
from app.layanan import model_aktif as MA
from app.layanan import pengaturan as PG
from app.layanan import rekomendasi as RK
from app.layanan import stok as ST
from app.models import Bahan, MutasiStok, Pesanan

OLEH = "demo"
HARI = 28
LABEL = "(simulasi demo)"


def _terima_pesanan(db, t):
    for ps in db.query(Pesanan).filter(Pesanan.status == "dipesan", Pesanan.tanggal_perkiraan <= t).all():
        for it in ps.items:
            it.jumlah_diterima = it.jumlah
            db.add(MutasiStok(bahan_id=it.bahan_id, tanggal=t, jenis="masuk", jumlah=it.jumlah, pesanan_item_id=it.id,
                              keterangan=f"Penerimaan {ps.nomor}", dibuat_oleh=OLEH))
        ps.status, ps.tanggal_terima = "diterima", t
    db.commit()


def _darurat_dan_terbuang(db, t, bahan):
    ids = [b.id for b in bahan]
    akhir = ST.susun_buku(db, t, ids).akhir_pada(t)
    n_darurat = 0
    for j, b in enumerate(bahan):
        if akhir[j] < -1e-9:
            db.add(MutasiStok(bahan_id=b.id, tanggal=t, jenis="masuk", jumlah=float(-akhir[j]),
                              keterangan=f"Pembelian darurat saat stok habis {LABEL}", dibuat_oleh=OLEH))
            n_darurat += 1
    db.commit()
    buku = ST.susun_buku(db, t, ids)
    n_buang = 0
    for b in bahan:
        u = ST.umur_stok(ST.batch_fifo(buku, b.id, t), t, int(b.masa_simpan), int(b.lead_time or 1))
        if u["kedaluwarsa"] > 1e-9:
            db.add(MutasiStok(bahan_id=b.id, tanggal=t, jenis="terbuang", jumlah=float(u["kedaluwarsa"]),
                              keterangan=f"Melewati masa simpan {LABEL}", dibuat_oleh=OLEH))
            n_buang += 1
    db.commit()
    return n_darurat, n_buang


def jalankan(log=print):
    from app.rute.pembelian import buat_pesanan
    db = SesiLokal()
    try:
        if PG.semua(db).get("mode_demo"):
            return
        model = MA.ambil(db)
        akhir = ST.tanggal_tercatat_terakhir(db)
        if model is None or akhir is None:
            log("Data demo tidak dibuat: model aktif atau stok keluar belum ada.")
            return
        t0 = akhir - timedelta(days=HARI)
        bahan = [b for b in db.query(Bahan).filter(Bahan.aktif.is_(True), Bahan.monitor.is_(True))
                 .order_by(Bahan.id).all() if b.sku in model.q]
        log(f"Membuat data demo {t0 + timedelta(days=1)} s.d. {akhir} untuk {len(bahan)} bahan (sekitar 1-2 menit)...")
        for b in bahan:
            k = float(b.kemasan_isi or model.q[b.sku]["k"])
            awal = math.ceil(2 * model.q[b.sku]["d_bar"] / k - 1e-9) * k
            db.add(MutasiStok(bahan_id=b.id, tanggal=t0, jenis="opname", jumlah=float(awal),
                              keterangan=f"Stok opname awal {LABEL}", dibuat_oleh=OLEH))
        db.commit()
        for i in range(HARI + 1):
            t = t0 + timedelta(days=i)
            n_darurat = n_buang = 0
            if i > 0:
                _terima_pesanan(db, t)
                n_darurat, n_buang = _darurat_dan_terbuang(db, t, bahan)
            h = RK.hitung(db, t)
            items = [(r.bahan, r.jumlah, r.id) for r in h.baris if r.jumlah > 1e-9]
            if t < akhir and items:
                buat_pesanan(db, t, items, OLEH, pemasok=f"Pemasok {LABEL}",
                             catatan=f"Dibuat otomatis dari rekomendasi {LABEL}")
            if i % 7 == 0 or t == akhir:
                log(f"  {t}: {len(items)} bahan dipesan, {n_buang} bahan terbuang, {n_darurat} pembelian darurat")
        PG.simpan(db, {"mode_demo": True})
        log("Data demo selesai.")
    finally:
        db.close()
