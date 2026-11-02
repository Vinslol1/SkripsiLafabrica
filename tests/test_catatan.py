"""Catatan manual cafe (laporan WhatsApp order dan barang masuk): penguraian, halaman, dan impor ulang Excel."""
import io
from datetime import date

from conftest import pesan_kilat
from openpyxl import load_workbook

TEKS = """REPORT ORDER tanggal 5-november-2026
*Lafabrica kitchen* :
- cumi 1kg
- tempe 3 btng
barang masuk hari ini tanggal 6-november-2026
*Lafabrica kitchen* :
- cumi 1000gr
- tempe 3 btng
- sendok plastik 2 pack
"""


def test_urai_baris_jumlah_satuan_dan_kurung():
    from app.layanan.catatan_manual import urai_baris
    kasus = {
        "- gold label 907gr (2botol)": (2, "botol", 907, "g"),          # ukuran (banyaknya)
        "- mie telur cap 3 ayam 2bks(200gr)": (2, "bungkus", 200, "g"),  # banyaknya (ukuran)
        "* Bakso ikan 1/2 kg": (0.5, "kg", None, None),
        "* ayam 3 1/2kg": (3.5, "kg", None, None),
        "- cabe rawit1/4": (0.25, "tanpa satuan", None, None),
        "- buah naga ( 2 kg )": (2, "kg", None, None),
    }
    for teks, harap in kasus.items():
        r = urai_baris(teks)
        assert (r["jumlah"], r["satuan"], r["isi"], r["satuan_isi"]) == harap, teks
    r = urai_baris("- bubuk kopi 2 bks ( 2000 gram )")                 # berat total di dalam kurung
    assert (r["jumlah"], r["satuan"]) == (2000, "g")
    r = urai_baris("- bumbu ayam penyet 10rb")
    assert r["jumlah"] is None and r["rupiah"] == 10000
    r = urai_baris("- beans arabica (sisa display dan 1 pack cadangan )")   # sisa stok, bukan jumlah order
    assert r["jumlah"] is None and "sisa display" in r["keterangan"]


def test_rapikan_mencocokkan_bahan_dan_satuan(db):
    from app.layanan import catatan_manual as CM
    df, laporan = CM.rapikan(TEKS, CM.Master.dari_db(db))
    assert [lp.jenis for lp in laporan] == ["order", "masuk"]
    m = df[df["jenis"] == "masuk"].set_index("nama")
    assert (m.loc["cumi", "sku"], m.loc["cumi", "jumlah_dasar"], m.loc["cumi", "status"]) == ("BB111", 1000, CM.DIPAKAI)
    assert (m.loc["tempe", "jumlah_dasar"], m.loc["tempe", "status"]) == (750, CM.PERLU_DICEK)   # 1 batang = 250 g
    assert m.loc["sendok plastik", "status"] == CM.BUKAN_BAHAN
    assert set(CM.order_vs_masuk(df)["status"]) == {"sesuai"}
    k1a = CM.data_k1_aktual(df)
    assert sorted(k1a["baris"]["sku"]) == ["BB111", "BB54"] and [str(h.date()) for h in k1a["hari"]] == ["2026-11-06"]


def test_catatan_awal_tempel_unduh_koreksi_impor_hapus(admin, db):
    from app.models import CatatanBarang
    # catatan WhatsApp di data_awal/catatan_manual diisi saat basis data dibuat
    assert db.query(CatatanBarang).filter(CatatanBarang.jenis == "masuk").count() > 300
    r = admin.get("/stok/catatan")
    assert r.status_code == 200 and "Barang masuk tercatat" in r.text
    for url in ["/stok/catatan?status=perlu dicek", "/stok/catatan?jenis=order&tanggal=semua"]:
        assert admin.get(url).status_code == 200, url
    # tempel dua kali: catatan tanggal yang sama diganti, tidak digandakan
    for _ in range(2):
        r = admin.post("/stok/catatan/tempel", data={"teks": TEKS})
        assert any(m.startswith("Catatan tersimpan: 3 baris barang masuk") for m in pesan_kilat(r.text)), \
            pesan_kilat(r.text)
    db.expire_all()
    assert db.query(CatatanBarang).filter(CatatanBarang.tanggal == date(2026, 11, 6)).count() == 3
    # unduh Excel, koreksi baris "perlu dicek" (tempe), lalu impor kembali
    r = admin.get("/stok/catatan/unduh")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Barang Masuk"]
    judul = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2):
        if row[0].value.date() == date(2026, 11, 6) and row[judul.index("Nama Barang")].value == "tempe":
            row[judul.index("Jumlah (Satuan Dasar)")].value = 600
            row[judul.index("Status")].value = "dipakai"
    buf = io.BytesIO()
    wb.save(buf)
    r = admin.post("/stok/catatan/impor", files={"berkas": ("catatan.xlsx", buf.getvalue(),
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert any(m.startswith("Catatan tersimpan") for m in pesan_kilat(r.text)), pesan_kilat(r.text)
    db.expire_all()
    t = db.query(CatatanBarang).filter(CatatanBarang.tanggal == date(2026, 11, 6), CatatanBarang.nama == "tempe").one()
    assert (t.jumlah_dasar, t.status) == (600, "dipakai")
    # Excel dengan SKU yang tidak dikenal ditolak tanpa mengubah data
    ws.cell(row=2, column=judul.index("SKU") + 1, value="XX999")
    buf = io.BytesIO()
    wb.save(buf)
    r = admin.post("/stok/catatan/impor", files={"berkas": ("salah.xlsx", buf.getvalue(),
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert any("XX999" in m for m in pesan_kilat(r.text))
    # hapus catatan barang masuk satu hari
    admin.post("/stok/catatan/hapus", data={"tanggal": "2026-11-06", "jenis": "masuk"})
    db.expire_all()
    assert db.query(CatatanBarang).filter(CatatanBarang.tanggal == date(2026, 11, 6),
                                          CatatanBarang.jenis == "masuk").count() == 0
