"""Catatan manual cafe (laporan WhatsApp order dan barang masuk): penguraian, halaman, dan impor ulang Excel."""
import io
from datetime import date

from conftest import pesan_kilat
from openpyxl import load_workbook

TEKS = """REPORT ORDER tanggal 19-november-2026
*Lafabrica kitchen* :
- cumi 1kg
- tempe 3 btng
barang masuk hari ini tanggal 20-november-2026
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
    assert sorted(k1a["baris"]["sku"]) == ["BB111", "BB54"] and [str(h.date()) for h in k1a["hari"]] == ["2026-11-20"]


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
    assert db.query(CatatanBarang).filter(CatatanBarang.tanggal == date(2026, 11, 20)).count() == 3
    # unduh Excel, koreksi baris "perlu dicek" (tempe), lalu impor kembali
    r = admin.get("/stok/catatan/unduh")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Barang Masuk"]
    judul = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2):
        if row[0].value.date() == date(2026, 11, 20) and row[judul.index("Nama Barang")].value == "tempe":
            row[judul.index("Jumlah (Satuan Dasar)")].value = 600
            row[judul.index("Status")].value = "dipakai"
    buf = io.BytesIO()
    wb.save(buf)
    r = admin.post("/stok/catatan/impor", files={"berkas": ("catatan.xlsx", buf.getvalue(),
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert any(m.startswith("Catatan tersimpan") for m in pesan_kilat(r.text)), pesan_kilat(r.text)
    db.expire_all()
    t = db.query(CatatanBarang).filter(CatatanBarang.tanggal == date(2026, 11, 20), CatatanBarang.nama == "tempe").one()
    assert (t.jumlah_dasar, t.status) == (600, "dipakai")
    # Excel dengan SKU yang tidak dikenal ditolak tanpa mengubah data
    ws.cell(row=2, column=judul.index("SKU") + 1, value="XX999")
    buf = io.BytesIO()
    wb.save(buf)
    r = admin.post("/stok/catatan/impor", files={"berkas": ("salah.xlsx", buf.getvalue(),
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert any("XX999" in m for m in pesan_kilat(r.text))
    # hapus catatan barang masuk satu hari
    admin.post("/stok/catatan/hapus", data={"tanggal": "2026-11-20", "jenis": "masuk"})
    db.expire_all()
    assert db.query(CatatanBarang).filter(CatatanBarang.tanggal == date(2026, 11, 20),
                                          CatatanBarang.jenis == "masuk").count() == 0


TEKS_WA = """[11/11, 18:53] kevin: Barang masuk hari ini tnggl 5 nov 2026

* beras 10000gr
* Ayam special 3000gr( 1kg potong 8)
* Totole 80gr(2bks)
* Udang kering 1 0ns
* minyak mkan 1 dus( 6 bks 13 liter)
* gas 4 tbung( 1 tabung sma bar kitchen)

*mkan karywan*
Telur 40 butir
[11/11, 18:53] kevin: REPORT ORDER tanggal 5- november-2026

*orderan kitchen lafabrica* :
* Ayam dada 2kg
* Bawng merah kupas 1/2kg
[11/11, 18:53] kevin: REPORT ORDER tanggal 5- november-2026

*orderan (bar depan)*
* Madu 1-2 botol

*orderan kitchen lafabrica* :
* Ayam dada 2kg
* Bawng merah kupas 1/2kg
[11/11, 18:53] kevin: *orderan bar :*
1. Dripp Lychee ( sisa display )
14. Beans Arabica 1.585 gr

orderan waiters :
1. Sedotan besar (utk smoothies)
[11/11, 18:53] kevin: Barang masuk Bar Kitchen tgl 6 Nov
1. Alpukat 3 kg
2. Air mineral 5 kotak
[11/11, 18:53] kevin: Orderan bar kitchen
1. Allukat 3 kg
[11/11, 18:53] kevin: *Belanja frozen*
Spagetti sedani 2bks
[11/11, 18:53] kevin: barang masuk bar depan lafabrica 7/11/26
1. beans arabica 4 bag
"""


def test_pesan_whatsapp_diteruskan_dengan_judul_beragam(db):
    """Pesan WhatsApp yang diteruskan: awalan pesan, judul singkat, order tanpa tanggal, dan kiriman ulang."""
    from app.layanan import catatan_manual as CM
    df, laporan = CM.rapikan(TEKS_WA, CM.Master.dari_db(db))
    ringkas = [(lp.jenis, str(lp.tanggal_tertulis), sorted({b["bagian"] for b in lp.baris})) for lp in laporan]
    assert ringkas == [
        ("masuk", "2026-11-05", ["Kitchen", "Makan karyawan"]),   # bagian tidak ditulis: ditebak dari isi barangnya
        ("order", "2026-11-05", ["Kitchen"]),
        ("order", "2026-11-05", ["Bar depan"]),                    # kiriman ulang: bagian kitchen yang sama dibuang
        ("order", "2026-11-05", ["Bar depan", "Waiters"]),         # tanpa tanggal: ikut laporan sebelumnya
        ("masuk", "2026-11-06", ["Bar belakang"]),                 # "bar kitchen" = bar belakang; "tgl 6 Nov"
        ("order", "2026-11-06", ["Bar belakang"]),
        ("order", "2026-11-06", ["Kitchen"]),                      # daftar belanja dicatat sebagai order
        ("masuk", "2026-11-07", ["Bar depan"]),                    # tanggal 7/11/26
    ]
    assert "Kiriman ulang" in laporan[2].catatan and "Daftar belanja" in laporan[6].catatan
    o = df[df["jenis"] == "order"]
    assert int((o["nama_normal"] == "ayam dada").sum()) == 1       # order kitchen 5 November tidak terhitung dua kali
    m = df[df["jenis"] == "masuk"].set_index("nama_normal")
    assert (m.loc["ayam special", "sku"], m.loc["ayam special", "jumlah_dasar"]) == ("BB176", 24)   # 3 kg x 8 potong
    assert m.loc["totole", "jumlah_dasar"] == 80 and m.loc["totole", "status"] == CM.PERLU_DICEK     # berat total
    assert m.loc["udang kering", "jumlah_dasar"] == 100            # "1 0ns" = 1 ons
    assert m.loc["minyak makan", "jumlah_dasar"] == 13000          # isi dus yang tertulis di catatan
    assert (m.loc["gas", "sku"], m.loc["gas", "jumlah_dasar"]) == ("BB105", 4)
    assert m.loc["telur", "status"] == CM.KARYAWAN
    assert (m.loc["alpukat", "jumlah_dasar"], m.loc["air mineral", "jumlah_dasar"]) == (3000, 120)
    assert (m.loc["beans arabica", "jumlah_dasar"], m.loc["beans arabica", "status"]) == (4000, CM.PERLU_DICEK)
    assert o.set_index("nama_normal").loc["beans arabica", "jumlah_dasar"] == 1585   # "1.585 gr"
    assert o.set_index("nama_normal").loc["bawang merah", "sku"] == "BB129"
    # daftar belanja tidak dibandingkan dengan barang masuk dan tidak menjadi barang masuk K1 aktual
    assert "BB56" not in set(CM.order_vs_masuk(df)["sku"]) and "BB56" not in set(CM.data_k1_aktual(df)["baris"]["sku"])
