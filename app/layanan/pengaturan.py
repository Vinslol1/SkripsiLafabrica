"""Pengaturan yang bisa diubah dari aplikasi (nilai di basis data mengalahkan config.py)."""
import json

from sqlalchemy.orm import Session

import config as C
from app.models import Pengaturan

BAWAAN = {
    "nama_outlet": C.NAMA_OUTLET,
    "biaya_pesan": C.BIAYA_PESAN,
    "biaya_simpan_persen": C.BIAYA_SIMPAN_PERSEN,
    "ql_episode": C.QL_EPISODE,
    "ql_seed": len(C.SIM_SEED),
    "ql_tuning": True,
    "xgb_grid_search": True,
}

LABEL = {
    "nama_outlet": "Nama outlet",
    "biaya_pesan": "Biaya per pesanan satu bahan, c_o (Rp)",
    "biaya_simpan_persen": "Biaya simpan per hari, c_h (% harga beli)",
    "ql_episode": "Jumlah episode pelatihan Q-Learning",
    "ql_seed": "Jumlah seed pengujian K4",
    "ql_tuning": "Pilih alpha dan gamma pada periode validasi",
    "xgb_grid_search": "Grid search hiperparameter XGBoost",
}


def semua(db: Session) -> dict:
    out = dict(BAWAAN)
    for p in db.query(Pengaturan).all():
        try:
            out[p.kunci] = json.loads(p.nilai)
        except json.JSONDecodeError:
            out[p.kunci] = p.nilai
    return out


def simpan(db: Session, nilai: dict):
    for k, v in nilai.items():
        p = db.get(Pengaturan, k)
        if p is None:
            db.add(Pengaturan(kunci=k, nilai=json.dumps(v)))
        else:
            p.nilai = json.dumps(v)
    db.commit()
