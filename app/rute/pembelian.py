"""Inventori > Pembelian Stok: pesanan pembelian, penerimaan (stok masuk), pembatalan."""
from datetime import date, datetime, timedelta

import pandas as pd
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import pengguna_aktif
from app.db import get_db
from app.layanan import impor_ekspor as IE
from app.layanan import stok as ST
from app.models import Bahan, MutasiStok, Pesanan, PesananItem, Rekomendasi
from app.web import flash, ke, render, tgl, unduh

router = APIRouter(prefix="/pembelian", dependencies=[Depends(pengguna_aktif)])

STATUS = {"semua": "Semua", "dipesan": "Dipesan", "terlambat": "Terlambat", "diterima": "Diterima",
          "dibatalkan": "Dibatalkan"}


def nomor_baru(db: Session, t: date) -> str:
    awalan = f"PO-{t:%Y%m%d}-"
    n = db.query(func.count(Pesanan.id)).filter(Pesanan.nomor.like(f"{awalan}%")).scalar() or 0
    while True:
        n += 1
        nomor = f"{awalan}{n:03d}"
        if not db.query(Pesanan.id).filter(Pesanan.nomor == nomor).first():
            return nomor


def buat_pesanan(db: Session, t: date, items: list, oleh: str, pemasok: str = "", catatan: str = "") -> Pesanan:
    """items: [(bahan, jumlah satuan dasar, rekomendasi_id | None)]. Perkiraan tiba = t + lead time."""
    lead = max([int(b.lead_time or 1) for b, _, _ in items] or [1])
    p = Pesanan(nomor=nomor_baru(db, t), tanggal_pesan=t, tanggal_perkiraan=t + timedelta(days=lead),
                status="dipesan", pemasok=pemasok, catatan=catatan, dibuat_oleh=oleh)
    for b, q, rid in items:
        p.items.append(PesananItem(bahan_id=b.id, jumlah=float(q), harga_satuan=float(b.harga_satuan or 0),
                                   rekomendasi_id=rid))
    db.add(p)
    db.commit()
    return p


@router.get("")
def daftar(request: Request, status: str = "semua", db: Session = Depends(get_db)):
    hari_ini = date.today()
    qry = db.query(Pesanan)
    if status in ("dipesan", "diterima", "dibatalkan"):
        qry = qry.filter(Pesanan.status == status)
    if status == "terlambat":
        qry = qry.filter(Pesanan.status == "dipesan", Pesanan.tanggal_perkiraan < hari_ini)
    rows = qry.order_by(Pesanan.tanggal_pesan.desc(), Pesanan.id.desc()).limit(300).all()
    return render(request, "pembelian_daftar.html", menu="pembelian", rows=rows, status=status, status_list=STATUS,
                  hari_ini=hari_ini)


@router.get("/baru")
def form_baru(request: Request, db: Session = Depends(get_db)):
    bahan = db.query(Bahan).filter(Bahan.aktif.is_(True)).order_by(Bahan.nama).all()
    t = (ST.tanggal_tercatat_terakhir(db) or date.today())
    return render(request, "pembelian_baru.html", menu="pembelian", bahan=bahan, t=t)


@router.post("/baru")
async def simpan_baru(request: Request, db: Session = Depends(get_db), p=Depends(pengguna_aktif)):
    form = await request.form()
    try:
        t = date.fromisoformat(form.get("tanggal_pesan") or "")
    except ValueError:
        flash(request, "Tanggal pesan tidak valid.", "galat")
        return ke("/pembelian/baru")
    ids = form.getlist("bahan_id")
    jml = form.getlist("jumlah")
    items = []
    for bid, q in zip(ids, jml):
        x = IE.angka(q)
        if not str(bid).isdigit() or x is None or x <= 0:
            continue
        b = db.get(Bahan, int(bid))
        if b is not None:
            items.append((b, x, None))
    if not items:
        flash(request, "Isi minimal satu bahan dengan jumlah > 0.", "galat")
        return ke("/pembelian/baru")
    ps = buat_pesanan(db, t, items, p.username, (form.get("pemasok") or "").strip()[:100],
                      (form.get("catatan") or "").strip())
    flash(request, f"Pesanan {ps.nomor} dibuat ({len(items)} bahan).")
    return ke(f"/pembelian/{ps.id}")


@router.get("/{pid}")
def detail(request: Request, pid: int, db: Session = Depends(get_db)):
    ps = db.get(Pesanan, pid)
    if ps is None:
        return ke("/pembelian")
    return render(request, "pembelian_detail.html", menu="pembelian", ps=ps, hari_ini=date.today(),
                  terima_bawaan=min(max(ps.tanggal_perkiraan, ps.tanggal_pesan), date.today())
                  if ps.tanggal_perkiraan <= date.today() else ps.tanggal_perkiraan)


@router.post("/{pid}/ubah")
async def ubah(request: Request, pid: int, db: Session = Depends(get_db)):
    ps = db.get(Pesanan, pid)
    if ps is None or ps.status != "dipesan":
        flash(request, "Hanya pesanan berstatus Dipesan yang dapat diubah.", "galat")
        return ke(f"/pembelian/{pid}")
    form = await request.form()
    for it in list(ps.items):
        x = IE.angka(form.get(f"jumlah_{it.id}"))
        if x is None:
            continue
        if x <= 0:
            ps.items.remove(it)
        else:
            it.jumlah = x
    ps.pemasok = (form.get("pemasok") or ps.pemasok or "").strip()[:100]
    ps.catatan = (form.get("catatan") or "").strip()
    try:
        ps.tanggal_perkiraan = date.fromisoformat(form.get("tanggal_perkiraan") or "")
    except ValueError:
        pass
    if not ps.items:
        ps.status = "dibatalkan"
    db.commit()
    flash(request, f"Pesanan {ps.nomor} diperbarui.")
    return ke(f"/pembelian/{pid}")


@router.post("/{pid}/terima")
async def terima(request: Request, pid: int, db: Session = Depends(get_db), p=Depends(pengguna_aktif)):
    ps = db.get(Pesanan, pid)
    if ps is None or ps.status != "dipesan":
        flash(request, "Pesanan ini sudah tidak berstatus Dipesan.", "galat")
        return ke(f"/pembelian/{pid}")
    form = await request.form()
    try:
        t = date.fromisoformat(form.get("tanggal_terima") or "")
    except ValueError:
        flash(request, "Tanggal terima tidak valid.", "galat")
        return ke(f"/pembelian/{pid}")
    if t < ps.tanggal_pesan:
        flash(request, "Tanggal terima tidak boleh sebelum tanggal pesan.", "galat")
        return ke(f"/pembelian/{pid}")
    n = 0
    for it in ps.items:
        x = IE.angka(form.get(f"diterima_{it.id}"))
        x = it.jumlah if x is None else max(x, 0.0)
        it.jumlah_diterima = x
        if x > 0:
            db.add(MutasiStok(bahan_id=it.bahan_id, tanggal=t, jenis="masuk", jumlah=x, pesanan_item_id=it.id,
                              keterangan=f"Penerimaan {ps.nomor}", dibuat_oleh=p.username))
            n += 1
    ps.status = "diterima"
    ps.tanggal_terima = t
    db.commit()
    telat = (t - ps.tanggal_perkiraan).days
    flash(request, f"{ps.nomor} diterima {tgl(t)}: stok masuk {n} bahan" +
          (f" (terlambat {telat} hari)" if telat > 0 else "") + ".")
    return ke(f"/pembelian/{pid}")


@router.post("/{pid}/batal")
def batal(request: Request, pid: int, db: Session = Depends(get_db)):
    ps = db.get(Pesanan, pid)
    if ps is not None and ps.status == "dipesan":
        ps.status = "dibatalkan"
        db.commit()
        flash(request, f"Pesanan {ps.nomor} dibatalkan dan tidak lagi dihitung sebagai stok dalam perjalanan.")
    return ke(f"/pembelian/{pid}")


@router.post("/{pid}/batal-terima")
def batal_terima(request: Request, pid: int, db: Session = Depends(get_db)):
    """Koreksi salah catat: hapus stok masuk pesanan ini dan kembalikan statusnya menjadi Dipesan."""
    ps = db.get(Pesanan, pid)
    if ps is None or ps.status != "diterima":
        return ke(f"/pembelian/{pid}")
    ids = [it.id for it in ps.items]
    db.query(MutasiStok).filter(MutasiStok.pesanan_item_id.in_(ids)).delete(synchronize_session=False)
    for it in ps.items:
        it.jumlah_diterima = None
    ps.status, ps.tanggal_terima = "dipesan", None
    db.commit()
    flash(request, f"Penerimaan {ps.nomor} dibatalkan; pesanan kembali berstatus Dipesan.", "peringatan")
    return ke(f"/pembelian/{pid}")


@router.get("/{pid}/unduh")
def unduh_pesanan(pid: int, db: Session = Depends(get_db)):
    ps = db.get(Pesanan, pid)
    if ps is None:
        return ke("/pembelian")
    df = pd.DataFrame([{"SKU": it.bahan.sku, "Nama Bahan": it.bahan.nama, "Jumlah": it.jumlah,
                        "Satuan": it.bahan.satuan,
                        "Jumlah Kemasan": round(it.jumlah / it.bahan.kemasan_isi, 2) if it.bahan.kemasan_isi else None,
                        "Kemasan": it.bahan.kemasan_nama, "Perkiraan Harga (Rp)": round(it.jumlah * it.harga_satuan)}
                       for it in ps.items])
    info = [["Nomor", ps.nomor], ["Tanggal pesan", tgl(ps.tanggal_pesan)],
            ["Perkiraan tiba", tgl(ps.tanggal_perkiraan)], ["Pemasok", ps.pemasok or "-"]]
    return unduh(IE.buku_tabel("Pesanan Pembelian", df, info), f"{ps.nomor}.xlsx")
