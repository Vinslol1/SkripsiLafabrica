"""Analisis Model: Prediksi Kebutuhan, Evaluasi Prediksi, Simulasi Kebijakan K1/K2/K3, Pelatihan Ulang."""
import math
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

import config as C
from app.auth import admin_saja, pengguna_aktif
from app.db import get_db
from app.layanan import model_aktif as MA
from app.layanan import pelatihan as PL
from app.layanan import stok as ST
from app.models import Bahan, ModelRun
from app.web import angka, angka_pas, bersih, flash, ke, render
from ml import rincian as RC
from ml import simulasi as SIM

router = APIRouter(dependencies=[Depends(pengguna_aktif)])

LAPORAN = {"evaluasi": "evaluasi_xgboost.xlsx", "simulasi": "simulasi_K1_K2_K3.xlsx"}


@router.get("/prediksi")
def prediksi(request: Request, sku: str = "", q: str = "", db: Session = Depends(get_db)):
    model = MA.ambil(db)
    t = ST.tanggal_tercatat_terakhir(db)
    if model is None or t is None:
        return render(request, "prediksi.html", menu="prediksi", model=None, t=t, rows=[], hari=[], grafik=None)
    riw = ST.riwayat_pemakaian(db, model.items, t, 28)
    prak = model.prakiraan(riw, pd.Timestamp(t) + pd.Timedelta(days=1))
    hari = [d.date() for d in prak.index]
    bahan = {b.sku: b for b in db.query(Bahan).filter(Bahan.sku.in_(model.items)).all()}
    rows = []
    for s in model.items:
        b = bahan.get(s)
        if b is None or not b.aktif:
            continue
        if q and q.lower() not in b.nama.lower() and q.lower() not in s.lower():
            continue
        v = prak[s].values
        rows.append({"b": b, "nilai": v, "total": float(v.sum()), "sigma": model.sigma_e.get(s, 0.0),
                     "rata28": float(riw[s].mean())})
    rows.sort(key=lambda r: r["b"].nama)
    pilih = sku if sku in model.items else (rows[0]["b"].sku if rows else None)
    grafik = None
    if pilih:
        a = riw[pilih]
        p = prak[pilih]
        sg = model.sigma_e.get(pilih, 0.0)
        grafik = {"sku": pilih, "nama": bahan[pilih].nama, "satuan": bahan[pilih].satuan,
                  "label": [str(d.date()) for d in a.index] + [str(d) for d in hari],
                  "aktual": [round(float(x), 2) for x in a.values] + [None] * len(hari),
                  "prediksi": [None] * (len(a) - 1) + [round(float(a.values[-1]), 2)] + [round(float(x), 2) for x in p],
                  "atas": [None] * len(a) + [round(float(x + C.Z_LAYANAN * sg), 2) for x in p],
                  "bawah": [None] * len(a) + [round(max(float(x - C.Z_LAYANAN * sg), 0), 2) for x in p]}
    kurang = ST.hari_belum_tercatat(db, t, 7)
    return render(request, "prediksi.html", menu="prediksi", model=model, t=t, rows=rows, hari=hari, grafik=grafik,
                  q=q, pilih=pilih, kurang=kurang)


@lru_cache(maxsize=8)
def _baca_excel(path: str, sheet: str, mtime: float) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet, engine="openpyxl")


def _sheet(model, nama, sheet):
    f = Path(model.folder) / LAPORAN[nama]
    if not f.exists():
        return None
    return _baca_excel(str(f), sheet, f.stat().st_mtime)


@router.get("/evaluasi")
def evaluasi(request: Request, urut: str = "nama", db: Session = Depends(get_db)):
    model = MA.ambil(db)
    ev = model.evaluasi() if model else None
    per = None
    if model is not None:
        df = _sheet(model, "evaluasi", "Per Bahan (Uji)")
        if df is not None:
            df = df.rename(columns={df.columns[0]: "sku"})
            rata = df["rata_pemakaian"].where(df["rata_pemakaian"] > 0)
            df["nrmse_xgb"] = df["RMSE_xgboost"] / rata
            df["nrmse_ma7"] = df["RMSE_ma_7"] / rata
            df["menang"] = df["RMSE_xgboost"] < df["RMSE_ma_7"]
            per = bersih(df.to_dict(orient="records"))
            kunci = {"nama": lambda r: str(r.get("nama")),
                     "selisih": lambda r: (r["nrmse_xgb"] or 0) - (r["nrmse_ma7"] or 0),
                     "nrmse": lambda r: r["nrmse_xgb"] if r["nrmse_xgb"] is not None else 1e9}
            per.sort(key=kunci.get(urut, kunci["nama"]))
    return render(request, "evaluasi.html", menu="evaluasi", ev=ev, per=per, model=model, urut=urut)


@router.get("/simulasi")
def simulasi(request: Request, kelompok: str = "utama", db: Session = Depends(get_db)):
    model = MA.ambil(db)
    ev = model.evaluasi() if model else None
    per = []
    if ev:
        per = [r for r in ev["per_bahan"] if kelompok == "semua" or r.get("utama")]
        per.sort(key=lambda r: -(r.get("K1_TC") or 0))
    return render(request, "simulasi.html", menu="simulasi", ev=ev, per=per, kelompok=kelompok, model=model)


@lru_cache(maxsize=4)
def _muat_rincian(folder: str, mtime: float):
    return RC.muat(folder)


def _rincian(model):
    f = Path(model.folder) / RC.BERKAS
    if not f.exists():
        return None
    return _muat_rincian(str(model.folder), f.stat().st_mtime)


def _pilih_awal(nilai: float, pilihan: list, bawaan: float) -> float:
    for a in pilihan:
        if abs(a - nilai) < 1e-6:
            return a
    return bawaan if bawaan in pilihan else (pilihan[0] if pilihan else bawaan)


def _bagian_rincian(bag: dict, sku: str, varian: tuple, awal: float, seed: int, tampil: str, bawaan_awal: float):
    """Catatan harian satu run per kebijakan, totalnya, dan data grafik sisa stok untuk satu bahan."""
    b = bag["skus"].index(sku)
    pil = RC.pilihan_run(bag, varian[0])
    awal = _pilih_awal(awal, pil["awal"], bawaan_awal)
    seeds = RC.pilihan_run(bag, "K3")["seed"]
    seed = seed if seed in seeds else (seeds[0] if seeds else 0)
    hari = {v: RC.harian_run(bag, v, b, awal, seed) for v in varian}
    hari = {v: df for v, df in hari.items() if df is not None}
    tampil = tampil if tampil in hari else next(iter(hari), None)
    d_bar = float(bag["par"]["d_bar"][b])
    label_awal = []
    for a in pil["awal"]:
        if a == SIM.STOK_AWAL_TAKSIRAN:
            label_awal.append((a, f"Taksiran stok awal aktual ({angka_pas(float(bag['stok_taksiran'][b]))})"))
        else:
            label_awal.append((a, f"{angka(a, 1)} × rata-rata pemakaian ({angka_pas(a * d_bar)})"))
    return {
        "awal": awal, "seed": seed, "seeds": seeds, "label_awal": label_awal, "tampil": tampil,
        "ringkas": {v: RC.ringkas_run(df) for v, df in hari.items()},
        "tabel": bersih(hari[tampil].to_dict(orient="records")) if tampil else [],
        "grafik": {"label": [str(t) for t in bag["tanggal"]], "pemakaian": [float(x) for x in bag["d"][b]],
                   **{v: [round(float(x), 2) for x in df["sisa_akhir"]] for v, df in hari.items()}},
        "par": {k: float(v[b]) for k, v in bag["par"].items()},
    }


def _bilangan(teks: str, bawaan: float) -> float:
    try:
        v = float(str(teks).replace(",", "."))
    except ValueError:
        return bawaan
    return v if math.isfinite(v) else bawaan


@router.get("/simulasi/bahan/{sku}")
def simulasi_bahan(request: Request, sku: str, awal: str = "", seed: str = "", tampil: str = "K3",
                   awal_aktual: str = "", tampil_aktual: str = "K1A", db: Session = Depends(get_db)):
    """Rincian simulasi satu bahan: asal setiap komponen biaya, neraca barang, dan sisa stok setiap hari.
    awal = tingkat stok awal run yang ditampilkan (kelipatan rata-rata pemakaian; -1 = taksiran stok awal aktual),
    seed = seed K3 (mulai 1), tampil = kebijakan pada tabel catatan harian."""
    awal = _bilangan(awal, RC.AWAL_CONTOH)
    awal_aktual = _bilangan(awal_aktual, SIM.STOK_AWAL_TAKSIRAN)
    seed = int(_bilangan(seed, 1))
    model = MA.ambil(db)
    ev = model.evaluasi() if model else None
    if not ev:
        return ke("/simulasi")
    baris = next((r for r in ev["per_bahan"] if r["sku"] == sku), None)
    if baris is None:
        flash(request, "Bahan ini tidak ikut simulasi model aktif.", "galat")
        return ke("/simulasi")
    ak = ev.get("aktual") or {}
    baris_a = next((r for r in ak.get("per_bahan", []) if r["sku"] == sku), None)
    R = _rincian(model)
    uji = aktual = None
    if R is not None and sku in R["uji"]["skus"]:
        uji = _bagian_rincian(R["uji"], sku, RC.VARIAN_UJI, awal, seed - 1, tampil, RC.AWAL_CONTOH)
        if R["aktual"] and sku in R["aktual"]["skus"]:
            aktual = _bagian_rincian(R["aktual"], sku, RC.VARIAN_AKTUAL, awal_aktual, seed - 1, tampil_aktual,
                                     SIM.STOK_AWAL_TAKSIRAN)
    bahan = db.query(Bahan).filter(Bahan.sku == sku).first()
    return render(request, "simulasi_bahan.html", menu="simulasi", ev=ev, model=model, sku=sku, baris=baris,
                  baris_a=baris_a, bahan=bahan, uji=uji, aktual=aktual, nama_varian=RC.NAMA_VARIAN,
                  ada_rincian=R is not None)


@router.get("/laporan/{run_id}/{nama}")
def unduh_laporan(run_id: int, nama: str, db: Session = Depends(get_db)):
    run = db.get(ModelRun, run_id)
    if run is None or nama not in LAPORAN:
        return ke("/simulasi")
    f = MA.folder_run(run) / LAPORAN[nama]
    if not f.exists():
        return ke("/simulasi")
    return FileResponse(f, filename=f"{f.stem}_run{run_id}.xlsx")


@router.get("/pelatihan")
def pelatihan(request: Request, db: Session = Depends(get_db)):
    runs = db.query(ModelRun).order_by(ModelRun.id.desc()).limit(30).all()
    berjalan = PL.sedang_berjalan(db)
    t = ST.tanggal_tercatat_terakhir(db)
    aktif = next((r for r in runs if r.aktif), None)
    data_baru = (t - aktif.data_sampai).days if (aktif and t and aktif.data_sampai) else None
    return render(request, "pelatihan.html", menu="pelatihan", runs=runs, berjalan=berjalan, t=t, aktif=aktif,
                  data_baru=data_baru)


@router.post("/pelatihan/mulai")
def mulai_pelatihan(request: Request, jenis: str = Form("lengkap"), db: Session = Depends(get_db),
                    p=Depends(admin_saja)):
    try:
        run = PL.mulai(db, p.username, "cepat" if jenis == "cepat" else "lengkap")
    except RuntimeError as e:
        flash(request, str(e), "galat")
        return ke("/pelatihan")
    flash(request, f"Pelatihan #{run.id} dimulai di latar belakang. Halaman ini memperbarui log secara otomatis.")
    return ke("/pelatihan")


@router.get("/pelatihan/{rid}/status")
def status_pelatihan(rid: int, db: Session = Depends(get_db)):
    run = db.get(ModelRun, rid)
    if run is None:
        return JSONResponse({"status": "tidak ada"}, status_code=404)
    baris = (run.log or "").splitlines()
    return {"status": run.status, "log": "\n".join(baris[-40:]), "aktif": run.aktif}


@router.post("/pelatihan/{rid}/aktifkan")
def aktifkan(request: Request, rid: int, db: Session = Depends(get_db), p=Depends(admin_saja)):
    try:
        PL.aktifkan(db, rid)
        flash(request, f"Model #{rid} sekarang aktif. Hitung ulang rekomendasi agar memakai model ini.")
    except ValueError as e:
        flash(request, str(e), "galat")
    return ke("/pelatihan")
