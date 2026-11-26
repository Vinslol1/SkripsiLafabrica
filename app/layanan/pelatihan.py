"""Pelatihan ulang XGBoost + Q-Learning dari data di basis data, berjalan di latar belakang.

lengkap : grid search XGBoost, tuning alpha/gamma Q-Learning, uji K2/K3/K4 dengan beberapa seed (beberapa menit).
cepat   : hiperparameter XGBoost dan Q-Learning dari model aktif, satu seed pengujian.
Model baru langsung menjadi model aktif bila pelatihan berhasil.
"""
import json
import threading
import traceback
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

import config as C
from app.db import SesiLokal
from app.layanan import catatan_manual as CM
from app.layanan import model_aktif as MA
from app.layanan import pengaturan as PG
from app.layanan import stok as ST
from app.models import Bahan, ModelRun

_kunci = threading.Lock()


def master_dari_db(db: Session) -> pd.DataFrame:
    rows = []
    for b in db.query(Bahan).filter(Bahan.aktif.is_(True)).all():
        rows.append({"sku": b.sku, "nama": b.nama, "kategori": b.kategori, "satuan": b.satuan, "monitor": b.monitor,
                     "kemasan_isi": b.kemasan_isi, "harga_satuan": b.harga_satuan, "masa_simpan": b.masa_simpan,
                     "maks_kelipatan": b.maks_kelipatan if b.maks_kelipatan else float("nan"),
                     "biaya_kehabisan": b.biaya_kehabisan})
    return pd.DataFrame(rows)


def sedang_berjalan(db: Session) -> ModelRun | None:
    return db.query(ModelRun).filter(ModelRun.status == "berjalan").first()


def mulai(db: Session, oleh: str, jenis: str = "lengkap") -> ModelRun:
    with _kunci:
        if sedang_berjalan(db):
            raise RuntimeError("Pelatihan lain masih berjalan.")
        run = ModelRun(status="berjalan", jenis=jenis, dibuat_oleh=oleh, mulai=datetime.now())
        db.add(run)
        db.commit()
    threading.Thread(target=_kerja, args=(run.id, jenis), daemon=True).start()
    return run


def _kerja(run_id: int, jenis: str):
    from app.seed import ringkasan_run
    from ml import pipeline as P
    db = SesiLokal()
    run = db.get(ModelRun, run_id)
    baris = []

    def log(msg):
        baris.append(f"[{datetime.now():%H:%M:%S}] {msg}")
        run.log = "\n".join(baris)
        db.commit()

    try:
        cfg = PG.semua(db)
        long = ST.tabel_panjang_stok_keluar(db)
        if long.empty:
            raise RuntimeError("Belum ada data stok keluar.")
        master = master_dari_db(db)
        lengkap = jenis == "lengkap"
        aktif = MA.ambil(db)
        best = None
        alpha_gamma = None
        if not (lengkap and cfg["xgb_grid_search"]):
            best = aktif.meta["best_params"] if aktif else C.MANUAL_PARAMS
        if not lengkap and aktif:
            alpha_gamma = aktif.meta.get("ql_params")
        folder = C.FOLDER_MODEL / f"run_{run_id}"
        biaya = {"biaya_pesan": float(cfg["biaya_pesan"]), "biaya_simpan_persen": float(cfg["biaya_simpan_persen"])}
        log(f"Pelatihan {jenis}: {long['Tanggal'].nunique()} hari data, {master.shape[0]} bahan")
        P.jalankan(long, master, biaya=biaya, tuning=lengkap and bool(cfg["ql_tuning"]),
                   n_seed=int(cfg["ql_seed"]) if lengkap else 1, n_episode=int(cfg["ql_episode"]), log=log,
                   grid_search=best is None, best_params=best, folder_artefak=folder, ql_params=alpha_gamma,
                   masuk=CM.data_k1_aktual(CM.dari_db(db)))
        MA.daftarkan_run(db, run, folder)
        m = json.loads((MA.folder_run(run) / "xgb_meta.json").read_text(encoding="utf-8"))
        ev = json.loads((MA.folder_run(run) / "evaluasi.json").read_text(encoding="utf-8"))
        run.data_mulai = pd.Timestamp(m["data_mulai"]).date()
        run.data_sampai = pd.Timestamp(m["data_sampai"]).date()
        run.ringkasan = ringkasan_run(ev)
        run.status = "selesai"
        run.selesai = datetime.now()
        db.query(ModelRun).filter(ModelRun.id != run.id).update({ModelRun.aktif: False})
        run.aktif = True
        log("Model baru aktif.")
        MA.lupakan()
    except Exception as e:  # noqa: BLE001 - kesalahan apa pun dicatat di log pelatihan
        run.status = "gagal"
        run.selesai = datetime.now()
        log(f"Gagal: {e}\n{traceback.format_exc()}")
    finally:
        db.commit()
        db.close()


def aktifkan(db: Session, run_id: int):
    run = db.get(ModelRun, run_id)
    if run is None or run.status != "selesai":
        raise ValueError("Model belum selesai dilatih.")
    db.query(ModelRun).update({ModelRun.aktif: False})
    run.aktif = True
    db.commit()
    MA.lupakan()
