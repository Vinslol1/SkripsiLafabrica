"""Uji alur aplikasi lewat HTTP: login, CSRF, hak akses, stok keluar, opname, rekomendasi (Gambar 3),
pesanan, penerimaan, serta impor/ekspor Excel."""
import io
import math
from datetime import date, timedelta

import pytest
from openpyxl import Workbook, load_workbook

from conftest import masuk, pesan_kilat

T = date(2026, 10, 25)          # hari terakhir data stok keluar awal


def _bahan_model(db, n=3):
    from app.layanan import model_aktif as MA
    from app.models import Bahan
    model = MA.ambil(db)
    rows = db.query(Bahan).filter(Bahan.monitor.is_(True), Bahan.aktif.is_(True), Bahan.sku.in_(list(model.q))) \
        .order_by(Bahan.sku).all()
    # bahan yang rutin dipakai agar prediksi dan ROP-nya bermakna
    rows = [b for b in rows if model.q[b.sku]["d_bar"] > 1]
    return model, rows[:n]


def _rek(db, t, bahan_id):
    from app.models import Rekomendasi
    db.expire_all()
    return db.query(Rekomendasi).filter(Rekomendasi.tanggal == t, Rekomendasi.bahan_id == bahan_id).one_or_none()


def test_semua_halaman_terbuka(admin):
    for url in ["/dasbor", "/rekomendasi", "/rekomendasi/riwayat", "/prediksi", "/bahan", "/bahan/tambah",
                "/pembelian", "/pembelian/baru", "/stok", "/stok/keluar", "/stok/opname", "/stok/terbuang", "/stok/catatan",
                "/evaluasi", "/evaluasi?urut=selisih", "/simulasi", "/simulasi?kelompok=semua", "/pelatihan",
                "/pengaturan"]:
        r = admin.get(url)
        assert r.status_code == 200, url
    for url in ["/bahan/berkas/ekspor", "/bahan/berkas/template", "/stok/ekspor", "/stok/keluar/template",
                "/stok/opname/template", "/rekomendasi/ekspor", "/laporan/1/evaluasi", "/laporan/1/simulasi",
                "/stok/catatan/unduh"]:
        r = admin.get(url)
        assert r.status_code == 200 and r.content[:2] == b"PK", url     # berkas xlsx


def test_wajib_login_dan_sandi_salah(tamu):
    r = tamu.get("/dasbor", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/masuk")
    from conftest import token
    tamu.headers["x-csrf-token"] = token(tamu.get("/masuk").text)
    r = tamu.post("/masuk", data={"username": "admin", "sandi": "salah"})
    assert "Nama pengguna atau kata sandi salah." in pesan_kilat(r.text)


def test_post_tanpa_token_csrf_ditolak(admin):
    r = admin.post("/stok/keluar/tutup", data={"tanggal": "2026-10-20"}, headers={"x-csrf-token": "palsu"})
    assert r.status_code == 400


def test_staf_tidak_bisa_mengubah_data_master(aplikasi, admin, db):
    from app.models import Bahan
    r = admin.post("/pengaturan/pengguna", data={"username": "staf1", "nama": "Staf", "sandi": "rahasia123",
                                                "peran": "staf"})
    assert "Pengguna staf1 ditambahkan." in pesan_kilat(r.text)
    staf = masuk(aplikasi, "staf1", "rahasia123")
    n = db.query(Bahan).count()
    r = staf.post("/bahan/tambah", data={"sku": "UJI01", "nama": "Bahan Uji", "satuan": "Gram"},
                  headers={"referer": "http://testserver/bahan"})
    assert any("hanya dapat dilakukan oleh admin" in m for m in pesan_kilat(r.text))
    db.expire_all()
    assert db.query(Bahan).count() == n
    assert staf.get("/rekomendasi").status_code == 200


def test_pengaturan_menolak_nilai_negatif(admin):
    r = admin.post("/pengaturan", data={"biaya_pesan": "-5", "biaya_simpan_persen": "0,1", "ql_episode": "5000",
                                        "ql_seed": "5"})
    assert any(m.startswith("Nilai tidak valid") for m in pesan_kilat(r.text))


def test_pesan_kilat_tidak_hilang_bila_belum_ditampilkan(admin):
    # pesan pertama belum sempat tampil (redirect tidak diikuti), pesan kedua tetap harus ikut tersimpan
    for nilai in ("-5", "-6"):
        admin.post("/pengaturan", data={"biaya_pesan": nilai, "biaya_simpan_persen": "0,1", "ql_episode": "5000",
                                        "ql_seed": "5"}, follow_redirects=False)
    pesan = pesan_kilat(admin.get("/pengaturan").text)
    assert sum(m.startswith("Nilai tidak valid") for m in pesan) == 2


def test_alur_harian_rekomendasi_pesan_terima(admin, db):
    from app.layanan import rekomendasi as RK
    from app.layanan import stok as ST
    from app.models import Bahan, MutasiStok, Pesanan
    model, (a, b, c) = _bahan_model(db)
    kap_b = model.q[b.sku]["kap"]

    # 1. tanpa stok opname belum ada jumlah pesan yang bisa direkomendasikan
    h = RK.hitung(db, T)
    assert h.status == "ok" and a.id in {x.id for x in h.tanpa_opname}

    # 2. stok opname akhir hari T: a habis, b jauh di atas kapasitas simpan, c sedang
    r = admin.post("/stok/opname", data={"tanggal": str(T), f"fisik_{a.id}": "0",
                                         f"fisik_{b.id}": str(int(10 * kap_b)), f"fisik_{c.id}": "1.000"})
    assert "Stok opname 25 Okt 2026 tersimpan untuk 3 bahan." in pesan_kilat(r.text)

    # 3. hitung rekomendasi (Gambar 3)
    r = admin.post("/rekomendasi/hitung", data={"tanggal": str(T)})
    assert r.status_code == 200
    ra, rb = _rek(db, T, a.id), _rek(db, T, b.id)
    assert ra is not None and rb is not None
    k_a = model.q[a.sku]["k"]
    assert ra.kritis and ra.posisi == 0
    # prediksi disimpan dengan 4 desimal
    assert ra.rop == pytest.approx(ra.prediksi[0] + 1.65 * ra.sigma_e, abs=1e-3)           # Persamaan 21
    assert ra.target == pytest.approx(ra.prediksi[0] + ra.prediksi[1] + 1.65 * ra.sigma_e * math.sqrt(2),
                                      abs=1e-3)                                             # Persamaan 25
    assert ra.jumlah > 0 and ra.jumlah / k_a == pytest.approx(round(ra.jumlah / k_a))        # kelipatan kemasan
    assert ra.jumlah <= model.q[a.sku]["kap"] + 1e-6
    assert not rb.kritis and rb.jumlah == 0                                                  # melebihi kapasitas
    q_pesan, rid = ra.jumlah, ra.id      # objek ORM ikut berubah saat rekomendasi dihitung ulang
    db.expire_all()
    assert db.get(Bahan, a.id).stok_minimum == math.ceil(ra.rop - 1e-9)                      # ROP -> Stok Minimum

    # 4. buat pesanan dari rekomendasi, lalu stok dalam perjalanan ikut dihitung
    r = admin.post("/rekomendasi/pesan", data={"tanggal": str(T), "pilih": [str(rid)],
                                               f"jumlah_{rid}": str(int(q_pesan))}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/pembelian/")
    pid = int(r.headers["location"].rsplit("/", 1)[1])
    ps = db.get(Pesanan, pid)
    assert ps.status == "dipesan" and ps.tanggal_perkiraan == T + timedelta(days=1)
    RK.hitung(db, T)
    ra2 = _rek(db, T, a.id)
    assert ra2.dalam_perjalanan == pytest.approx(q_pesan) and ra2.posisi == pytest.approx(q_pesan)
    assert ra2.jumlah == 0                                   # posisi stok sudah mencukupi, tidak pesan dua kali

    # 5. barang diterima awal hari berikutnya dan stok keluar hari itu dicatat manual
    t1 = T + timedelta(days=1)
    r = admin.post(f"/pembelian/{pid}/terima", data={"tanggal_terima": str(t1),
                                                     f"diterima_{ps.items[0].id}": str(int(q_pesan))})
    assert any("diterima" in m for m in pesan_kilat(r.text))
    r = admin.post("/stok/keluar", data={"tanggal": str(t1), "tampil": [str(a.id), str(c.id)],
                                         f"keluar_{a.id}": "5", f"keluar_{c.id}": ""})
    assert r.status_code == 200
    db.expire_all()
    assert db.query(MutasiStok).filter(MutasiStok.bahan_id == a.id, MutasiStok.jenis == "masuk").count() == 1
    akhir = ST.susun_buku(db, t1, [a.id]).akhir_pada(t1)[0]
    assert akhir == pytest.approx(q_pesan - 5)

    # 6. hari yang belum dicatat menghentikan rekomendasi dan meminta pengelola melengkapi data
    t3 = T + timedelta(days=3)
    h = RK.hitung(db, t3)
    assert h.status == "belum_lengkap" and h.hari_kurang == [T + timedelta(days=2), t3]
    r = admin.post("/rekomendasi/hitung", data={"tanggal": str(t3)})
    assert any("belum tercatat" in m for m in pesan_kilat(r.text))

    # 7. hari kafe tutup dihitung sebagai pemakaian 0, sehingga rekomendasi bisa dihitung lagi
    admin.post("/stok/keluar/tutup", data={"tanggal": str(T + timedelta(days=2))})
    admin.post("/stok/keluar/tutup", data={"tanggal": str(t3)})
    assert RK.hitung(db, t3).status == "ok"


def test_impor_stok_keluar_format_panjang(admin, db):
    from app.models import Bahan, StokKeluar
    _, (a, *_ ) = _bahan_model(db, 1)
    wb = Workbook()
    ws = wb.active
    ws.append(["Tanggal", "SKU", "Jumlah Keluar"])
    ws.append(["30/10/2026", a.sku, 7])
    ws.append(["30/10/2026", "XX999", 1])
    buf = io.BytesIO()
    wb.save(buf)
    r = admin.post("/stok/keluar/impor", files={"berkas": ("keluar.xlsx", buf.getvalue(),
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}, data={"tanggal": ""})
    pesan = pesan_kilat(r.text)
    assert any(m.startswith("Impor stok keluar: 1 hari") for m in pesan), (r.status_code, pesan, r.url)
    assert any("XX999" in m for m in pesan)
    db.expire_all()
    q = db.query(StokKeluar).filter(StokKeluar.bahan_id == a.id, StokKeluar.tanggal == date(2026, 10, 30)).one()
    assert q.jumlah == 7


def test_ekspor_lalu_impor_parameter_bahan(admin, db):
    from app.models import Bahan
    _, (a, *_ ) = _bahan_model(db, 1)
    r = admin.get("/bahan/berkas/ekspor")
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Parameter PrediStok"]
    judul = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2):
        if row[0].value == a.sku:
            row[judul.index("Harga Beli per Satuan Dasar (Rp)")].value = 123.45
            row[judul.index("Masa Simpan (hari)")].value = 7
            row[judul.index("Kapasitas Simpan Maks (kemasan)")].value = 12
            row[judul.index("Data sudah benar (Y/T)")].value = "Y"
    buf = io.BytesIO()
    wb.save(buf)
    r = admin.post("/bahan/berkas/impor", files={"berkas": ("bahan.xlsx", buf.getvalue(),
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert any(m.startswith("Impor selesai: 0 bahan baru") for m in pesan_kilat(r.text))
    db.expire_all()
    b = db.get(Bahan, a.id)
    assert (b.harga_satuan, b.masa_simpan, b.maks_kelipatan) == (123.45, 7, 12)
    assert b.daftar_asumsi == []
