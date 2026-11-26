"""Rekomendasi Pemesanan harian (Gambar 3) dan penjelasan Q-table setiap rekomendasi."""
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import case, func
from sqlalchemy.orm import Session

import config as C
from app.auth import pengguna_aktif
from app.db import get_db
from app.layanan import impor_ekspor as IE
from app.layanan import model_aktif as MA
from app.layanan import rekomendasi as RK
from app.layanan import stok as ST
from app.models import Bahan, PesananItem, Pesanan, Rekomendasi
from app.rute.pembelian import buat_pesanan
from app.web import flash, ke, render, tgl, unduh
from ml.kebijakan import indeks_bin

router = APIRouter(prefix="/rekomendasi", dependencies=[Depends(pengguna_aktif)])

FILTER = {"perlu": "Perlu dipesan", "kritis": "Stok kritis", "semua": "Semua bahan"}


def _t(s, db):
    try:
        return date.fromisoformat(s) if s else RK.tanggal_keputusan_bawaan(db)
    except ValueError:
        return RK.tanggal_keputusan_bawaan(db)


def _pemilihan(db):
    """Ringkasan praproses bahan target dari model aktif (None untuk model lama)."""
    model = MA.ambil(db)
    ev = model.evaluasi() if model else None
    return (ev or {}).get("pemilihan")


@router.get("")
def halaman(request: Request, tanggal: str = "", filter: str = "perlu", q: str = "", kategori: str = "",
            db: Session = Depends(get_db)):
    t = _t(tanggal, db)
    if t is None:
        return render(request, "rekomendasi.html", menu="rekomendasi", t=None, hasil=None, rows=[], filter=filter,
                      filter_list=FILTER, q=q, kategori=kategori, kategori_list=[], sudah_dipesan={})
    rows = db.query(Rekomendasi).filter(Rekomendasi.tanggal == t).all()
    if not rows:
        hasil = RK.hitung(db, t)
        rows = hasil.baris
    else:
        hasil = RK.status(db, t)
    semua = len(rows)
    if q:
        rows = [r for r in rows if q.lower() in r.bahan.nama.lower() or q.lower() in r.bahan.sku.lower()]
    if kategori:
        rows = [r for r in rows if r.bahan.kategori == kategori]
    if filter == "perlu":
        rows = [r for r in rows if r.jumlah > 0]
    elif filter == "kritis":
        rows = [r for r in rows if r.kritis]
    rows.sort(key=lambda r: (not r.kritis, -(r.jumlah * (r.bahan.harga_satuan or 0)), r.bahan.nama))
    # pesanan yang sudah dibuat dari rekomendasi tanggal ini
    sudah = dict(db.query(PesananItem.rekomendasi_id, Pesanan.nomor).join(Pesanan)
                 .filter(PesananItem.rekomendasi_id.in_([r.id for r in rows if r.id]), Pesanan.status != "dibatalkan")
                 .all()) if rows else {}
    kategori_list = sorted({r.bahan.kategori for r in db.query(Rekomendasi).filter(Rekomendasi.tanggal == t).all()})
    total_nilai = sum(r.jumlah * (r.bahan.harga_satuan or 0) for r in rows if r.jumlah > 0)
    q_t = db.query(Rekomendasi).filter(Rekomendasi.tanggal == t)
    return render(request, "rekomendasi.html", menu="rekomendasi", t=t, hasil=hasil, rows=rows, semua=semua,
                  filter=filter, filter_list=FILTER, q=q, kategori=kategori, kategori_list=kategori_list,
                  sudah_dipesan=sudah, total_nilai=total_nilai, hari_ini=date.today(), t_tiba=t + timedelta(days=1),
                  n_kritis=q_t.filter(Rekomendasi.kritis.is_(True)).count(),
                  n_perlu=q_t.filter(Rekomendasi.jumlah > 0).count(), pemilihan=_pemilihan(db))


@router.post("/hitung")
def hitung(request: Request, tanggal: str = Form(""), db: Session = Depends(get_db)):
    t = _t(tanggal, db)
    if t is None:
        flash(request, "Belum ada data stok keluar.", "galat")
        return ke("/rekomendasi")
    h = RK.hitung(db, t)
    if h.status == "belum_lengkap":
        flash(request, "Rekomendasi tidak dihitung: stok keluar belum tercatat pada " +
              ", ".join(tgl(d) for d in h.hari_kurang) + ". Lengkapi pencatatan terlebih dahulu.", "galat")
    elif h.status == "belum_ada_model":
        flash(request, "Belum ada model aktif. Jalankan Pelatihan Ulang terlebih dahulu.", "galat")
    else:
        flash(request, f"Rekomendasi {tgl(t)} dihitung untuk {len(h.baris)} bahan; stok minimum (ROP) "
                       f"diperbarui untuk {h.stok_minimum_diubah} bahan.")
    return ke(f"/rekomendasi?tanggal={t}")


@router.post("/pesan")
async def pesan(request: Request, db: Session = Depends(get_db), p=Depends(pengguna_aktif)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("pilih") if str(x).isdigit()]
    items = []
    t = None
    for r in db.query(Rekomendasi).filter(Rekomendasi.id.in_(ids)).all() if ids else []:
        q = IE.angka(form.get(f"jumlah_{r.id}"))
        q = r.jumlah if q is None else q
        if q > 0:
            items.append((r.bahan, q, r.id))
            t = r.tanggal
    if not items:
        flash(request, "Pilih minimal satu bahan dengan jumlah pesan > 0.", "peringatan")
        return ke(f"/rekomendasi?tanggal={form.get('tanggal', '')}")
    ps = buat_pesanan(db, t, items, p.username, (form.get("pemasok") or "").strip()[:100],
                      f"Dibuat dari rekomendasi {tgl(t)}")
    flash(request, f"Pesanan {ps.nomor} dibuat untuk {len(items)} bahan. Stok ini dihitung sebagai pesanan dalam "
                   f"perjalanan sampai dicatat diterima.")
    return ke(f"/pembelian/{ps.id}")


@router.get("/ekspor")
def ekspor(tanggal: str = "", db: Session = Depends(get_db)):
    t = _t(tanggal, db)
    rows = db.query(Rekomendasi).filter(Rekomendasi.tanggal == t).all() if t else []
    df = pd.DataFrame([{
        "SKU": r.bahan.sku, "Nama Bahan": r.bahan.nama, "Kategori": r.bahan.kategori, "Satuan": r.bahan.satuan,
        "Stok": round(r.stok, 2), "Dalam Perjalanan": round(r.dalam_perjalanan, 2), "Posisi Persediaan": round(r.posisi, 2),
        "Prediksi Besok": round(r.prediksi[0], 2), "ROP Dinamis (Stok Minimum)": round(r.rop, 2),
        "Stok Target": round(r.target, 2), "Hampir Kedaluwarsa": round(r.hampir_kedaluwarsa, 2),
        "Rekomendasi Pesan": round(r.jumlah, 2),
        "Rekomendasi (kemasan)": round(r.jumlah / r.bahan.kemasan_isi, 2) if r.bahan.kemasan_isi else None,
        "Kemasan": r.bahan.kemasan_nama, "Sumber": "Q-Learning" if r.sumber == "q_learning" else "Aturan cadangan K3",
        "Status": "Kritis" if r.kritis else "Aman"} for r in sorted(rows, key=lambda r: r.bahan.nama)])
    data = IE.buku_tabel("Rekomendasi Pemesanan", df, [["Keputusan akhir hari", tgl(t) if t else "-"],
                                                       ["Pesanan tiba", tgl(t + timedelta(days=1)) if t else "-"]])
    return unduh(data, f"Rekomendasi_{t:%Y%m%d}.xlsx" if t else "Rekomendasi.xlsx")


@router.get("/riwayat")
def riwayat(request: Request, db: Session = Depends(get_db)):
    rows = db.query(Rekomendasi.tanggal, func.count(Rekomendasi.id),
                    func.sum(case((Rekomendasi.kritis.is_(True), 1), else_=0)),
                    func.sum(Rekomendasi.jumlah * Bahan.harga_satuan)) \
        .join(Bahan, Bahan.id == Rekomendasi.bahan_id).group_by(Rekomendasi.tanggal) \
        .order_by(Rekomendasi.tanggal.desc()).limit(120).all()
    perlu = dict(db.query(Rekomendasi.tanggal, func.count(Rekomendasi.id)).filter(Rekomendasi.jumlah > 0)
                 .group_by(Rekomendasi.tanggal).all())
    return render(request, "rekomendasi_riwayat.html", menu="rekomendasi", rows=rows, perlu=perlu)


@router.get("/{rid}")
def penjelasan(request: Request, rid: int, db: Session = Depends(get_db)):
    r = db.get(Rekomendasi, rid)
    if r is None:
        return ke("/rekomendasi")
    model = MA.ambil(db)
    tabel = model.q.get(r.bahan.sku) if model and model.run_id == r.model_run_id else None
    info = None
    if tabel is not None:
        ed = tabel["edges"]
        bi, bd, be = indeks_bin(r.posisi, ed["ip"]), indeks_bin(r.prediksi[0], ed["d"]), \
            indeks_bin(r.hampir_kedaluwarsa, ed["e"])
        s = r.state if r.state is not None else 0
        qrow, nrow = tabel["Q"][s], tabel["N"][s]
        layak = RK.aksi_layak(tabel, r.posisi)
        aksi = [{"i": i, "jumlah": i * tabel["k"], "q": float(qrow[i]), "n": int(nrow[i]), "layak": bool(layak[i])}
                for i in range(len(qrow))]
        dicoba = [a for a in aksi if a["n"] >= C.QL_MIN_KUNJUNGAN]
        info = {"bin": (bi, bd, be, int(r.kritis)), "edges": ed, "aksi": aksi, "dicoba": dicoba, "k": tabel["k"],
                "m": tabel["m"], "n_state": int(nrow.sum()), "kap": tabel.get("kap"),
                "kap_manual": tabel.get("kap_manual")}
    hari = [r.tanggal + timedelta(days=i + 1) for i in range(len(r.prediksi))]
    riwayat = ST.riwayat_pemakaian(db, [r.bahan.sku], r.tanggal, 28)[r.bahan.sku]
    grafik = {"label": [str(d.date()) for d in riwayat.index] + [str(d) for d in hari],
              "aktual": [round(float(x), 2) for x in riwayat.values] + [None] * len(hari),
              "prediksi": [None] * (len(riwayat) - 1) + [round(float(riwayat.values[-1]), 2)] +
                          [round(float(x), 2) for x in r.prediksi]}
    return render(request, "rekomendasi_detail.html", menu="rekomendasi", r=r, info=info, hari=hari, grafik=grafik,
                  Z=C.Z_LAYANAN)
