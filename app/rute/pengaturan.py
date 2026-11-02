"""Pengaturan: biaya, parameter pelatihan, kata sandi, dan pengguna."""
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

import config as C
from app.auth import admin_saja, cek_sandi, hash_sandi, pengguna_aktif
from app.db import get_db
from app.layanan import impor_ekspor as IE
from app.layanan import pengaturan as PG
from app.models import Pengguna
from app.web import flash, ke, render

router = APIRouter(prefix="/pengaturan", dependencies=[Depends(pengguna_aktif)])


@router.get("")
def halaman(request: Request, db: Session = Depends(get_db)):
    return render(request, "pengaturan.html", menu="pengaturan", cfg=PG.semua(db), label=PG.LABEL,
                  pengguna_list=db.query(Pengguna).order_by(Pengguna.id).all(), C=C)


@router.post("")
async def simpan(request: Request, db: Session = Depends(get_db), p=Depends(admin_saja)):
    form = await request.form()
    nilai, galat = {}, []
    for k in ("biaya_pesan", "biaya_simpan_persen"):
        x = IE.angka(form.get(k))
        if x is None or x < 0:
            galat.append(PG.LABEL[k])
        else:
            nilai[k] = x
    for k, lo, hi in (("ql_episode", 200, 50000), ("ql_seed", 1, 10)):
        x = IE.angka(form.get(k))
        if x is None or not lo <= x <= hi:
            galat.append(f"{PG.LABEL[k]} ({lo}-{hi})")
        else:
            nilai[k] = int(x)
    nilai["ql_tuning"] = form.get("ql_tuning") == "on"
    nilai["xgb_grid_search"] = form.get("xgb_grid_search") == "on"
    nama = (form.get("nama_outlet") or "").strip()
    if nama:
        nilai["nama_outlet"] = nama[:100]
    if galat:
        flash(request, "Nilai tidak valid: " + ", ".join(galat), "galat")
        return ke("/pengaturan")
    PG.simpan(db, nilai)
    flash(request, "Pengaturan disimpan. Biaya baru dipakai pada pelatihan ulang berikutnya.")
    return ke("/pengaturan")


@router.post("/sandi")
def ganti_sandi(request: Request, lama: str = Form(...), baru: str = Form(...), ulang: str = Form(...),
                db: Session = Depends(get_db), p=Depends(pengguna_aktif)):
    u = db.get(Pengguna, p.id)
    if not cek_sandi(lama, u.hash_sandi):
        flash(request, "Kata sandi lama salah.", "galat")
    elif len(baru) < 8:
        flash(request, "Kata sandi baru minimal 8 karakter.", "galat")
    elif baru != ulang:
        flash(request, "Ulangi kata sandi baru dengan benar.", "galat")
    else:
        u.hash_sandi = hash_sandi(baru)
        u.sandi_bawaan = False
        db.commit()
        flash(request, "Kata sandi berhasil diganti.")
    return ke("/pengaturan")


@router.post("/pengguna")
def tambah_pengguna(request: Request, username: str = Form(...), nama: str = Form(...), sandi: str = Form(...),
                    peran: str = Form("staf"), db: Session = Depends(get_db), p=Depends(admin_saja)):
    username = username.strip()
    if not username or len(sandi) < 8:
        flash(request, "Isi nama pengguna dan kata sandi minimal 8 karakter.", "galat")
    elif db.query(Pengguna).filter(func.lower(Pengguna.username) == username.lower()).first():
        flash(request, f"Nama pengguna {username} sudah dipakai.", "galat")
    else:
        db.add(Pengguna(username=username, nama=nama.strip() or username, hash_sandi=hash_sandi(sandi),
                        peran="admin" if peran == "admin" else "staf"))
        db.commit()
        flash(request, f"Pengguna {username} ditambahkan.")
    return ke("/pengaturan")


@router.post("/pengguna/{uid}/nonaktif")
def nonaktif(request: Request, uid: int, db: Session = Depends(get_db), p=Depends(admin_saja)):
    u = db.get(Pengguna, uid)
    if u is None or u.id == p.id:
        flash(request, "Tidak dapat menonaktifkan akun sendiri.", "galat")
    else:
        u.aktif = not u.aktif
        db.commit()
        flash(request, f"Akun {u.username} {'diaktifkan' if u.aktif else 'dinonaktifkan'}.")
    return ke("/pengaturan")
