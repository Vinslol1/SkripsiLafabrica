"""Memperbarui aplikasi: basis data dari versi sebelumnya dilengkapi data bawaan yang lebih baru saat dimulai,
tanpa mengubah data yang sudah ada."""
from datetime import timedelta

import pandas as pd
import pytest


def test_basis_data_versi_lama_dilengkapi_tanpa_mengubah_data_yang_ada(aplikasi, db):
    from sqlalchemy import func

    import config as C
    from app import seed
    from app.layanan import catatan_manual as CM
    from app.layanan import model_aktif as MA
    from app.layanan import pengaturan as PG
    from app.models import Bahan, CatatanBarang, ModelRun, PencatatanHarian, StokKeluar
    from ml.master import susun_master

    # tiru basis data versi lama: nilai sementara bahan dari data lama, dua hari stok keluar terakhir, order hari
    # terakhir, dan model terbaru belum ada
    master = {r["sku"]: r for r in susun_master(log=lambda *_: None).to_dict(orient="records")}
    tebak = db.query(Bahan).filter(Bahan.asumsi.like("%kemasan%")).order_by(Bahan.sku).first()
    tebak.kemasan_isi = master[tebak.sku]["kemasan_isi"] * 3          # perkiraan versi lama, belum dikonfirmasi
    pasti = db.query(Bahan).filter(Bahan.asumsi.like("%biaya_kehabisan%")).order_by(Bahan.sku.desc()).first()
    pasti.biaya_kehabisan = 4321.0                                    # diisi pengguna, tanda asumsinya hilang
    pasti.asumsi = ",".join(x for x in pasti.daftar_asumsi if x != "biaya_kehabisan")
    awal = seed._stok_keluar_awal()
    akhir = max(awal["Tanggal"])
    hilang = [akhir - timedelta(days=1), akhir]
    db.query(StokKeluar).filter(StokKeluar.tanggal.in_(hilang)).delete(synchronize_session=False)
    db.query(PencatatanHarian).filter(PencatatanHarian.tanggal.in_(hilang)).delete(synchronize_session=False)
    sk = db.query(StokKeluar).filter(StokKeluar.tanggal == akhir - timedelta(days=2)).first()
    sk.jumlah += 123.0                                  # diubah pengguna: tidak boleh ditimpa data bawaan
    dijaga = sk.jumlah

    cat, _ = CM.dari_folder(C.FOLDER_CATATAN, CM.Master.dari_db(db))
    tgl_cat = pd.to_datetime(cat["tanggal"]).dt.date
    order_akhir = max(tgl_cat[cat["jenis"] == "order"])
    n_order = int(((cat["jenis"] == "order") & (tgl_cat == order_akhir)).sum())
    db.query(CatatanBarang).filter(CatatanBarang.jenis == "order", CatatanBarang.tanggal == order_akhir) \
        .delete(synchronize_session=False)
    masuk = db.query(CatatanBarang).filter(CatatanBarang.jenis == "masuk").order_by(CatatanBarang.id).first()
    masuk.keterangan = "dikoreksi pengguna"

    run_lama = db.query(ModelRun).filter(ModelRun.aktif.is_(True)).one()
    run_lama.data_sampai = run_lama.data_sampai - timedelta(days=8)
    n_run = db.query(ModelRun).count()
    db.commit()
    PG.simpan(db, {seed.KUNCI_DATA_AWAL: {}})          # versi lama belum menyimpan penanda data_awal

    seed.jalankan(log=lambda *_: None)
    db.expire_all()

    assert db.get(Bahan, tebak.id).kemasan_isi == pytest.approx(master[tebak.sku]["kemasan_isi"])
    assert db.get(Bahan, pasti.id).biaya_kehabisan == 4321.0
    assert "biaya_kehabisan" not in db.get(Bahan, pasti.id).daftar_asumsi
    for t in hilang:
        assert db.get(PencatatanHarian, t).sumber == "data_awal versi baru"
        harap = awal.loc[awal["Tanggal"] == t, "Jumlah Keluar"].sum()
        dapat = db.query(func.sum(StokKeluar.jumlah)).filter(StokKeluar.tanggal == t).scalar()
        assert dapat == pytest.approx(harap)
    assert db.get(StokKeluar, sk.id).jumlah == pytest.approx(dijaga)
    assert db.query(CatatanBarang).filter(CatatanBarang.jenis == "order",
                                          CatatanBarang.tanggal == order_akhir).count() == n_order
    assert db.get(CatatanBarang, masuk.id).keterangan == "dikoreksi pengguna"
    runs = db.query(ModelRun).order_by(ModelRun.id).all()
    assert len(runs) == n_run + 1 and runs[-1].aktif and not db.get(ModelRun, run_lama.id).aktif
    assert MA.ambil(db).run_id == runs[-1].id

    # saat dimulai lagi penandanya sudah sama, jadi tidak ada yang ditambahkan dua kali
    seed.jalankan(log=lambda *_: None)
    db.expire_all()
    assert db.query(ModelRun).count() == n_run + 1
    assert db.query(StokKeluar).filter(StokKeluar.tanggal == akhir).count() == (awal["Tanggal"] == akhir).sum()


def test_model_bawaan_baru_dengan_data_sama_menggantikan_model_bawaan_lama(aplikasi, db):
    """Versi aplikasi baru membawa model bawaan yang dilatih ulang dengan data yang sama (mis. kini dengan rincian
    harian): model bawaan aktif yang lama diganti, tetapi model hasil Pelatihan Ulang pengguna tidak."""
    import shutil

    import config as C
    from app import seed
    from app.layanan import model_aktif as MA
    from app.layanan import pengaturan as PG
    from app.models import ModelRun
    from ml import rincian as RC

    def lupakan_penanda():
        PG.simpan(db, {seed.KUNCI_DATA_AWAL: {**seed._penanda(db), "model": "versi-lama"}})

    aktif = db.query(ModelRun).filter(ModelRun.aktif.is_(True)).one()
    assert aktif.dibuat_oleh == "sistem"
    (MA.folder_run(aktif) / RC.BERKAS).unlink(missing_ok=True)     # model bawaan versi lama: tanpa rincian harian
    n_run = db.query(ModelRun).count()
    lupakan_penanda()
    seed.jalankan(log=lambda *_: None)
    db.expire_all()
    baru = db.query(ModelRun).filter(ModelRun.aktif.is_(True)).one()
    assert baru.id != aktif.id and db.query(ModelRun).count() == n_run + 1
    assert baru.data_sampai == db.get(ModelRun, aktif.id).data_sampai
    assert (MA.folder_run(baru) / RC.BERKAS).exists() and MA.ambil(db).run_id == baru.id

    seed.jalankan(log=lambda *_: None)                              # penanda sudah sama: tidak didaftarkan lagi
    assert db.query(ModelRun).count() == n_run + 1

    baru.dibuat_oleh = "admin"                                      # model hasil Pelatihan Ulang pengguna
    db.commit()
    (MA.folder_run(baru) / RC.BERKAS).unlink()
    lupakan_penanda()
    seed.jalankan(log=lambda *_: None)
    db.expire_all()
    assert db.query(ModelRun).count() == n_run + 1
    assert db.query(ModelRun).filter(ModelRun.aktif.is_(True)).one().id == baru.id
    shutil.copy2(C.ARTEFAK / RC.BERKAS, MA.folder_run(baru) / RC.BERKAS)   # pulihkan untuk uji lain
    baru.dibuat_oleh = "sistem"
    db.commit()
    MA.lupakan()
