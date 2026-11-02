"""Inventori > Daftar Bahan Baku."""
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth import admin_saja, pengguna_aktif
from app.db import get_db
from app.layanan import impor_ekspor as IE
from app.models import Bahan, SatuanBahan
from app.web import berbeda, flash, ke, render, unduh

router = APIRouter(prefix="/bahan", dependencies=[Depends(pengguna_aktif)])

SATUAN_UMUM = ["Gram", "Pcs", "Botol", "Kantung", "Pack", "Ml", "Liter", "Kg", "Lembar", "Ikat", "Keping", "Tabung"]
FIELD_ASUMSI = {"harga_satuan": "harga", "kemasan_isi": "kemasan", "kemasan_nama": "kemasan",
                "masa_simpan": "masa_simpan", "lead_time": "lead_time", "biaya_kehabisan": "biaya_kehabisan",
                "maks_kelipatan": "kapasitas"}


@router.get("")
def daftar(request: Request, q: str = "", kategori: str = "", tampil: int = 50, hal: int = 1,
           db: Session = Depends(get_db)):
    qry = db.query(Bahan).filter(Bahan.aktif.is_(True))
    if q:
        pola = f"%{q.strip()}%"
        qry = qry.filter(or_(Bahan.nama.ilike(pola), Bahan.sku.ilike(pola)))
    if kategori:
        qry = qry.filter(Bahan.kategori == kategori)
    total = qry.count()
    tampil = max(10, min(tampil, 500))
    hal = max(1, min(hal, max(1, -(-total // tampil))))
    rows = qry.order_by(Bahan.nama).offset((hal - 1) * tampil).limit(tampil).all()
    kategori_list = [k for (k,) in db.query(Bahan.kategori).filter(Bahan.aktif.is_(True)).distinct()
                     .order_by(Bahan.kategori).all()]
    n_asumsi = db.query(Bahan).filter(Bahan.aktif.is_(True), Bahan.asumsi != "").count()
    return render(request, "bahan_daftar.html", menu="bahan", rows=rows, q=q, kategori=kategori,
                  kategori_list=kategori_list, total=total, tampil=tampil, hal=hal, n_asumsi=n_asumsi)


def _kategori(db):
    return [k for (k,) in db.query(Bahan.kategori).distinct().order_by(Bahan.kategori).all()]


@router.get("/tambah")
def form_tambah(request: Request, db: Session = Depends(get_db)):
    b = Bahan(sku="", nama="", kategori="Lainnya", satuan="Gram", monitor=True, kemasan_nama="Kemasan",
              kemasan_isi=1.0, harga_satuan=0.0, masa_simpan=30, lead_time=1, biaya_kehabisan=0.0, asumsi="",
              stok_minimum=0.0)
    return render(request, "bahan_form.html", menu="bahan", b=b, baru=True, kategori_list=_kategori(db),
                  satuan_list=SATUAN_UMUM)


def _ambil_form(form) -> tuple[dict, list]:
    galat = []

    def num(k, wajib=True, bulat=False, positif=False):
        v = (form.get(k) or "").strip()
        if v == "":
            if wajib:
                galat.append(f"{k.replace('_', ' ')} wajib diisi")
            return None
        x = IE.angka(v)
        if x is None or x < 0 or (positif and x <= 0):
            galat.append(f"{k.replace('_', ' ')} harus angka {'> 0' if positif else '>= 0'}")
            return None
        return int(round(x)) if bulat else x

    d = {
        "sku": (form.get("sku") or "").strip(), "nama": (form.get("nama") or "").strip(),
        "kategori": (form.get("kategori") or "Lainnya").strip() or "Lainnya",
        "satuan": (form.get("satuan") or "Gram").strip() or "Gram", "monitor": form.get("monitor") == "on",
        "kemasan_nama": (form.get("kemasan_nama") or "Kemasan").strip() or "Kemasan",
        "kemasan_isi": num("kemasan_isi", positif=True), "harga_satuan": num("harga_satuan"),
        "masa_simpan": num("masa_simpan", bulat=True, positif=True), "lead_time": num("lead_time", bulat=True,
                                                                                    positif=True),
        "maks_kelipatan": num("maks_kelipatan", wajib=False, bulat=True, positif=True),
        "biaya_kehabisan": num("biaya_kehabisan"), "catatan": (form.get("catatan") or "").strip(),
    }
    if not d["sku"]:
        galat.append("SKU wajib diisi")
    if not d["nama"]:
        galat.append("Nama bahan wajib diisi")
    return d, galat


@router.post("/tambah")
async def tambah(request: Request, db: Session = Depends(get_db), p=Depends(admin_saja)):
    form = await request.form()
    d, galat = _ambil_form(form)
    lama = db.query(Bahan).filter(func.lower(Bahan.sku) == d["sku"].lower()).first()
    if lama is not None and lama.aktif:
        galat.append(f"SKU {d['sku']} sudah dipakai {lama.nama}")
    if galat:
        b = Bahan(**{k: v for k, v in d.items()}, asumsi="", stok_minimum=0.0)
        return render(request, "bahan_form.html", menu="bahan", b=b, baru=True, galat=galat,
                      kategori_list=_kategori(db), satuan_list=SATUAN_UMUM, status_code=400)
    b = lama or Bahan(sku=d["sku"])
    for k, v in d.items():
        setattr(b, k, v)
    b.aktif = True
    b.asumsi = ""
    b.sumber_harga = b.sumber_kemasan = b.sumber_biaya_kehabisan = "diisi kafe"
    if lama is None:
        b.satuan_lain.append(SatuanBahan(no=1, satuan=b.satuan, sku=b.sku, konversi=1.0, dasar=True))
        db.add(b)
    db.commit()
    flash(request, f"Bahan baku {b.nama} ditambahkan. Bahan baru ikut dimodelkan setelah pelatihan ulang.")
    return ke("/bahan")


@router.post("/hapus-terpilih")
async def hapus_terpilih(request: Request, db: Session = Depends(get_db), p=Depends(admin_saja)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("pilih") if str(x).isdigit()]
    n = 0
    for b in db.query(Bahan).filter(Bahan.id.in_(ids)).all() if ids else []:
        b.aktif = False
        n += 1
    db.commit()
    flash(request, f"{n} bahan baku dihapus.")
    return ke("/bahan")


@router.get("/{bid}")
def form_ubah(request: Request, bid: int, db: Session = Depends(get_db)):
    b = db.get(Bahan, bid)
    if b is None or not b.aktif:
        flash(request, "Bahan tidak ditemukan.", "galat")
        return ke("/bahan")
    return render(request, "bahan_form.html", menu="bahan", b=b, baru=False, kategori_list=_kategori(db),
                  satuan_list=SATUAN_UMUM)


@router.post("/{bid}")
async def ubah(request: Request, bid: int, db: Session = Depends(get_db), p=Depends(admin_saja)):
    b = db.get(Bahan, bid)
    if b is None:
        return ke("/bahan")
    form = await request.form()
    d, galat = _ambil_form(form)
    d["sku"] = b.sku      # SKU tidak diubah karena dipakai riwayat dan majoo
    if galat:
        return render(request, "bahan_form.html", menu="bahan", b=b, baru=False, galat=galat,
                      kategori_list=_kategori(db), satuan_list=SATUAN_UMUM, status_code=400)
    asumsi = set(b.daftar_asumsi)
    for k, v in d.items():
        if berbeda(getattr(b, k), v):
            setattr(b, k, v)
            tanda = FIELD_ASUMSI.get(k)
            if tanda:
                asumsi.discard(tanda)
                if tanda == "harga":
                    b.sumber_harga = "diisi kafe"
                elif tanda == "kemasan":
                    b.sumber_kemasan = "diisi kafe"
                elif tanda == "biaya_kehabisan":
                    b.sumber_biaya_kehabisan = "diisi kafe"
    if form.get("konfirmasi") == "on":
        asumsi.clear()
        b.sumber_harga = b.sumber_kemasan = b.sumber_biaya_kehabisan = "diisi kafe"
    b.asumsi = ",".join(sorted(asumsi))
    b.diubah = datetime.now()
    dasar = next((u for u in b.satuan_lain if u.dasar), None)
    if dasar is not None:
        dasar.satuan = b.satuan
    db.commit()
    flash(request, f"Perubahan {b.nama} disimpan.")
    return ke("/bahan")


@router.post("/{bid}/hapus")
def hapus(request: Request, bid: int, db: Session = Depends(get_db), p=Depends(admin_saja)):
    b = db.get(Bahan, bid)
    if b is not None:
        b.aktif = False
        db.commit()
        flash(request, f"{b.nama} dihapus dari daftar bahan baku (riwayat stok tetap tersimpan).")
    return ke("/bahan")


@router.get("/berkas/ekspor")
def ekspor(db: Session = Depends(get_db)):
    wb = IE.buku_bahan(db)
    return unduh(IE.ke_bytes(wb), f"Ekspor_Daftar_Bahan_Baku_{datetime.now():%Y%m%d}.xlsx")


@router.get("/berkas/template")
def template(db: Session = Depends(get_db)):
    wb = IE.buku_bahan(db)
    wb.move_sheet("Petunjuk", offset=-(len(wb.sheetnames) - 1))
    wb.active = 0
    return unduh(IE.ke_bytes(wb), "Template_Data_Master_PrediStok.xlsx")


@router.post("/berkas/impor")
async def impor(request: Request, berkas: UploadFile = File(...), db: Session = Depends(get_db),
                p=Depends(admin_saja)):
    data = await berkas.read()
    try:
        h = IE.impor_bahan(db, data)
    except ValueError as e:
        flash(request, str(e), "galat")
        return ke("/bahan")
    pesan = f"Impor selesai: {h['baru']} bahan baru, {h['diubah']} bahan diperbarui"
    if h["parameter"]:
        pesan += f", parameter {h['parameter']} bahan diperbarui"
    if h["biaya"]:
        pesan += ", biaya umum diperbarui"
    flash(request, pesan + ".")
    if h["galat"]:
        flash(request, "Baris yang dilewati: " + "; ".join(h["galat"][:10]) +
              (f" (dan {len(h['galat']) - 10} lainnya)" if len(h["galat"]) > 10 else ""), "peringatan")
    return ke("/bahan")
