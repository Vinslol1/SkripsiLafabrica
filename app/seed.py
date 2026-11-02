"""Isi awal basis data dari folder data_awal dan artefak pelatihan awal.

Dijalankan otomatis oleh run.py bila basis data masih kosong:
  - pengguna admin (kata sandi wajib diganti),
  - data master bahan baku (ekspor majoo + estimasi harga/kemasan/masa simpan, ditandai sebagai asumsi),
  - stok keluar harian Juli-Oktober 2026 (file Stok_Keluar_Harian_Bahan_Baku.xlsx),
  - catatan manual order dan barang masuk cafe (data_awal/catatan_manual/*.txt) untuk K1 aktual,
  - model hasil pelatihan awal (artefak/ dan laporan/) sebagai model aktif.
"""
import json
import shutil
from datetime import datetime

import pandas as pd
from sqlalchemy import insert, inspect, text

import config as C
from app.auth import hash_sandi
from app.db import Base, SesiLokal, engine
from app.layanan import model_aktif as MA
from app.models import Bahan, CatatanBarang, ModelRun, PencatatanHarian, Pengguna, SatuanBahan, StokKeluar

BERKAS_MODEL = ["xgb_model.json", "xgb_meta.json", "qtable.npz", "qtable_meta.json", "evaluasi.json"]
BERKAS_LAPORAN = ["evaluasi_xgboost.xlsx", "simulasi_K1_K2_K3.xlsx"]


def buat_tabel():
    Base.metadata.create_all(engine)
    _tambah_kolom_baru()


def _tambah_kolom_baru():
    """Tambahkan kolom yang belum ada pada basis data dari versi aplikasi sebelumnya (tanpa menghapus data)."""
    insp = inspect(engine)
    with engine.begin() as con:
        for tabel in Base.metadata.sorted_tables:
            if not insp.has_table(tabel.name):
                continue
            ada = {c["name"] for c in insp.get_columns(tabel.name)}
            for kol in tabel.columns:
                if kol.name not in ada:
                    tipe = kol.type.compile(dialect=engine.dialect)
                    con.execute(text(f"ALTER TABLE {tabel.name} ADD COLUMN {kol.name} {tipe}"))


def isi_pengguna(db, log=print):
    if db.query(Pengguna).count():
        return
    u, p = C.PENGGUNA_AWAL
    db.add(Pengguna(username=u, nama="Administrator", hash_sandi=hash_sandi(p), peran="admin", sandi_bawaan=True))
    db.commit()
    log(f"Pengguna awal dibuat: {u} / {p} (ganti kata sandi setelah masuk)")


def isi_bahan(db, log=print):
    if db.query(Bahan).count():
        return
    from ml.master import susun_master
    m = susun_master(log=log)
    for r in m.to_dict(orient="records"):
        lain = r.pop("satuan_lain") or []
        b = Bahan(sku=r["sku"], nama=r["nama"], kategori=r["kategori"], satuan=r["satuan"], monitor=bool(r["monitor"]),
                  stok_minimum=float(r["stok_minimum_majoo"] or 0), kemasan_nama=r["kemasan_nama"],
                  kemasan_isi=float(r["kemasan_isi"]), harga_satuan=float(r["harga_satuan"]),
                  masa_simpan=int(r["masa_simpan"]), lead_time=int(r["lead_time"]),
                  maks_kelipatan=None, biaya_kehabisan=float(r["biaya_kehabisan"]),
                  sumber_harga=r["sumber_harga"], sumber_kemasan=r["sumber_kemasan"],
                  sumber_biaya_kehabisan=r["sumber_biaya_kehabisan"], asumsi=r["asumsi"], catatan=r["catatan"] or "")
        nos = {u["no"] for u in lain}
        no_dasar = min(set(range(1, len(lain) + 2)) - nos)
        b.satuan_lain.append(SatuanBahan(no=no_dasar, satuan=r["satuan"], sku=r["sku"], konversi=1.0, dasar=True))
        for u in lain:
            b.satuan_lain.append(SatuanBahan(no=int(u["no"]), satuan=u["satuan"], sku=u["sku"],
                                             konversi=float(u.get("konv") or 1.0), dasar=False))
        db.add(b)
    db.commit()
    log(f"Data master: {db.query(Bahan).count()} bahan baku")


def isi_stok_keluar(db, log=print):
    if db.query(StokKeluar).count():
        return
    long = pd.read_excel(C.FILE_STOK_KELUAR, sheet_name="Stok Keluar (Long)", engine="openpyxl")
    long["Tanggal"] = pd.to_datetime(long["Tanggal"]).dt.date
    ids = {b.sku: b.id for b in db.query(Bahan).all()}
    g = long.groupby(["Tanggal", "SKU Bahan"])["Jumlah Keluar"].sum().reset_index()
    rows = [{"bahan_id": ids[s], "tanggal": t, "jumlah": float(q)} for t, s, q in g.itertuples(index=False)
            if s in ids]
    db.execute(insert(StokKeluar), rows)
    for t in sorted(g["Tanggal"].unique()):
        db.add(PencatatanHarian(tanggal=t, status="tercatat", sumber="impor awal"))
    db.commit()
    log(f"Stok keluar: {len(rows)} baris, {g['Tanggal'].nunique()} hari ({g['Tanggal'].min()} s.d. {g['Tanggal'].max()})")


def isi_catatan_manual(db, log=print):
    """Catatan WhatsApp order dan barang masuk di data_awal/catatan_manual, dirapikan lalu disimpan (sekali saja:
    setelah tabel berisi, catatan baru diimpor dari menu Catatan Barang Masuk)."""
    if db.query(CatatanBarang).count() or not db.query(Bahan).count():
        return
    from app.layanan import catatan_manual as CM
    files = sorted(C.FOLDER_CATATAN.glob("*.txt"))
    if not files:
        return
    df, _ = CM.dari_folder(C.FOLDER_CATATAN, CM.Master.dari_db(db))
    h = CM.simpan_ke_db(db, df, sumber=", ".join(f.name for f in files), oleh="sistem")
    if h["hari_masuk"]:
        log(f"Catatan barang masuk: {h['masuk']} baris ({h['hari_masuk'][0]} s.d. {h['hari_masuk'][-1]}), "
            f"{h['order']} baris order")


def isi_model_awal(db, log=print):
    if db.query(ModelRun).count():
        return
    if not all((C.ARTEFAK / f).exists() for f in BERKAS_MODEL):
        log("Artefak pelatihan awal belum ada; jalankan pelatihan dari menu Pelatihan Ulang.")
        return
    run = ModelRun(status="selesai", jenis="lengkap", aktif=True, dibuat_oleh="sistem", mulai=datetime.now())
    db.add(run)
    db.flush()
    tujuan = C.FOLDER_MODEL / f"run_{run.id}"
    tujuan.mkdir(parents=True, exist_ok=True)
    for f in BERKAS_MODEL:
        shutil.copy2(C.ARTEFAK / f, tujuan / f)
    for f in BERKAS_LAPORAN:
        if (C.LAPORAN / f).exists():
            shutil.copy2(C.LAPORAN / f, tujuan / f)
    meta = json.loads((tujuan / "xgb_meta.json").read_text(encoding="utf-8"))
    ev = json.loads((tujuan / "evaluasi.json").read_text(encoding="utf-8"))
    run.data_mulai = pd.Timestamp(meta["data_mulai"]).date()
    run.data_sampai = pd.Timestamp(meta["data_sampai"]).date()
    run.mulai = datetime.fromisoformat(meta["dibuat"])
    run.selesai = run.mulai
    run.ringkasan = ringkasan_run(ev)
    run.log = "Model hasil pelatihan awal (python -m ml.pipeline --tuning)."
    MA.daftarkan_run(db, run, tujuan)
    log(f"Model awal terdaftar (data s.d. {run.data_sampai})")


def ringkasan_run(ev: dict) -> dict:
    out = {"best_params": ev.get("best_params"), "ql_params": ev.get("ql_params"), "periode_uji": ev.get("periode_uji"),
           "xgb_menang_ma7": ev.get("xgb_menang_ma7"), "xgb_n_bahan": ev.get("xgb_n_bahan")}
    for kel in ("utama", "semua"):
        t = ev.get("kebijakan", {}).get(kel, {}).get("total", {})
        out[f"TC_{kel}"] = {v: t[v].get("TC_mean") for v in t}
    return out


def jalankan(log=print):
    buat_tabel()
    db = SesiLokal()
    try:
        isi_pengguna(db, log)
        isi_bahan(db, log)
        isi_stok_keluar(db, log)
        isi_catatan_manual(db, log)
        isi_model_awal(db, log)
    finally:
        db.close()


if __name__ == "__main__":
    jalankan()
