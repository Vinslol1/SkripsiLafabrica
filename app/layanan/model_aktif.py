"""Memuat model yang sedang aktif: berkas XGBoost dan Q-table setiap bahan dari basis data."""
import io
import json
import threading
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

import config as C
from app.models import ModelRun, QTabel
from ml.xgb import ModelXGB, prediksi_rekursif

_kunci = threading.Lock()
_cache = {"run_id": None, "model": None}


def ke_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, arr, allow_pickle=False)
    return buf.getvalue()


def dari_bytes(b: bytes) -> np.ndarray:
    return np.load(io.BytesIO(b), allow_pickle=False)


def folder_run(run: ModelRun) -> Path:
    f = Path(run.folder)
    return f if f.is_absolute() else C.BASE_DIR / f


class ModelAktif:
    def __init__(self, run: ModelRun, qtabel: list):
        self.run_id = run.id
        self.folder = folder_run(run)
        self.meta = json.loads((self.folder / "xgb_meta.json").read_text(encoding="utf-8"))
        self.items = list(self.meta["items"])
        self.skala = pd.Series(self.meta["skala"], dtype=float)
        self.sigma_e = {k: float(v) for k, v in self.meta["sigma_e"].items()}
        self.model = ModelXGB.muat(self.folder / "xgb_model.json")
        self.q = {}
        for r in qtabel:
            self.q[r.sku] = {"k": r.k, "m": r.m, "edges": r.edges, "Q": dari_bytes(r.q), "N": dari_bytes(r.n),
                             "d_bar": r.d_bar, "sigma_e": r.sigma_e,
                             "kap": float(r.kap) if r.kap is not None else float("inf"), "kap_manual": r.kap_manual}
        self.data_sampai = run.data_sampai

    def prakiraan(self, riwayat: pd.DataFrame, mulai: pd.Timestamp, horizon: int = C.HORIZON) -> pd.DataFrame:
        """Prediksi rekursif 7 hari untuk semua bahan model; riwayat = tabel lebar s.d. hari sebelum `mulai`."""
        riw = riwayat.reindex(columns=self.items).fillna(0.0)
        return prediksi_rekursif(self.model, self.items, riw, self.skala, mulai, horizon)

    def evaluasi(self) -> dict | None:
        f = self.folder / "evaluasi.json"
        if not f.exists():
            return None
        from app.web import bersih
        from ml.penamaan import seragamkan
        return bersih(seragamkan(json.loads(f.read_text(encoding="utf-8"))))


def ambil(db: Session) -> ModelAktif | None:
    run = db.query(ModelRun).filter(ModelRun.aktif.is_(True), ModelRun.status == "selesai") \
        .order_by(ModelRun.id.desc()).first()
    if run is None:
        return None
    with _kunci:
        if _cache["run_id"] != run.id:
            rows = db.query(QTabel).filter(QTabel.model_run_id == run.id).all()
            _cache["model"] = ModelAktif(run, rows)
            _cache["run_id"] = run.id
        return _cache["model"]


def lupakan():
    with _kunci:
        _cache["run_id"] = None
        _cache["model"] = None


def daftarkan_run(db: Session, run: ModelRun, folder: Path):
    """Simpan Q-table dari artefak pelatihan ke basis data (Q-table setiap bahan disimpan di basis data)."""
    z = np.load(folder / "qtable.npz", allow_pickle=False)
    meta = json.loads((folder / "qtable_meta.json").read_text(encoding="utf-8"))
    xmeta = json.loads((folder / "xgb_meta.json").read_text(encoding="utf-8"))
    db.query(QTabel).filter(QTabel.model_run_id == run.id).delete()
    for i, sku in enumerate(z["skus"].tolist()):
        mq = meta[sku]
        m = int(mq["m"])
        db.add(QTabel(model_run_id=run.id, sku=sku, k=float(mq["k"]), m=m, d_bar=float(mq["d_bar"]),
                      kap=float(mq["kap"]) if mq.get("kap") is not None else None,
                      kap_manual=bool(mq.get("kap_manual", False)),
                      sigma_e=float(xmeta["sigma_e"].get(sku, 0.0)), edges=mq["edges"],
                      q=ke_bytes(z["Q"][i, :, :m + 1].astype(np.float32)),
                      n=ke_bytes(z["N"][i, :, :m + 1].astype(np.int32))))
    try:
        run.folder = Path(folder).resolve().relative_to(C.BASE_DIR).as_posix()
    except ValueError:
        run.folder = str(folder)
    db.commit()
