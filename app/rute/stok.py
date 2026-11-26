"""Inventori > Kelola Stok: Daftar Stok, kartu stok, Stok Opname, Stok Terbuang, Stok Keluar Harian, Catatan
Barang Masuk."""
from datetime import date, datetime, timedelta

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth import pengguna_aktif
from app.db import get_db
from app.layanan import catatan_manual as CM
from app.layanan import impor_ekspor as IE
from app.layanan import stok as ST
from app.models import Bahan, CatatanBarang, MutasiStok, PencatatanHarian, StokKeluar
from app.web import angka_pas, flash, ke, render, tgl, unduh

router = APIRouter(prefix="/stok", dependencies=[Depends(pengguna_aktif)])

FILTER_JUMLAH = {"semua": "Jumlah Stok", "minus": "Stok minus", "kritis": "Di bawah stok minimum",
                 "habis": "Stok habis (0)", "tersedia": "Stok tersedia"}
KOLOM_OPSIONAL = {"terbuang": "Terbuang", "selisih": "Selisih Opname", "minimum": "Stok Minimum (ROP)",
                  "transit": "Dalam Perjalanan", "nilai": "Nilai Stok"}


def _tanggal(s, bawaan):
    try:
        return date.fromisoformat(s) if s else bawaan
    except ValueError:
        return bawaan


def _rentang(db, mulai, sampai):
    akhir = ST.tanggal_tercatat_terakhir(db) or date.today()
    awal = ST.tanggal_tercatat_pertama(db) or akhir
    m, s = _tanggal(mulai, awal), _tanggal(sampai, akhir)
    if m > s:
        m, s = s, m
    return m, s


def _baris_stok(db, mulai, sampai, q="", kategori="", jumlah="semua"):
    qry = db.query(Bahan).filter(Bahan.aktif.is_(True))
    if q:
        pola = f"%{q.strip()}%"
        qry = qry.filter(or_(Bahan.nama.ilike(pola), Bahan.sku.ilike(pola)))
    if kategori:
        qry = qry.filter(Bahan.kategori == kategori)
    bahan = qry.order_by(Bahan.nama).all()
    if not bahan:
        return [], None
    buku = ST.susun_buku(db, sampai, [b.id for b in bahan])
    rk = buku.ringkas(mulai, sampai)
    transit = ST.dalam_perjalanan(db, sampai)
    rows = []
    for b in bahan:
        r = rk.loc[b.id]
        akhir = float(r["akhir"])
        kritis = b.monitor and (akhir < -1e-9 or (b.stok_minimum or 0) > 0 and akhir <= b.stok_minimum)
        row = {"b": b, "awal": r["awal"], "masuk": r["masuk"], "keluar": r["keluar"], "terbuang": r["terbuang"],
               "selisih": r["selisih"], "akhir": akhir, "diketahui": bool(r["diketahui"]), "kritis": kritis,
               "transit": transit.get(b.id, 0.0), "nilai": max(akhir, 0) * (b.harga_satuan or 0)}
        if jumlah == "minus" and not akhir < -1e-9:
            continue
        if jumlah == "kritis" and not kritis:
            continue
        if jumlah == "habis" and abs(akhir) > 1e-9:
            continue
        if jumlah == "tersedia" and not akhir > 1e-9:
            continue
        rows.append(row)
    return rows, buku


@router.get("")
def daftar_stok(request: Request, mulai: str = "", sampai: str = "", q: str = "", kategori: str = "",
                jumlah: str = "semua", db: Session = Depends(get_db)):
    m, s = _rentang(db, mulai, sampai)
    rows, _ = _baris_stok(db, m, s, q, kategori, jumlah)
    kategori_list = [k for (k,) in db.query(Bahan.kategori).filter(Bahan.aktif.is_(True)).distinct()
                     .order_by(Bahan.kategori).all()]
    n_tanpa_opname = sum(1 for r in rows if not r["diketahui"] and r["b"].monitor)
    return render(request, "stok_daftar.html", menu="stok", rows=rows, mulai=m, sampai=s, q=q, kategori=kategori,
                  jumlah=jumlah, kategori_list=kategori_list, filter_jumlah=FILTER_JUMLAH,
                  kolom_opsional=KOLOM_OPSIONAL, n_tanpa_opname=n_tanpa_opname)


@router.get("/ekspor")
def ekspor_stok(mulai: str = "", sampai: str = "", q: str = "", kategori: str = "", jumlah: str = "semua",
                db: Session = Depends(get_db)):
    m, s = _rentang(db, mulai, sampai)
    rows, _ = _baris_stok(db, m, s, q, kategori, jumlah)
    df = pd.DataFrame([{
        "SKU": r["b"].sku, "Nama": r["b"].nama, "Jenis": "Bahan", "Kategori": r["b"].kategori,
        "Awal": round(r["awal"], 2), "Masuk": round(r["masuk"], 2), "Terjual (Keluar)": round(r["keluar"], 2),
        "Terbuang": round(r["terbuang"], 2), "Selisih Opname": round(r["selisih"], 2), "Akhir": round(r["akhir"], 2),
        "Stok Minimum (ROP)": r["b"].stok_minimum, "Dalam Perjalanan": round(r["transit"], 2),
        "Satuan": r["b"].satuan, "Status": "Kritis" if r["kritis"] else "",
        "Sudah Opname": "Ya" if r["diketahui"] else "Belum"} for r in rows])
    data = IE.buku_tabel("Daftar Stok", df, [["Periode", f"{tgl(m)} - {tgl(s)}"],
                                             ["Tanggal Ekspor", datetime.now().strftime("%d/%m/%Y %H:%M")]])
    return unduh(data, f"Daftar_Stok_{m:%Y%m%d}_{s:%Y%m%d}.xlsx")


# ---------------------------------------------------------------- stok opname
@router.get("/opname")
def opname(request: Request, tanggal: str = "", q: str = "", kategori: str = "", db: Session = Depends(get_db)):
    t = _tanggal(tanggal, ST.tanggal_tercatat_terakhir(db) or date.today())
    qry = db.query(Bahan).filter(Bahan.aktif.is_(True), Bahan.monitor.is_(True))
    if q:
        pola = f"%{q.strip()}%"
        qry = qry.filter(or_(Bahan.nama.ilike(pola), Bahan.sku.ilike(pola)))
    if kategori:
        qry = qry.filter(Bahan.kategori == kategori)
    bahan = qry.order_by(Bahan.kategori, Bahan.nama).all()
    buku = ST.susun_buku(db, t, [b.id for b in bahan]) if bahan else None
    tercatat = {b.id: float(buku.akhir_pada(t)[buku.kolom(b.id)]) for b in bahan} if buku else {}
    tahu = {b.id: bool(buku.diketahui_pada(t)[buku.kolom(b.id)]) for b in bahan} if buku else {}
    riwayat = db.query(MutasiStok).filter(MutasiStok.jenis == "opname").order_by(MutasiStok.tanggal.desc(),
                                                                                  MutasiStok.id.desc()).limit(50).all()
    kategori_list = [k for (k,) in db.query(Bahan.kategori).filter(Bahan.aktif.is_(True)).distinct()
                     .order_by(Bahan.kategori).all()]
    return render(request, "stok_opname.html", menu="opname", t=t, bahan=bahan, tercatat=tercatat, tahu=tahu,
                  riwayat=riwayat, q=q, kategori=kategori, kategori_list=kategori_list)


@router.post("/opname")
async def simpan_opname(request: Request, db: Session = Depends(get_db), p=Depends(pengguna_aktif)):
    form = await request.form()
    t = _tanggal(form.get("tanggal"), None)
    if t is None:
        flash(request, "Tanggal opname tidak valid.", "galat")
        return ke("/stok/opname")
    n, galat = 0, []
    for k, v in form.items():
        if not k.startswith("fisik_") or str(v).strip() == "":
            continue
        q = IE.angka(v)
        if q is None or q < 0:
            galat.append(k)
            continue
        db.add(MutasiStok(bahan_id=int(k[6:]), tanggal=t, jenis="opname", jumlah=q,
                          keterangan=(form.get("keterangan") or "").strip()[:200], dibuat_oleh=p.username))
        n += 1
    db.commit()
    flash(request, f"Stok opname {tgl(t)} tersimpan untuk {n} bahan." if n else "Tidak ada stok fisik yang diisi.",
          "sukses" if n else "peringatan")
    if galat:
        flash(request, f"{len(galat)} isian bukan angka yang valid dan dilewati.", "peringatan")
    return ke(f"/stok/opname?tanggal={t}")


@router.get("/opname/template")
def template_opname(tanggal: str = "", db: Session = Depends(get_db)):
    t = _tanggal(tanggal, ST.tanggal_tercatat_terakhir(db) or date.today())
    ids = [b for (b,) in db.query(Bahan.id).filter(Bahan.aktif.is_(True)).all()]
    buku = ST.susun_buku(db, t, ids)
    tercatat = {b: float(buku.akhir_pada(t)[buku.kolom(b)]) for b in ids}
    return unduh(IE.ke_bytes(IE.buku_opname(db, t, tercatat)), f"Template_Stok_Opname_{t:%Y%m%d}.xlsx")


@router.post("/opname/impor")
async def impor_opname(request: Request, tanggal: str = Form(...), berkas: UploadFile = File(...),
                       db: Session = Depends(get_db), p=Depends(pengguna_aktif)):
    t = _tanggal(tanggal, None)
    if t is None:
        flash(request, "Tanggal opname tidak valid.", "galat")
        return ke("/stok/opname")
    try:
        h = IE.impor_opname(db, await berkas.read(), t, p.username)
    except ValueError as e:
        flash(request, str(e), "galat")
        return ke("/stok/opname")
    flash(request, f"Impor opname {tgl(t)}: {h['baris']} bahan.")
    if h["galat"]:
        flash(request, "; ".join(h["galat"][:10]), "peringatan")
    return ke(f"/stok/opname?tanggal={t}")


@router.post("/mutasi/{mid}/hapus")
def hapus_mutasi(request: Request, mid: int, kembali: str = Form("/stok/opname"), db: Session = Depends(get_db)):
    m = db.get(MutasiStok, mid)
    if m is not None and m.pesanan_item_id is None:
        db.delete(m)
        db.commit()
        flash(request, "Catatan dihapus.")
    elif m is not None:
        flash(request, "Stok masuk dari pesanan dihapus lewat menu Pembelian Stok.", "peringatan")
    return ke(kembali if kembali.startswith("/") else "/stok/opname")


# ---------------------------------------------------------------- stok terbuang
@router.get("/terbuang")
def terbuang(request: Request, db: Session = Depends(get_db)):
    t = ST.tanggal_tercatat_terakhir(db) or date.today()
    bahan = db.query(Bahan).filter(Bahan.aktif.is_(True)).order_by(Bahan.nama).all()
    buku = ST.susun_buku(db, t, [b.id for b in bahan]) if bahan else None
    usulan = []
    if buku is not None:
        tahu = buku.diketahui_pada(t)
        for b in bahan:
            j = buku.kolom(b.id)
            if not tahu[j]:
                continue
            u = ST.umur_stok(ST.batch_fifo(buku, b.id, t), t, int(b.masa_simpan), int(b.lead_time or 1))
            if u["kedaluwarsa"] > 1e-9 or u["hampir_kedaluwarsa"] > 1e-9:
                usulan.append({"b": b, **u})
    riwayat = db.query(MutasiStok).filter(MutasiStok.jenis == "terbuang").order_by(MutasiStok.tanggal.desc(),
                                                                                   MutasiStok.id.desc()).limit(50).all()
    return render(request, "stok_terbuang.html", menu="terbuang", t=t, bahan=bahan, usulan=usulan, riwayat=riwayat)


@router.post("/terbuang")
def simpan_terbuang(request: Request, tanggal: str = Form(...), bahan_id: int = Form(...), jumlah: str = Form(...),
                    alasan: str = Form("Kedaluwarsa"), db: Session = Depends(get_db), p=Depends(pengguna_aktif)):
    t = _tanggal(tanggal, None)
    q = IE.angka(jumlah)
    b = db.get(Bahan, bahan_id)
    if t is None or q is None or q <= 0 or b is None:
        flash(request, "Isi tanggal, bahan, dan jumlah terbuang (> 0).", "galat")
        return ke("/stok/terbuang")
    db.add(MutasiStok(bahan_id=b.id, tanggal=t, jenis="terbuang", jumlah=q, keterangan=alasan[:200],
                      dibuat_oleh=p.username))
    db.commit()
    flash(request, f"Stok terbuang {b.nama} {angka_pas(q)} {b.satuan} dicatat.")
    return ke("/stok/terbuang")


# ---------------------------------------------------------------- stok keluar harian
@router.get("/keluar")
def stok_keluar(request: Request, tanggal: str = "", q: str = "", db: Session = Depends(get_db)):
    terakhir = ST.tanggal_tercatat_terakhir(db)
    t = _tanggal(tanggal, (terakhir + timedelta(days=1)) if terakhir else date.today())
    hari = db.query(PencatatanHarian).order_by(PencatatanHarian.tanggal.desc()).limit(35).all()
    nilai = dict(db.query(StokKeluar.tanggal, func.sum(StokKeluar.jumlah * Bahan.harga_satuan))
                 .join(Bahan, Bahan.id == StokKeluar.bahan_id)
                 .filter(StokKeluar.tanggal >= (hari[-1].tanggal if hari else date.today()))
                 .group_by(StokKeluar.tanggal).all())
    qry = db.query(Bahan).filter(Bahan.aktif.is_(True))
    if q:
        pola = f"%{q.strip()}%"
        qry = qry.filter(or_(Bahan.nama.ilike(pola), Bahan.sku.ilike(pola)))
    bahan = qry.order_by(Bahan.nama).all()
    isi = {r.bahan_id: r.jumlah for r in db.query(StokKeluar).filter(StokKeluar.tanggal == t).all()}
    status = db.get(PencatatanHarian, t)
    kosong = ST.hari_belum_tercatat(db, terakhir, 7) if terakhir else []
    return render(request, "stok_keluar.html", menu="keluar", t=t, hari=hari, nilai=nilai, bahan=bahan, isi=isi,
                  status=status, q=q, terakhir=terakhir, kosong=kosong)


@router.post("/keluar")
async def simpan_stok_keluar(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    t = _tanggal(form.get("tanggal"), None)
    if t is None:
        flash(request, "Tanggal tidak valid.", "galat")
        return ke("/stok/keluar")
    isi, salah = {}, 0
    for bid in {int(x) for x in form.getlist("tampil") if str(x).isdigit()}:
        v = str(form.get(f"keluar_{bid}") or "").strip()
        x = IE.angka(v) if v else 0.0
        if x is None or x < 0:
            salah += 1
            continue
        isi[bid] = x
    # formulir bisa difilter: bahan yang tidak tampil tetap memakai nilai lama
    IE.simpan_stok_keluar(db, {t: isi}, sumber="manual", ganti_hari=False)
    flash(request, f"Stok keluar {tgl(t)} tersimpan ({sum(1 for v in isi.values() if v > 0)} bahan terpakai; "
                   f"isian kosong dianggap 0).")
    if salah:
        flash(request, f"{salah} isian bukan angka yang valid dan dilewati.", "peringatan")
    return ke(f"/stok/keluar?tanggal={t}")


@router.post("/keluar/tutup")
def tandai_tutup(request: Request, tanggal: str = Form(...), db: Session = Depends(get_db)):
    t = _tanggal(tanggal, None)
    if t is None:
        return ke("/stok/keluar")
    IE.simpan_stok_keluar(db, {t: {}}, sumber="manual", ganti_hari=True, status="tutup")
    flash(request, f"{tgl(t)} ditandai kafe tutup (pemakaian 0).")
    return ke(f"/stok/keluar?tanggal={t}")


@router.post("/keluar/impor")
async def impor_stok_keluar(request: Request, tanggal: str = Form(""), berkas: UploadFile = File(...),
                            db: Session = Depends(get_db)):
    try:
        h = IE.impor_stok_keluar(db, await berkas.read(), _tanggal(tanggal, None))
    except ValueError as e:
        flash(request, str(e), "galat")
        return ke("/stok/keluar")
    flash(request, f"Impor stok keluar: {h['hari']} hari ({tgl(h['mulai'])} s.d. {tgl(h['sampai'])}), "
                   f"{h['baris']} baris.")
    if h["tidak_dikenal"]:
        flash(request, f"SKU tidak dikenal dilewati: {', '.join(h['tidak_dikenal'][:15])}", "peringatan")
    return ke("/stok/keluar")


@router.get("/keluar/template")
def template_keluar(tanggal: str = "", db: Session = Depends(get_db)):
    t = _tanggal(tanggal, date.today())
    bahan = db.query(Bahan).filter(Bahan.aktif.is_(True)).order_by(Bahan.nama).all()
    df = pd.DataFrame([{"Tanggal": t.strftime("%d/%m/%Y"), "SKU": b.sku, "Nama Bahan": b.nama, "Satuan": b.satuan,
                        "Jumlah Keluar": None} for b in bahan])
    return unduh(IE.buku_tabel("Stok Keluar", df), f"Template_Stok_Keluar_{t:%Y%m%d}.xlsx")


# ---------------------------------------------------------------- catatan barang masuk (laporan WhatsApp cafe)
def _cakupan_catatan(db) -> dict | None:
    """Rentang barang masuk tercatat dan perkiraan periode uji aktual K1 (irisan dengan stok keluar)."""
    hari = [t for (t,) in db.query(CatatanBarang.tanggal).filter(CatatanBarang.jenis == "masuk").distinct()
            .order_by(CatatanBarang.tanggal).all()]
    if not hari:
        return None
    pakai_sampai = ST.tanggal_tercatat_terakhir(db)
    jendela = CM.jendela_aktual(hari, pakai_sampai)
    lengkap = [hari[0] + timedelta(days=i) for i in range((hari[-1] - hari[0]).days + 1)]
    bolong = [t for t in lengkap if t not in set(hari)]
    return {"mulai": hari[0], "sampai": hari[-1], "n_hari": len(hari), "pakai_sampai": pakai_sampai,
            "jendela": [j.date() for j in jendela], "bolong": bolong}


def _simpan_catatan(request, db, df, sumber, oleh):
    if df.empty:
        flash(request, "Tidak ada laporan yang dikenali. Catatan harus memuat judul seperti \"REPORT ORDER tanggal "
                       "24-oktober-2026\" atau \"barang masuk hari ini tanggal 24-oktober-2026\".", "galat")
        return None
    h = CM.simpan_ke_db(db, df, sumber=sumber, oleh=oleh)
    rentang = (f" ({tgl(h['hari_masuk'][0])} s.d. {tgl(h['hari_masuk'][-1])})" if h["hari_masuk"] else "")
    flash(request, f"Catatan tersimpan: {h['masuk']} baris barang masuk{rentang} dan {h['order']} baris order. "
                   f"{h['dipakai']} baris barang masuk dipakai K1.")
    if h["perlu_dicek"]:
        flash(request, f"{h['perlu_dicek']} baris barang masuk memakai asumsi (status perlu dicek). Unduh Excel, cek "
                       f"lembar Perlu Dicek, lalu impor kembali Excel yang sudah dikoreksi.", "peringatan")
    return h


@router.get("/catatan")
def catatan(request: Request, tanggal: str = "", jenis: str = "masuk", status: str = "",
            db: Session = Depends(get_db)):
    jenis = jenis if jenis in ("masuk", "order") else "masuk"
    hari = {}
    for t, j, st, n in (db.query(CatatanBarang.tanggal, CatatanBarang.jenis, CatatanBarang.status, func.count())
                        .group_by(CatatanBarang.tanggal, CatatanBarang.jenis, CatatanBarang.status).all()):
        h = hari.setdefault(t, {"tanggal": t, "masuk": 0, "order": 0, "cek": 0, "pakai": 0})
        h[j] += n
        if j == "masuk" and st == CM.PERLU_DICEK:
            h["cek"] += n
        if j == "masuk" and st in CM.STATUS_DIPAKAI:
            h["pakai"] += n
    hari = sorted(hari.values(), key=lambda h: h["tanggal"], reverse=True)
    semua = tanggal == "semua"
    t = None if semua else _tanggal(tanggal, None)
    if t is None and not semua:
        t = hari[0]["tanggal"] if hari else None
        if status:
            semua, t = True, None
    q = db.query(CatatanBarang).filter(CatatanBarang.jenis == jenis)
    if t is not None:
        q = q.filter(CatatanBarang.tanggal == t)
    if status:
        q = q.filter(CatatanBarang.status == status)
    rows = q.order_by(CatatanBarang.tanggal, CatatanBarang.id).limit(2000).all() if hari else []
    n_status = dict(db.query(CatatanBarang.status, func.count()).filter(CatatanBarang.jenis == jenis)
                    .group_by(CatatanBarang.status).all())
    return render(request, "stok_catatan.html", menu="catatan", hari=hari, rows=rows, t=t, semua=semua, jenis=jenis,
                  status=status, n_status=n_status, cakupan=_cakupan_catatan(db), SEMUA_STATUS=CM.SEMUA_STATUS,
                  ARTI_STATUS=CM.ARTI_STATUS, PERLU_DICEK=CM.PERLU_DICEK, DIPAKAI=CM.DIPAKAI, BELUM_ADA=CM.BELUM_ADA)


@router.post("/catatan/tempel")
def tempel_catatan(request: Request, teks: str = Form(""), db: Session = Depends(get_db),
                   p=Depends(pengguna_aktif)):
    df, _ = CM.rapikan(teks, CM.Master.dari_db(db))
    h = _simpan_catatan(request, db, df, f"tempel {datetime.now():%d/%m/%Y %H:%M}", p.username)
    t = h["hari_masuk"][-1] if h and h["hari_masuk"] else ""
    return ke(f"/stok/catatan?tanggal={t}")


@router.post("/catatan/impor")
async def impor_catatan(request: Request, berkas: UploadFile = File(...), db: Session = Depends(get_db),
                        p=Depends(pengguna_aktif)):
    data = await berkas.read()
    nama = (berkas.filename or "").lower()
    M = CM.Master.dari_db(db)
    try:
        if nama.endswith(".txt"):
            df, _ = CM.rapikan(data.decode("utf-8", errors="replace"), M)
        elif nama.endswith(".xlsx"):
            import io
            df = CM.baca_excel(io.BytesIO(data), M)
        else:
            raise ValueError("Pilih file .txt (tempelan WhatsApp) atau .xlsx (Excel catatan yang sudah dikoreksi).")
    except (ValueError, KeyError) as e:
        flash(request, f"Impor gagal: {e}", "galat")
        return ke("/stok/catatan")
    h = _simpan_catatan(request, db, df, berkas.filename or "impor", p.username)
    t = h["hari_masuk"][-1] if h and h["hari_masuk"] else ""
    return ke(f"/stok/catatan?tanggal={t}")


@router.get("/catatan/unduh")
def unduh_catatan(db: Session = Depends(get_db)):
    import io
    df = CM.dari_db(db)
    if df.empty:
        return ke("/stok/catatan")
    buf = io.BytesIO()
    CM.tulis_excel(df, None, buf, judul_sumber=", ".join(sorted(set(df["sumber"]) - {""})))
    m = df[df["jenis"] == "masuk"]["tanggal"] if (df["jenis"] == "masuk").any() else df["tanggal"]
    return unduh(buf.getvalue(), f"Catatan_Barang_Masuk_{min(m):%Y%m%d}-{max(m):%Y%m%d}.xlsx")


@router.post("/catatan/hapus")
def hapus_catatan(request: Request, tanggal: str = Form(...), jenis: str = Form(...), db: Session = Depends(get_db)):
    t = _tanggal(tanggal, None)
    if t is None or jenis not in ("masuk", "order"):
        return ke("/stok/catatan")
    n = (db.query(CatatanBarang).filter(CatatanBarang.tanggal == t, CatatanBarang.jenis == jenis)
         .delete(synchronize_session=False))
    db.commit()
    flash(request, f"{n} baris catatan {'barang masuk' if jenis == 'masuk' else 'order'} {tgl(t)} dihapus.")
    return ke("/stok/catatan")


# ---------------------------------------------------------------- kartu stok satu bahan
@router.get("/{bid}")
def kartu_stok(request: Request, bid: int, mulai: str = "", sampai: str = "", db: Session = Depends(get_db)):
    b = db.get(Bahan, bid)
    if b is None:
        return ke("/stok")
    m, s = _rentang(db, mulai, sampai)
    buku = ST.susun_buku(db, s, [b.id])
    sel = (buku.tanggal >= pd.Timestamp(m)) & (buku.tanggal <= pd.Timestamp(s))
    harian = []
    for i in [k for k, v in enumerate(sel) if v]:
        harian.append({"tanggal": buku.tanggal[i].date(), "awal": buku.akhir[i - 1, 0] if i > 0 else 0.0,
                       "masuk": buku.masuk[i, 0], "keluar": buku.keluar[i, 0], "terbuang": buku.terbuang[i, 0],
                       "opname": buku.opname[i, 0], "selisih": buku.selisih[i, 0], "akhir": buku.akhir[i, 0],
                       "diketahui": bool(buku.diketahui[i, 0])})
    batches = ST.batch_fifo(buku, b.id, s) if buku.diketahui_pada(s)[0] else []
    batch_rows = [{"tanggal": r, "jumlah": q, "umur": (s - r).days,
                   "kedaluwarsa": r + timedelta(days=int(b.masa_simpan) - 1)} for r, q in batches]
    mutasi = db.query(MutasiStok).filter(MutasiStok.bahan_id == b.id, MutasiStok.tanggal >= m,
                                         MutasiStok.tanggal <= s).order_by(MutasiStok.tanggal.desc()).all()
    # sebelum opname pertama stok fisik tidak diketahui, jadi tidak digambar
    grafik = {"label": [str(h["tanggal"]) for h in harian],
              "akhir": [round(h["akhir"], 2) if h["diketahui"] else None for h in harian],
              "keluar": [round(h["keluar"], 2) for h in harian]}
    return render(request, "stok_kartu.html", menu="stok", b=b, harian=list(reversed(harian)), mulai=m, sampai=s,
                  batches=batch_rows, mutasi=mutasi, grafik=grafik, diketahui=bool(buku.diketahui_pada(s)[0]))
