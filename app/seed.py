"""Isi awal basis data dari folder data_awal dan artefak pelatihan awal.

Dijalankan otomatis oleh run.py setiap kali aplikasi dimulai. Bila basis data masih kosong, diisi:
  - pengguna admin (kata sandi wajib diganti),
  - data master bahan baku (ekspor majoo + estimasi harga/kemasan/masa simpan, ditandai sebagai asumsi),
  - stok keluar harian sejak Juli 2026 (file Stok_Keluar_Harian_Bahan_Baku.xlsx),
  - catatan manual order dan barang masuk cafe (data_awal/catatan_manual/*.txt) untuk K1 aktual,
  - model hasil pelatihan awal (artefak/ dan laporan/) sebagai model aktif.

Bila basis data berasal dari versi sebelumnya, data bawaan yang lebih baru ditambahkan tanpa mengubah data yang
sudah ada (lengkapi_dari_data_awal): hari stok keluar yang belum tercatat, hari catatan yang belum ada, dan model
bawaan bila datanya lebih baru daripada semua model yang ada (atau datanya sama dengan model bawaan yang sedang aktif
tetapi berkasnya lebih baru, mis. kini dengan rincian harian simulasi). Nilai bahan yang masih berupa perkiraan dari data
(isi kemasan, harga, biaya kehabisan yang belum dikonfirmasi) dihitung ulang seperti pada instalasi baru.
"""
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import insert, inspect, text

import config as C
from app.auth import hash_sandi
from app.db import Base, SesiLokal, engine
from app.layanan import model_aktif as MA
from app.layanan import pengaturan as PG
from app.models import Bahan, CatatanBarang, ModelRun, PencatatanHarian, Pengguna, SatuanBahan, StokKeluar

BERKAS_MODEL = ["xgb_model.json", "xgb_meta.json", "qtable.npz", "qtable_meta.json", "evaluasi.json"]
BERKAS_MODEL_OPSIONAL = ["simulasi_harian.npz"]     # rincian harian simulasi; model lama tidak memilikinya
BERKAS_LAPORAN = ["evaluasi_xgboost.xlsx", "simulasi_K1_K2_K3.xlsx"]
# Pengaturan internal: sidik berkas data_awal yang sudah dimasukkan, agar pemeriksaan saat mulai cukup sekali.
KUNCI_DATA_AWAL = "data_awal_terpakai"
# Tanda asumsi pada bahan -> kolom yang dihitung dari data bawaan (ml.master.susun_master)
NILAI_SEMENTARA = {
    "kemasan": ("kemasan_nama", "kemasan_isi", "sumber_kemasan"),
    "harga": ("harga_satuan", "sumber_harga"),
    "biaya_kehabisan": ("biaya_kehabisan", "sumber_biaya_kehabisan"),
}


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
    _catat_penanda(db, master=_sidik(*_berkas_master()))
    log(f"Data master: {db.query(Bahan).count()} bahan baku")


def _berkas_master() -> list:
    return [f for f in (C.FILE_EKSPOR_BAHAN, C.FILE_RESEP, C.FILE_STOK_KELUAR) if f.exists()]


def _sidik(*berkas) -> str:
    h = hashlib.sha1()
    for f in berkas:
        h.update(Path(f).name.encode("utf-8"))
        h.update(Path(f).read_bytes())
    return h.hexdigest()


def _penanda(db) -> dict:
    v = PG.semua(db).get(KUNCI_DATA_AWAL)
    return v if isinstance(v, dict) else {}


def _catat_penanda(db, **isi):
    p = _penanda(db)
    p.update(isi)
    PG.simpan(db, {KUNCI_DATA_AWAL: p})


def _stok_keluar_awal() -> pd.DataFrame:
    long = pd.read_excel(C.FILE_STOK_KELUAR, sheet_name="Stok Keluar (Long)", engine="openpyxl")
    long["Tanggal"] = pd.to_datetime(long["Tanggal"]).dt.date
    return long.groupby(["Tanggal", "SKU Bahan"])["Jumlah Keluar"].sum().reset_index()


def _tambah_hari_stok_keluar(db, g: pd.DataFrame, hari: list, sumber: str) -> int:
    ids = {b.sku: b.id for b in db.query(Bahan).all()}
    pilih = set(hari)
    rows = [{"bahan_id": ids[s], "tanggal": t, "jumlah": float(q)} for t, s, q in g.itertuples(index=False)
            if s in ids and t in pilih]
    if rows:
        db.execute(insert(StokKeluar), rows)
    for t in sorted(pilih):
        db.add(PencatatanHarian(tanggal=t, status="tercatat", sumber=sumber))
    db.commit()
    return len(rows)


def isi_stok_keluar(db, log=print):
    if db.query(StokKeluar).count():
        return
    g = _stok_keluar_awal()
    n = _tambah_hari_stok_keluar(db, g, sorted(g["Tanggal"].unique()), "impor awal")
    _catat_penanda(db, stok_keluar=_sidik(C.FILE_STOK_KELUAR))
    log(f"Stok keluar: {n} baris, {g['Tanggal'].nunique()} hari ({g['Tanggal'].min()} s.d. {g['Tanggal'].max()})")


def _berkas_catatan() -> list:
    return sorted(C.FOLDER_CATATAN.glob("*.txt")) if C.FOLDER_CATATAN.exists() else []


def isi_catatan_manual(db, log=print):
    """Catatan WhatsApp order dan barang masuk di data_awal/catatan_manual, dirapikan lalu disimpan. Setelah tabel
    berisi, catatan baru diimpor dari menu Catatan Barang Masuk (atau ditambahkan oleh lengkapi_catatan)."""
    if db.query(CatatanBarang).count() or not db.query(Bahan).count():
        return
    from app.layanan import catatan_manual as CM
    files = _berkas_catatan()
    if not files:
        return
    df, _ = CM.dari_folder(C.FOLDER_CATATAN, CM.Master.dari_db(db))
    h = CM.simpan_ke_db(db, df, sumber=", ".join(f.name for f in files), oleh="sistem")
    _catat_penanda(db, catatan=_sidik(*files))
    if h["hari_masuk"]:
        log(f"Catatan barang masuk: {h['masuk']} baris ({h['hari_masuk'][0]} s.d. {h['hari_masuk'][-1]}), "
            f"{h['order']} baris order")


def _artefak_lengkap() -> bool:
    return all((C.ARTEFAK / f).exists() for f in BERKAS_MODEL)


def _berkas_artefak(folder) -> list:
    folder = Path(folder)
    return [folder / f for f in BERKAS_MODEL + BERKAS_MODEL_OPSIONAL if (folder / f).exists()]


def _sidik_artefak(folder) -> str:
    return _sidik(*_berkas_artefak(folder))


def _daftarkan_artefak(db, keterangan: str, aktif: bool) -> ModelRun:
    """Salin artefak/ (dan laporan/) ke folder model baru, lalu daftarkan sebagai run selesai."""
    run = ModelRun(status="selesai", jenis="lengkap", aktif=aktif, dibuat_oleh="sistem", mulai=datetime.now())
    db.add(run)
    db.flush()
    tujuan = C.FOLDER_MODEL / f"run_{run.id}"
    tujuan.mkdir(parents=True, exist_ok=True)
    for f in _berkas_artefak(C.ARTEFAK):
        shutil.copy2(f, tujuan / f.name)
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
    run.log = keterangan
    MA.daftarkan_run(db, run, tujuan)
    return run


def isi_model_awal(db, log=print):
    if db.query(ModelRun).count():
        return
    if not _artefak_lengkap():
        log("Artefak pelatihan awal belum ada; jalankan pelatihan dari menu Pelatihan Ulang.")
        return
    run = _daftarkan_artefak(db, "Model hasil pelatihan awal (python -m ml.pipeline --tuning).", aktif=True)
    _catat_penanda(db, model=_sidik_artefak(C.ARTEFAK))
    log(f"Model awal terdaftar (data s.d. {run.data_sampai})")


# ------------------------------------------------------------- basis data dari versi aplikasi sebelumnya
def lengkapi_nilai_sementara(db, log=print):
    """Hitung ulang nilai bahan yang masih berupa perkiraan dari data (isi kemasan, harga, dan biaya kehabisan yang
    belum dikonfirmasi), sama seperti pada instalasi baru. Nilai yang sudah diisi atau dikonfirmasi tidak diubah."""
    berkas = _berkas_master()
    if not db.query(Bahan).count() or len(berkas) < 3:
        return
    sidik = _sidik(*berkas)
    if _penanda(db).get("master") == sidik:
        return
    from ml.master import susun_master
    baru = {r["sku"]: r for r in susun_master(log=lambda *_: None).to_dict(orient="records")}
    n = 0
    for b in db.query(Bahan).all():
        r = baru.get(b.sku)
        if r is None:
            continue
        tanda = set(b.daftar_asumsi)
        tanda_baru = {a for a in (r["asumsi"] or "").split(",") if a}
        ubah = False
        for t, kolom in NILAI_SEMENTARA.items():
            if t not in tanda:
                continue
            for k in kolom:
                v = float(r[k]) if k in ("kemasan_isi", "harga_satuan", "biaya_kehabisan") else r[k]
                if getattr(b, k) != v:
                    setattr(b, k, v)
                    ubah = True
            if t not in tanda_baru:            # nilai baru bukan perkiraan lagi (mis. ada konversi di majoo)
                tanda.discard(t)
                ubah = True
        if ubah:
            b.asumsi = ",".join(a for a in b.daftar_asumsi if a in tanda)
            n += 1
    db.commit()
    if n:
        log(f"Nilai sementara bahan dihitung ulang dari data bawaan yang lebih baru: {n} bahan. Nilai yang sudah "
            f"dikonfirmasi tidak diubah.")
    _catat_penanda(db, master=sidik)


def lengkapi_stok_keluar(db, log=print):
    """Tambahkan hari di file stok keluar bawaan yang belum tercatat. Hari yang sudah tercatat (termasuk yang
    ditandai tutup atau diisi manual) tidak diubah."""
    if not db.query(StokKeluar).count() or not C.FILE_STOK_KELUAR.exists():
        return
    sidik = _sidik(C.FILE_STOK_KELUAR)
    if _penanda(db).get("stok_keluar") == sidik:
        return
    g = _stok_keluar_awal()
    sudah = {t for (t,) in db.query(PencatatanHarian.tanggal).all()}
    hari = sorted(set(g["Tanggal"]) - sudah)
    if hari:
        n = _tambah_hari_stok_keluar(db, g, hari, "data_awal versi baru")
        log(f"Stok keluar dari data bawaan yang lebih baru: {len(hari)} hari ditambahkan ({hari[0]} s.d. "
            f"{hari[-1]}, {n} baris). Hari yang sudah tercatat tidak diubah.")
    _catat_penanda(db, stok_keluar=sidik)


def lengkapi_catatan(db, log=print):
    """Tambahkan catatan order/barang masuk bawaan untuk (jenis, tanggal) yang belum ada di basis data. Hari yang
    sudah ada (termasuk yang dikoreksi lewat menu Catatan Barang Masuk) tidak diubah."""
    files = _berkas_catatan()
    if not files or not db.query(CatatanBarang).count():
        return
    sidik = _sidik(*files)
    if _penanda(db).get("catatan") == sidik:
        return
    from app.layanan import catatan_manual as CM
    df, _ = CM.dari_folder(C.FOLDER_CATATAN, CM.Master.dari_db(db))
    ada = {(j, t) for j, t in db.query(CatatanBarang.jenis, CatatanBarang.tanggal).distinct()}
    if not df.empty:
        kunci = zip(df["jenis"], pd.to_datetime(df["tanggal"]).dt.date)
        baru = df[[k not in ada for k in kunci]]
        if not baru.empty:
            h = CM.simpan_ke_db(db, baru, sumber=", ".join(f.name for f in files), oleh="sistem")
            hari = sorted({pd.Timestamp(t).date() for t in baru["tanggal"]})
            log(f"Catatan bawaan yang lebih baru: {h['masuk']} baris barang masuk dan {h['order']} baris order "
                f"ditambahkan ({hari[0]} s.d. {hari[-1]}).")
    _catat_penanda(db, catatan=sidik)


def lengkapi_model(db, log=print):
    """Daftarkan model bawaan (artefak/) sebagai model aktif bila:
      - datanya lebih baru daripada semua model yang ada, atau
      - datanya sama dengan model aktif yang juga model bawaan, tetapi berkasnya berbeda (versi aplikasi baru
        membawa model bawaan yang dilatih ulang dengan data yang sama, mis. kini dengan rincian harian simulasi).
    Model hasil Pelatihan Ulang pengguna dengan data yang sama atau lebih baru tidak diganti. Model sebelumnya
    tetap ada di riwayat dan bisa diaktifkan kembali dari menu Pelatihan Ulang. Setiap versi artefak diperiksa
    sekali (penanda sidik di pengaturan)."""
    if not db.query(ModelRun).count() or not _artefak_lengkap():
        return
    sidik = _sidik_artefak(C.ARTEFAK)
    if _penanda(db).get("model") == sidik:
        return
    meta = json.loads((C.ARTEFAK / "xgb_meta.json").read_text(encoding="utf-8"))
    sampai = pd.Timestamp(meta["data_sampai"]).date()
    selesai = db.query(ModelRun).filter(ModelRun.status == "selesai").all()
    if any(r.data_sampai == sampai and r.folder and _sidik_artefak(MA.folder_run(r)) == sidik for r in selesai):
        _catat_penanda(db, model=sidik)          # sudah terdaftar (basis data dari versi tanpa penanda model)
        return
    terakhir = max((r.data_sampai for r in selesai if r.data_sampai), default=None)
    aktif = next((r for r in selesai if r.aktif), None)
    lebih_baru = terakhir is None or sampai > terakhir
    bawaan_sama = (aktif is not None and aktif.dibuat_oleh == "sistem" and aktif.data_sampai == sampai
                   and sampai >= terakhir)
    if lebih_baru or bawaan_sama:
        run = _daftarkan_artefak(db, "Model bawaan versi baru (artefak/), didaftarkan otomatis saat aplikasi "
                                     "diperbarui.", aktif=False)
        db.query(ModelRun).filter(ModelRun.id != run.id).update({ModelRun.aktif: False})
        run.aktif = True
        db.commit()
        MA.lupakan()
        alasan = "yang lebih baru" if lebih_baru else "versi baru dengan data yang sama"
        log(f"Model bawaan {alasan} (data s.d. {sampai}) didaftarkan dan diaktifkan. Model sebelumnya tetap ada di "
            f"riwayat Pelatihan Ulang.")
    _catat_penanda(db, model=sidik)


def lengkapi_dari_data_awal(db, log=print):
    """Basis data dari versi sebelumnya: tambahkan data bawaan yang lebih baru tanpa mengubah data yang ada."""
    if C.DEMO:
        # riwayat demo disusun dari data saat basis data demo dibuat; jangan ditambal
        if C.FILE_STOK_KELUAR.exists() and _penanda(db).get("stok_keluar") != _sidik(C.FILE_STOK_KELUAR):
            log("Data bawaan di data_awal lebih baru daripada data demo ini. Jalankan jalankan_demo.bat --ulang-demo "
                "untuk membuat ulang data demo.")
        return
    lengkapi_stok_keluar(db, log)
    lengkapi_catatan(db, log)
    lengkapi_model(db, log)


def ringkasan_run(ev: dict) -> dict:
    out = {"best_params": ev.get("best_params"), "ql_params": ev.get("ql_params"), "periode_uji": ev.get("periode_uji"),
           "xgb_menang_ma7": ev.get("xgb_menang_ma7"), "xgb_n_bahan": ev.get("xgb_n_bahan")}
    for kel in ("utama", "semua"):
        t = ev.get("kebijakan", {}).get(kel, {}).get("total", {})
        out[f"TC_{kel}"] = {v: t[v].get("TC_mean") for v in t}
    out["n_utama"] = ev.get("kebijakan", {}).get("utama", {}).get("n_bahan")
    out["bahan_target"] = bool(ev.get("pemilihan"))        # model sejak praproses bahan target (ml/praproses.py)
    return out


def jalankan(log=print):
    buat_tabel()
    db = SesiLokal()
    try:
        isi_pengguna(db, log)
        isi_bahan(db, log)
        if not C.DEMO:
            lengkapi_nilai_sementara(db, log)    # sebelum catatan dirapikan, karena isi kemasan dipakai konversi
        isi_stok_keluar(db, log)
        isi_catatan_manual(db, log)
        isi_model_awal(db, log)
        lengkapi_dari_data_awal(db, log)
    finally:
        db.close()


if __name__ == "__main__":
    jalankan()
