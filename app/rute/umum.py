"""Masuk, keluar, dan dasbor."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import cek_sandi, pengguna_aktif
from app.db import get_db
from app.layanan import model_aktif as MA
from app.layanan import stok as ST
from app.models import Bahan, ModelRun, Pengguna, Pesanan, PesananItem, Rekomendasi, StokKeluar
from app.web import flash, ke, render

router = APIRouter()


@router.get("/")
def beranda(request: Request):
    return ke("/dasbor" if request.session.get("uid") else "/masuk")


@router.get("/masuk")
def halaman_masuk(request: Request, lanjut: str = "/dasbor"):
    if request.session.get("uid"):
        return ke("/dasbor")
    return render(request, "masuk.html", lanjut=lanjut if lanjut.startswith("/") else "/dasbor")


@router.post("/masuk")
def masuk(request: Request, username: str = Form(...), sandi: str = Form(...), lanjut: str = Form("/dasbor"),
          db: Session = Depends(get_db)):
    p = db.query(Pengguna).filter(func.lower(Pengguna.username) == username.strip().lower()).first()
    if p is None or not p.aktif or not cek_sandi(sandi, p.hash_sandi):
        flash(request, "Nama pengguna atau kata sandi salah.", "galat")
        return ke("/masuk")
    request.session.clear()
    request.session["uid"] = p.id
    if p.sandi_bawaan:
        flash(request, "Anda masih memakai kata sandi bawaan. Ganti kata sandi di menu Pengaturan.", "peringatan")
    return ke(lanjut if lanjut.startswith("/") and not lanjut.startswith("//") else "/dasbor")


@router.get("/keluar")
def keluar(request: Request):
    request.session.clear()
    return ke("/masuk")


@router.get("/dasbor")
def dasbor(request: Request, db: Session = Depends(get_db), p=Depends(pengguna_aktif)):
    hari_ini = date.today()
    terakhir = ST.tanggal_tercatat_terakhir(db)
    n_bahan = db.query(Bahan).filter(Bahan.aktif.is_(True), Bahan.monitor.is_(True)).count()
    t_rek = db.query(func.max(Rekomendasi.tanggal)).scalar()
    rek = db.query(Rekomendasi).filter(Rekomendasi.tanggal == t_rek).all() if t_rek else []
    kritis = sorted([r for r in rek if r.kritis], key=lambda r: r.posisi / r.rop if r.rop > 0 else 0)
    perlu = [r for r in rek if r.jumlah > 0]
    dipesan_ids = {i for (i,) in db.query(PesananItem.rekomendasi_id).join(Pesanan)
                   .filter(PesananItem.rekomendasi_id.in_([r.id for r in perlu]), Pesanan.status != "dibatalkan")
                   .all()} if perlu else set()
    belum_dipesan = [r for r in perlu if r.id not in dipesan_ids]
    nilai_perlu = sum(r.jumlah * (r.bahan.harga_satuan or 0) for r in belum_dipesan)
    hampir = sorted([r for r in rek if r.hampir_kedaluwarsa > 1e-9 or r.kedaluwarsa > 1e-9],
                    key=lambda r: -(r.hampir_kedaluwarsa * (r.bahan.harga_satuan or 0)))
    pesanan = db.query(Pesanan).filter(Pesanan.status == "dipesan").order_by(Pesanan.tanggal_perkiraan).all()
    terlambat = [x for x in pesanan if x.terlambat(hari_ini)]
    run = db.query(ModelRun).filter(ModelRun.aktif.is_(True)).first()
    model = MA.ambil(db)
    ev = model.evaluasi() if model else None
    # nilai pemakaian per hari 28 hari terakhir
    grafik = {"label": [], "nilai": []}
    if terakhir:
        mulai = terakhir - timedelta(days=27)
        rows = db.query(StokKeluar.tanggal, func.sum(StokKeluar.jumlah * Bahan.harga_satuan)) \
            .join(Bahan, Bahan.id == StokKeluar.bahan_id) \
            .filter(StokKeluar.tanggal >= mulai, StokKeluar.tanggal <= terakhir) \
            .group_by(StokKeluar.tanggal).order_by(StokKeluar.tanggal).all()
        grafik = {"label": [str(t) for t, _ in rows], "nilai": [round(float(v or 0)) for _, v in rows]}
    tanpa_opname = 0
    if terakhir and model is not None:
        # bahan yang sudah punya prediksi dan Q-table tetapi belum pernah diopname (tidak bisa direkomendasikan)
        ids = [b for (b,) in db.query(Bahan.id).filter(Bahan.aktif.is_(True), Bahan.monitor.is_(True),
                                                       Bahan.sku.in_(list(model.q))).all()]
        tanpa_opname = int((~ST.susun_buku(db, terakhir, ids).diketahui_pada(terakhir)).sum()) if ids else 0
    return render(request, "dasbor.html", menu="dasbor", hari_ini=hari_ini, terakhir=terakhir, n_bahan=n_bahan,
                  t_rek=t_rek, kritis=kritis, perlu=perlu, belum_dipesan=belum_dipesan, nilai_perlu=nilai_perlu,
                  hampir=hampir[:8], pesanan=pesanan, terlambat=terlambat, run=run, ev=ev, grafik=grafik,
                  tanpa_opname=tanpa_opname, besok_catat=terakhir + timedelta(days=1) if terakhir else None,
                  tertinggal=(hari_ini - terakhir).days - 1 if terakhir else None)
