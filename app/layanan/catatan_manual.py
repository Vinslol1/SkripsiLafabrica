"""Merapikan catatan manual cafe (laporan WhatsApp "REPORT ORDER" dan "barang masuk hari ini").

Catatan harian cafe ditulis bebas per bagian (bar depan, bar belakang, kitchen, makan karyawan). Modul ini:
  1. memisahkan teks menjadi laporan order dan laporan barang masuk per tanggal (teks boleh berupa tempelan
     biasa atau pesan WhatsApp yang diteruskan, lengkap dengan awalan "[11/11, 18:53] nama: "),
  2. mengurai setiap baris menjadi nama barang, jumlah, satuan, dan keterangan,
  3. mencocokkan nama barang dengan data bahan (SKU) dan mengubah jumlah ke satuan dasar majoo.

Baris yang pencocokan atau konversinya memakai asumsi diberi status "perlu dicek", supaya pengguna bisa
memeriksanya di Excel sebelum barang masuk diimpor ke aplikasi. Barang masuk inilah yang dipakai K1 aktual.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from ml.simulasi import jendela_aktual  # noqa: F401  (dipakai halaman Catatan Barang Masuk)

BULAN = {"januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
         "september": 9, "oktober": 10, "november": 11, "desember": 12,
         "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "agu": 8, "ags": 8, "agt": 8, "agust": 8,
         "sep": 9, "sept": 9, "okt": 10, "nov": 11, "nop": 11, "des": 12}

BAGIAN = {"bar depan": "Bar depan", "bar belakang": "Bar belakang", "kitchen": "Kitchen",
          "makan karyawan": "Makan karyawan", "waiters": "Waiters"}
TIDAK_DIKETAHUI = "Tidak diketahui"

# status baris
DIPAKAI = "dipakai"                       # cocok dengan data bahan dan jumlahnya jelas
PERLU_DICEK = "perlu dicek"               # dipakai, tetapi pencocokan atau konversi memakai asumsi
TANPA_JUMLAH = "tanpa jumlah"             # barang disebut tanpa jumlah (biasanya order "sisa display ...")
BELUM_ADA = "belum ada di data bahan"     # bahan baku yang belum terdaftar di majoo/aplikasi
BUKAN_BAHAN = "bukan bahan menu"          # perlengkapan (sedotan, cup, plastik, ...)
KARYAWAN = "makan karyawan"               # belanja makan karyawan, tidak tercatat di stok keluar menu
RUPIAH = "jumlah dalam rupiah"            # contoh "bumbu ayam penyet 10rb"

STATUS_DIPAKAI = (DIPAKAI, PERLU_DICEK)

_SINGKATAN = [
    (r"\bc\.\s*", "cabe "), (r"\bcbe\b", "cabe"), (r"\bbwng\b|\bbwang\b", "bawang"), (r"\bslada\b", "selada"),
    (r"\btoge\b", "tauge"), (r"\bkwetiaw\b|\bkwitiau\b", "kwetiau"), (r"\bifomi\b|\bifumie\b", "ifumie"),
    (r"\bindomi\b", "indomie"), (r"\bkentng\b", "kentang"), (r"\btimum\b", "timun"), (r"\bpapruka\b", "paprika"),
    (r"\bhijua\b|\bijo\b", "hijau"), (r"\balpukad\b", "alpukat"), (r"\bnenas\b", "nanas"), (r"\bkasuati\b", "kasturi"),
    (r"\bcurros\b", "churros"), (r"\bsambosa\b", "samosa"), (r"\bspagetti\b", "spaghetti"), (r"\btelor\b", "telur"),
    (r"\bayan\b", "ayam"), (r"\bbubukopi\b", "bubuk kopi"), (r"\blychee\b", "leci"), (r"\bchiken\b", "chicken"),
    (r"\bminyk\b|\bmiinyk\b", "minyak"), (r"\bmkan\b|\bmakn\b|\bmkn\b", "makan"), (r"\bbngo\b|\bbongo\b", "bango"),
    (r"\bpaking\b|\bpeking\b", "packing"), (r"\bmoca\b", "mocca"), (r"\bkeci\b", "leci"), (r"\bsawi nanas\b", "sawi manis"),
    (r"\bbutter croissant\b", "croissant"), (r"\bgreenfielda\b", "greenfields"),
    # ejaan yang muncul di catatan November
    (r"\balvukad\b|\ballukat\b|\balpokat\b", "alpukat"), (r"\bkasuari\b", "kasturi"), (r"\banyam\b", "ayam"),
    (r"\bkampoeng\b", "kampung"), (r"\bwoerter\b", "wortel"), (r"\bjanteen\b", "janten"), (r"\bkeca\b", "kecap"),
    (r"\blecing\b|\blecy\b", "leci"), (r"\bdripp\b", "drip"), (r"\bsereh\b", "serai"), (r"\bubu roti\b", "ubi roti"),
    (r"\budangnkering\b", "udang kering"), (r"\bmashroom\b", "mushroom"), (r"\bsaging\b", "daging"),
    (r"\bsbun\b", "sabun"), (r"\bpaprik\b", "paprika"), (r"\budng\b", "udang"), (r"\bbenas\b", "beans"),
    (r"\bhostblend\b|\bhouseblend\b", "house blend"), (r"\bbiscof\b", "biscoff"), (r"\bnuttela\b", "nutella"),
    (r"\btengerine\b", "tangerine"), (r"\bvanila\b", "vanilla"), (r"\bbilognaise\b|\bbolognaise\b", "bolognese"),
    (r"\bmi (?=telur|aceh)", "mie "), (r"\bbawng\b", "bawang"),
]

# (pola nama yang sudah dinormalkan, bagian atau None, SKU atau status, catatan asumsi atau "")
# Teks di antara pola menandai kelompok bagian tempat barang itu biasa dicatat (dipakai tebak_bagian).
_ALIAS_PER_BAGIAN = [
    "Bar depan",
    (r"^beans? (arabica|brazil|arabica brazil)\b", None, "BB01", "beans brazil dianggap Beans Arabica"),
    (r"^beans? house blend|^(house )?blend beans?", None, "BB02", ""),
    (r"^beans? blend", None, "BB02", "beans blend dianggap Beans House Blend"),
    (r"^beans? argopuro", None, "BB03", ""),
    (r"^(beans? |powder )?wine\b", None, "BB20", "wine dianggap Powder Beans Wine"),
    (r"^beans? ciwid[ae]y|^ciwid[ae]y beans?", None, BELUM_ADA, "beans Ciwidey belum terdaftar di data bahan"),
    (r"^(powder )?denali (powder )?matcha|^powder (denali )?matcha", None, "BB15", ""),
    (r"^(powder )?denali (powder )?coklat|^powder (denali )?coklat", None, "BB09", ""),
    (r"^monin grenadine", None, "BB24", ""),
    (r"^monin peach", None, "BB33", ""),
    (r"^monin tangerine", None, "BB32", ""),
    (r"^drip mint", None, "BB14", ""),
    (r"^drip leci|^leci drip", None, "BB30", ""),
    (r"^drip (sauce )?caramel|^(saus|sauce) caramel", None, "BB11", ""),
    (r"^drip strawberry", None, "BB22", ""),
    (r"^strawberry pure", None, "BB22", "strawberry pure dianggap Drip Strawberry"),
    (r"^drip vanilla|^vanilla drip", None, "BB10", ""),
    (r"^ice cream vanilla", None, "BB16", ""),
    (r"^ice cream three colou?r", None, "BB150", ""),
    (r"^ice cream strawberry", None, "BB149", ""),
    (r"^gold label", None, "BB18", ""),
    (r"^teh (celup )?lipton", None, "BB26", ""),
    (r"^(bubuk |powder )?teh bendera", None, "BB29", ""),
    (r"^(kantong )?teh jasmine|^jasmine tea", None, "BB07", ""),
    (r"^biscoff", None, "BB39", ""),
    (r"^gula aren(?! stic?k)", None, "BB17", ""),
    (r"^kue (kering|salju)", None, BELUM_ADA, "kue kering titipan belum terdaftar sebagai bahan"),
    (r"^croissant", None, "SNS001", ""),
    (r"^(buah )?alpukat", None, "BB25", ""),
    (r"^madu", "Bar depan", "BB05", "madu bar depan dianggap Madu Hutan (Bar Coffee)"),
    (r"^madu", "Bar belakang", "BB166", "madu bar belakang dianggap Madu Akasia (Bar Kitchen)"),
    (r"^(buah )?strawberry", None, "BB23", ""),
    (r"^sari lemon", None, "BB12", ""),
    (r"^mocca ceres", None, "BB155", ""),
    (r"^brownies (burn |burnt )?cheese ?cake", None, "BB152", ""),
    (r"^cheese ?cake", None, "BB154", ""),
    (r"^freshmilk|^fresh milk|^greenfields?", None, "BB08", ""),
    (r"^(powder |bubuk )thai tea", None, "BB28", ""),
    (r"^leci kaleng", None, "BB31", ""),
    (r"^daun mint", None, "BB27", ""),
    (r"^roti o\b", None, "SNS015", ""),
    (r"^donat", None, BELUM_ADA, "donat titipan belum terdaftar sebagai bahan"),
    (r"^gabin", None, BELUM_ADA, "gabin belum terdaftar sebagai bahan"),
    (r"^buko pandan", None, "BB153", ""),
    (r"^kacang\b", "Bar depan", "SNS010", "kacang bar depan dianggap Kacang Snack"),
    (r"^skm (putih|original)|^skm \d|^skm$", None, "BB19", ""),
    (r"^daun rosemary", None, BELUM_ADA, "rosemary belum terdaftar sebagai bahan"),
    (r"^(buah )?semangka", None, "BB36", ""),
    "Bar belakang",
    (r"^jambu", None, "BB165", ""),
    (r"^melon", None, "BB170", ""),
    (r"^sawi manis", "Bar belakang", BELUM_ADA, "sawi manis bar belakang belum terdaftar sebagai bahan"),
    (r"^(kopi|biji kopi) sumatera|^bubuk kopi", None, "BB160", "kopi sumatera/bubuk kopi dianggap Biji Kopi Sumatera"),
    (r"^(air )?mineral( water| botol)?", None, "BB175", "air mineral bar belakang dianggap Air Mineral 600ml"),
    (r"^gula pasir|^gula\b(?! stic?k)", None, "BB13", ""),
    (r"^skm coklat", None, "BB21", ""),
    (r"^badak", None, "BB163", ""),
    (r"^teh (celup )?sosro|^teh sosro", None, "BB167", ""),
    (r"^jeruk nipis", None, "BB06", ""),
    (r"^jeruk\b", None, "BB169", ""),
    (r"^lemon\b", None, BELUM_ADA, "lemon segar belum terdaftar sebagai bahan"),
    (r"^(buah )?naga", None, "BB171", ""),
    (r"^(buah )?nanas", None, "BB172", ""),
    (r"^telur ayam kampung", None, "BB179", ""),
    (r"^(buah )?kasturi", None, "BB173", ""),
    (r"^sirup kurnia", None, "BB162", ""),
    (r"^serai", None, "BB164", ""),
    (r"^milo|^coklat$", None, "BB161", ""),
    (r"^wortel", None, "BB40", ""),
    "Kitchen",
    (r"^beras", None, "BB126", ""),
    (r"^daging asap", None, "BB108", ""),
    (r"^daging sapi|^sapi\b", None, "BB109", ""),
    (r"^ayam dada", None, "BB133", "ayam dada dianggap Ayam Slice"),
    (r"^ayam penyet", None, "BB132", ""),
    (r"^ayam spe[cs]ial|^ayam\b", "Kitchen", "BB176", ""),
    (r"^cumi", None, "BB111", ""),
    (r"^udang kering", None, "BB42", ""),
    (r"^udang", None, "BB43", ""),
    (r"^bakso ikan", None, "BB131", "bakso ikan dianggap Bakso"),
    (r"^bakso", None, "BB131", ""),
    (r"^kerupuk", None, "BB92", ""),
    (r"^totole", None, "BB44", ""),
    (r"^selada", None, "BB60", ""),
    (r"^racik tempe", None, "BB121", "racik tempe dianggap Bumbu Racik/Sajiku"),
    (r"^tempe", None, "BB54", ""),
    (r"^terong", None, "BB47", ""),
    (r"^saos cabe|^saus cabe", None, "BB67", ""),
    (r"^cabe hijau", None, "BB118", ""),
    (r"^cabe rawit", None, "BB116", ""),
    (r"^cabe merah", None, "BB117", ""),
    (r"^cabe caplak|^caplak", None, "BB119", ""),
    (r"^cabe geprek", None, "BB119", "cabe geprek dianggap Cabe Caplak"),
    (r"^cabe giling", None, BELUM_ADA, "cabe giling belum terdaftar sebagai bahan"),
    (r"^bawang merah", None, "BB129", ""),
    (r"^bawang putih", None, "BB127", ""),
    (r"^bawang packing", None, "BB128", ""),
    (r"^bawang goreng", None, "BB130", ""),
    (r"^(bawang )?bomba[iy]", None, "BB124", ""),
    (r"^saori lada hitam", None, "BB68", ""),
    (r"^(saori )?saos tiram", None, "BB65", ""),
    (r"^saos tomat", None, "BB64", ""),
    (r"^sawi putih", None, "BB61", ""),
    (r"^sawi (hijau|manis)|^sawi$", "Kitchen", "BB62", "sawi/sawi manis kitchen dianggap Sawi Hijau"),
    (r"^tauge", None, "BB140", ""),
    (r"^kol\b", None, "BB178", ""),
    (r"^daun pre", None, "BB107", ""),
    (r"^bumbu (mie? )?aceh", None, "BB122", ""),
    (r"^kentang goreng", None, "BB93", "kentang goreng dianggap Kentang"),
    (r"^kentang", None, "BB93", ""),
    (r"^srikaya", None, "BB55", ""),
    (r"^sosis", None, "BB57", ""),
    (r"^pisang", None, "BB76", ""),
    (r"^bunga kol", None, "BB120", ""),
    (r"^brokoli|^brocoli", None, "BB123", ""),
    (r"^arcis", None, "BB135", ""),
    (r"^janten", None, "BB99", ""),
    (r"^tepung (pisang )?adabi", None, "BB51", ""),
    (r"^tepung sajiku|^sajiku", None, "BB121", ""),
    (r"^tepung roti", None, "BB52", ""),
    (r"^tepung panir", None, "BB53", ""),
    (r"^tepung terigu", None, "BB49", ""),
    (r"^indomie (goreng|goreng goreng)", None, "BB103", ""),
    (r"^indomie (kari|kuah)", None, "BB102", "indomie kuah dianggap Indomie Kari"),
    (r"^mie aceh|^mi aceh", None, "BB84", ""),
    (r"^kebab cheese", None, "BB97", ""),
    (r"^kebab beef", None, "BB98", ""),
    (r"^churros", None, "BB113", ""),
    (r"^ubi roti", None, "BB59", "ubi roti dianggap Singkong"),
    (r"^spaghetti", None, "BB56", ""),
    (r"^chicken burger", None, "BB114", ""),
    (r"^cheese burger", None, "BB115", "cheese burger dianggap Beef Burger"),
    (r"^pizza meat lovers", None, "BB75", ""),
    (r"^pizza mushroom", None, "BB74", ""),
    (r"^risol mayo", None, "BB73", ""),
    (r"^nutella|^ceres nutella", None, "BB81", ""),
    (r"^jahe", None, "BB101", ""),
    (r"^kucai", None, "BB91", ""),
    (r"^gas (fortable|portable)", None, BUKAN_BAHAN, ""),
    (r"^gas\b", None, "BB105", ""),
    (r"^paprika", None, "BB79", ""),
    (r"^timun", None, "BB46", ""),
    (r"^tomat", None, "BB45", ""),
    (r"^kwetiau", None, "BB90", ""),
    (r"^ifumie", None, "BB104", ""),
    (r"^sasa", None, "BB63", ""),
    (r"^kecap asin", None, "BB96", ""),
    (r"^kecap manis|^kecap bango", None, "BB95", ""),
    (r"^garam", None, "BB106", ""),
    (r"^jamur", None, "BB100", ""),
    (r"^merica", None, "BB85", ""),
    (r"^minyak (makan|goreng)", None, "BB82", ""),
    (r"^minyak wijen", None, "BB145", ""),
    (r"^mentega", None, "BB86", ""),
    (r"^bihun", None, "BB125", ""),
    (r"^maizena", None, "BB146", ""),
    (r"^ikan teri|^teri", None, "BB48", ""),
    (r"^roti tawar", None, "BB71", ""),
    (r"^roti$", "Kitchen", "BB71", "roti (tanpa keterangan) di kitchen dianggap Roti Tawar"),
    (r"^pasta tomyam", None, "BB77", ""),
    (r"^mayonaise|^mayones", None, "BB147", ""),
    (r"^oregano", None, "BB80", ""),
    (r"^parsley", None, "BB78", ""),
    (r"^keju\b", None, "BB94", ""),
    (r"^mantao", None, "BB87", ""),
    (r"^samosa curry", None, "BB69", ""),
    (r"^samosa bolognese", None, "BB70", ""),
    (r"^siomay", None, "BB58", ""),
    (r"^lumpia", None, "BB88", ""),
    (r"^mie telur", None, "BB83", ""),
    (r"^telur\b", None, "ST001", ""),
    (r"^terasi", None, BELUM_ADA, "terasi belum terdaftar sebagai bahan"),
    (r"^bumbu ayam penyet", None, BELUM_ADA, "bumbu ayam penyet belum terdaftar sebagai bahan"),
    "",                                                       # perlengkapan
    (r"^(gula stic?k|gula aren stic?k|sendok|tusuk gigi|sedotan|pengharum|cup|gelas|hands? gloves|plastik|sisa tutup"
     r"|tidak ada orderan|parkir|lesung|sabun|mama lemon|daun pisang)", None, BUKAN_BAHAN, ""),
]
ALIAS, _KELOMPOK_ALIAS = [], []
for _a in _ALIAS_PER_BAGIAN:
    if isinstance(_a, str):
        _kelompok = _a
    else:
        ALIAS.append(_a)
        _KELOMPOK_ALIAS.append(_kelompok)

# Isi satu satuan pembelian dalam satuan dasar bila data bahan tidak punya konversinya (asumsi, perlu dicek).
# Kunci: (SKU, satuan) -> (isi, keterangan)
ISI_ASUMSI = {
    ("BB132", "kg"): (None, "ayam penyet dicatat dalam kg; isi per kg belum diketahui"),
    ("BB170", "buah"): (1500.0, "1 buah melon dianggap 1.500 g"),
    ("BB172", "buah"): (1200.0, "1 buah nanas dianggap 1.200 g"),
    ("BB79", "buah"): (150.0, "1 buah paprika dianggap 150 g"),
    ("BB76", "sisir"): (12.0, "1 sisir pisang dianggap 12 buah"),
    ("BB54", "batang"): (250.0, "1 batang tempe dianggap 250 g (Pcs = 250 g di data bahan)"),
    ("BB54", "bungkus"): (250.0, "1 bungkus tempe dianggap sama dengan 1 batang (250 g)"),
    ("BB92", "bungkus"): (1000.0, "1 bungkus kerupuk dianggap 1.000 g (isi kemasan di data bahan)"),
    ("BB51", "bungkus"): (1000.0, "1 bungkus tepung adabi dianggap 1.000 g"),
    ("BB121", "bungkus"): (1000.0, "1 bungkus bumbu racik/sajiku dianggap 1.000 g"),
    ("BB121", "renteng"): (100.0, "1 renteng racik tempe dianggap 100 g"),
    ("BB52", "bungkus"): (1000.0, "1 bungkus tepung roti dianggap 1.000 g"),
    ("BB44", "bungkus"): (40.0, "1 bungkus totole dianggap 40 g (catatan 1 Nov: 2 bks = 40 gr per bks)"),
    ("BB63", "bungkus"): (250.0, "1 bungkus sasa dianggap 250 g"),
    ("BB64", "bungkus"): (1000.0, "1 bungkus saos tomat dianggap 1.000 g"),
    ("BB67", "bungkus"): (950.0, "1 bungkus saos cabe dianggap 950 g (catatan 1 Nov)"),
    ("BB106", "bungkus"): (250.0, "1 bungkus garam dianggap 250 g"),
    ("BB104", "bungkus"): (500.0, "1 bungkus ifumie dianggap 500 g"),
    ("BB83", "bungkus"): (200.0, "1 bungkus mie telur dianggap 200 g"),
    ("BB83", "botol"): (200.0, "mie telur tertulis \"btl\", dianggap salah tulis \"bks\" (1 bungkus = 200 g)"),
    ("BB56", "bungkus"): (1000.0, "1 bungkus spaghetti dianggap 1.000 g (catatan 3 dan 9 Nov: 1 bks = 1.000 g)"),
    ("BB95", "bungkus"): (520.0, "1 bungkus kecap manis dianggap 520 g"),
    ("BB147", "bungkus"): (1000.0, "1 bungkus mayonaise dianggap 1.000 g"),
    ("BB93", "bungkus"): (1000.0, "1 bungkus kentang goreng dianggap 1.000 g (catatan 1 Nov)"),
    ("BB27", "pack"): (50.0, "1 pack daun mint dianggap 50 g"),
    ("BB128", "g"): (None, "Bawang Packing dicatat per Pack di majoo; isi 1 pack dalam gram belum diketahui"),
    ("BB57", "bungkus"): (25.0, "1 bungkus sosis dianggap 25 pcs (isi kemasan di data bahan)"),
    ("BB71", "bungkus"): (2.0, "1 bungkus roti tawar dianggap 2 pcs (isi kemasan di data bahan)"),
    ("BB87", "bungkus"): (25.0, "1 bungkus mantao dianggap 25 pcs (isi kemasan di data bahan)"),
    ("BB69", "pax"): (5.0, "1 pax samosa dianggap 5 pcs"),
    ("BB58", "pax"): (10.0, "1 pax siomay dianggap 10 pcs"),
    ("BB88", "pax"): (10.0, "1 pax lumpia dianggap 10 pcs"),
    ("BB113", "porsi"): (5.0, "1 porsi churros dianggap 5 pcs"),
    ("BB115", "porsi"): (1.0, "1 porsi cheese burger dianggap 1 pcs"),
    ("BB114", "porsi"): (1.0, "1 porsi chicken burger dianggap 1 pcs"),
    ("BB69", "pack"): (5.0, "1 pack samosa dianggap 5 pcs"),
    ("BB70", "pack"): (5.0, "1 pack samosa dianggap 5 pcs"),
    ("BB70", "pax"): (5.0, "1 pax samosa dianggap 5 pcs"),
    ("BB55", "botol"): (500.0, "1 botol srikaya dianggap 500 g"),
    ("BB55", "pcs"): (500.0, "1 pcs srikaya dianggap 1 botol 500 g"),
    ("BB96", "botol"): (600.0, "1 botol kecap asin dianggap 600 g"),
    ("BB145", "botol"): (300.0, "1 botol minyak wijen dianggap 300 g"),
    ("BB77", "botol"): (500.0, "1 botol pasta tomyam dianggap 500 g"),
    ("BB100", "kaleng"): (400.0, "1 kaleng jamur dianggap 400 g"),
    ("BB146", "kotak"): (300.0, "1 kotak maizena dianggap 300 g"),
    ("BB21", "kaleng"): (370.0, "1 kaleng SKM coklat dianggap 370 g"),
    ("BB162", "botol"): (620.0, "1 botol sirup kurnia dianggap 620 g"),
    ("BB163", "crate"): (24.0, "1 crate badak dianggap 24 botol"),
    ("BB175", "kardus"): (24.0, "1 kardus air mineral dianggap 24 botol"),
    ("BB175", "kotak"): (24.0, "1 kotak air mineral dianggap 24 botol"),
    ("BB01", "bag"): (1000.0, "1 bag beans dianggap 1.000 g (catatan 2 Nov: 1 pack = 1.000 g)"),
    ("BB02", "bag"): (1000.0, "1 bag beans dianggap 1.000 g (catatan 2 Nov: 1 pack = 1.000 g)"),
    ("BB03", "bag"): (1000.0, "1 bag beans dianggap 1.000 g"),
    ("BB12", "botol"): (500.0, "1 botol sari lemon dianggap 500 g (catatan 3 Nov)"),
    ("BB15", "pack"): (800.0, "1 pack powder matcha dianggap 800 g (catatan 3 Nov)"),
    ("BB33", "botol"): (700.0, "1 botol monin dianggap 700 g (catatan 2 Nov)"),
    ("BB32", "botol"): (700.0, "1 botol monin dianggap 700 g"),
    ("BB30", "botol"): (760.0, "1 botol drip leci dianggap 760 g (catatan 2 Nov)"),
    ("BB27", "pcs"): (50.0, "1 pcs daun mint dianggap 1 pack 50 g"),
    ("BB18", "kotak"): (907.0, "1 kotak gold label dianggap sama dengan 1 botol 907 g (data bahan)"),
    ("BB160", "pack"): (1000.0, "1 pack kopi sumatera dianggap 1.000 g (catatan 27 Okt: 2 bks = 2.000 g)"),
    ("BB19", "dus"): (None, "isi 1 dus SKM (berapa kaleng) belum diketahui"),
    ("BB161", "pack"): (1000.0, "1 pack milo dianggap 1.000 g"),
    ("BB166", "botol"): (500.0, "1 botol madu bar belakang dianggap 500 g (Botol = 500 g di data bahan)"),
    ("BB05", "botol"): (1000.0, "1 botol madu bar depan dianggap 1.000 g"),
    ("ST001", "papan"): (30.0, "1 papan telur = 30 butir; cek apakah '10ppn' memang 10 papan"),
    ("BB179", "papan"): (30.0, "1 papan telur = 30 butir"),
    ("BB173", "kg"): (25.0, "1 kg jeruk kasturi dianggap 25 buah"),
    ("BB169", "kg"): (7.0, "1 kg jeruk dianggap 7 buah"),
    ("BB36", "buah"): (3000.0, "1 buah semangka = 3.000 g (data bahan)"),
    ("BB23", "pack"): (180.0, "1 pack strawberry = 180 g (catatan barang masuk)"),
    ("BB152", "loyang"): (8.0, "1 loyang brownies dianggap 8 potong"),
    ("BB94", "batang"): (250.0, "1 batang keju = 250 g (data bahan)"),
    ("BB26", "pack"): (100.0, "1 pack teh lipton = 100 kantung (data bahan)"),
}

# satuan tulisan cafe -> satuan baku
SATUAN = {
    "gr": "g", "g": "g", "gram": "g", "ge": "g", "grm": "g", "ml": "g",
    "kg": "kg", "kh": "kg", "lg": "kg", "jg": "kg", "kilo": "kg",
    "ons": "ons", "l": "liter", "liter": "liter", "ltr": "liter",
    "ekor": "ekor", "potong": "potong", "btng": "batang", "batang": "batang",
    "bks": "bungkus", "bk": "bungkus", "ks": "bungkus", "bungkus": "bungkus", "bms": "bungkus",
    "botol": "botol", "btol": "botol", "botil": "botol", "btl": "botol",
    "pack": "pack", "pak": "pack", "pck": "pack", "pax": "pax",
    "kaleng": "kaleng", "buah": "buah", "sisir": "sisir", "papan": "papan", "ppn": "papan",
    "crate": "crate", "krat": "crate", "kardus": "kardus", "dus": "dus", "lusin": "lusin", "porsi": "porsi",
    "bag": "bag", "tabung": "tabung", "tbung": "tabung",
    "pcs": "pcs", "pc": "pcs", "kotak": "kotak", "loyang": "loyang", "renteng": "renteng", "ikat": "ikat",
    "butir": "butir", "keping": "keping", "rb": "rb", "ribu": "rb",
}
BERAT = {"g": 1.0, "kg": 1000.0, "ons": 100.0, "liter": 1000.0}
_SAT_RE = "|".join(sorted(SATUAN, key=len, reverse=True))
# pecahan dicoba lebih dulu supaya "1/2kg" terbaca 0,5 kg (bukan "1" lalu "2kg") dan "3 1/2kg" terbaca 3,5 kg
_ANGKA = r"(\d+(?:[.,]\d+)?\s+(?:1/2|1/4|3/4)|(?:1|3)/[24]|\d+(?:[.,]\d+)?(?!\s*/))"
_RE_JUMLAH = re.compile(rf"(?<![a-z]){_ANGKA}\s*({_SAT_RE})?(?![a-z])")


@dataclass
class Laporan:
    jenis: str                 # "order" atau "masuk"
    tanggal_tertulis: date
    urutan: int
    teks: str
    tanggal: date = None       # tanggal setelah koreksi (lihat koreksi_tanggal_order)
    catatan: str = ""
    baris: list = field(default_factory=list)
    bagian: str | None = None  # bagian yang disebut di judul laporan ("Barang masuk bar kitchen 9 nov")
    belanja: bool = False      # daftar belanja ("Belanja frozen"): dicatat sebagai order, bukan barang masuk


def _angka(s: str) -> float:
    s = s.replace("¹/²", "1/2").strip()
    total = 0.0
    for bag in s.split():
        if "/" in bag:
            a, b = bag.split("/")
            total += float(a) / float(b)
        else:
            total += float(bag.replace(",", "."))
    return total


def _tanggal(h: str, b: str, t: str) -> date:
    return date(int(t), BULAN[b.lower()], int(h))


# awalan pesan WhatsApp yang diteruskan atau diekspor: "[11/11, 18:53] kevin: ", "[2/11/26 07.15.02] Nama: "
_RE_WA = re.compile(r"^\s*\[\d{1,2}/\d{1,2}(?:/\d{2,4})?,?\s+\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s*[ap]m)?\]\s*[^:\n]{1,40}:\s?",
                    re.I)
_RE_JUDUL = re.compile(r"^(report\s+order|barang\s+masuk|order(?:an)?|belanja)\b(.*)$")
_HARI = {"senin", "selasa", "rabu", "kamis", "jumat", "jum", "at", "sabtu", "minggu", "ahad"}
# kata yang boleh ada di baris judul selain tanggal dan nama bagian
_KATA_JUDUL = {"hari", "hri", "ini", "tanggal", "tgl", "tnggl", "tanggl", "tngl", "tggl", "lafabrica", "bar", "depan",
               "belakang", "kitchen", "waiters", "waiter", "orderan", "order", "barang", "masuk"} | _HARI


def _tanggal_dari(s: str, konteks: date | None = None) -> tuple[date | None, str]:
    """Tanggal di baris judul dan sisa teksnya. Bulan atau tahun yang tidak ditulis diambil dari laporan sebelumnya."""
    def aman(t, b, h):
        try:
            return date(t, b, h)
        except ValueError:
            return None

    m = re.search(r"(\d{1,2})\s*[-/ ]\s*([a-z]{3,9})\s*[-/ ]?\s*(\d{4})\b", s)
    if m and m.group(2) in BULAN:
        return aman(int(m.group(3)), BULAN[m.group(2)], int(m.group(1))), s[:m.start()] + " " + s[m.end():]
    m = re.search(r"\b(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2}|\d{4})\b", s)
    if m:
        t = int(m.group(3))
        return aman(t + 2000 if t < 100 else t, int(m.group(2)), int(m.group(1))), s[:m.start()] + " " + s[m.end():]
    m = re.search(r"\b(\d{1,2})\s*[-/ ]?\s*([a-z]{3,9})\b", s)
    if m and m.group(2) in BULAN and konteks is not None:
        return aman(konteks.year, BULAN[m.group(2)], int(m.group(1))), s[:m.start()] + " " + s[m.end():]
    m = re.search(r"\b(?:tanggal|tgl|tnggl|tanggl|tngl|tggl)\s*(\d{1,2})\b", s)
    if m and konteks is not None:
        return aman(konteks.year, konteks.month, int(m.group(1))), s[:m.start()] + " " + s[m.end():]
    return None, s


def _nama_bagian(s: str) -> str | None:
    """Bagian yang disebut dalam teks (huruf kecil). "Bar kitchen" adalah sebutan lain bar belakang."""
    if re.search(r"bar\s*\(?\s*depan", s):
        return BAGIAN["bar depan"]
    if re.search(r"bar\s*\(?\s*(belakang|kitchen)", s):
        return BAGIAN["bar belakang"]
    if "kitchen" in s:
        return BAGIAN["kitchen"]
    if re.search(r"\bwaiters?\b", s):
        return BAGIAN["waiters"]
    if re.search(r"\bbar\b", s):
        return BAGIAN["bar depan"]            # "orderan bar", "barang masuk bar lafabrica": bar kopi di depan
    return None


def _judul(baris: str, konteks: date | None = None) -> dict | None:
    """Baris judul laporan: "REPORT ORDER tanggal 5- november-2026", "Barang masuk hari ini tnggl 5 nov 2026",
    "Orderan bar kitchen tgl 9", "Order bar depan 9/11/26", "Orderan kitchen lafabrica:", "*Belanja frozen*".

    Mengembalikan jenis, tanggal (None bila tidak ditulis), bagian, dan penanda judul baku/daftar belanja; None
    bila baris bukan judul (mis. baris barang)."""
    s = re.sub(r"[*#•_]+", " ", baris.lower()).strip(" -:\t")
    m = _RE_JUDUL.match(s)
    if not m:
        return None
    kata, sisa = re.sub(r"\s+", " ", m.group(1)), m.group(2)
    tgl, sisa_teks = _tanggal_dari(sisa, konteks)
    lain = [k for k in re.findall(r"[a-z]+", sisa_teks) if k not in _KATA_JUDUL]
    belanja = kata == "belanja"
    if re.search(r"\d", sisa_teks) or len(lain) > (2 if belanja else 0):
        return None                                           # masih ada angka atau kata lain: baris barang
    return {"jenis": "masuk" if kata == "barang masuk" else "order", "tanggal": tgl, "bagian": _nama_bagian(sisa),
            "baku": kata == "report order", "belanja": belanja}


def pisah_laporan(teks: str) -> list[Laporan]:
    """Memisahkan teks tempelan menjadi laporan order dan barang masuk sesuai urutan kemunculan.

    Laporan baru dimulai oleh baris judul (lihat _judul). Di dalam satu laporan, judul sejenis yang tanpa tanggal
    atau bertanggal sama hanyalah sub-judul bagian. Pada teks WhatsApp yang diteruskan, judul di awal pesan selalu
    memulai laporan baru. Order yang judulnya tanpa tanggal memakai tanggal laporan sebelumnya."""
    teks = teks.replace("\r\n", "\n").replace("\r", "\n")
    teks = re.sub("[⁠​‎‏﻿]", "", teks)
    teks = re.sub(r"(?i)(?<!\n)(REPORT ORDER tanggal|barang masuk hari ini tanggal)", r"\n\1", teks)
    hasil: list[Laporan] = []
    isi: list[list[str]] = []
    terakhir = None                                   # tanggal laporan terakhir (konteks tanggal yang tidak lengkap)
    for baris in teks.split("\n"):
        m = _RE_WA.match(baris)
        awal_pesan = bool(m)
        if m:
            baris = baris[m.end():]
        j = _judul(baris, terakhir)
        if j:
            kini = hasil[-1] if hasil else None
            sub = (kini is not None and not awal_pesan and not j["baku"] and not j["belanja"] and not kini.belanja
                   and j["jenis"] == kini.jenis and j["tanggal"] in (None, kini.tanggal_tertulis))
            tgl = j["tanggal"] or terakhir
            if not sub and tgl is not None:
                lp = Laporan(j["jenis"], tgl, len(hasil) + 1, "", tanggal=tgl, bagian=j["bagian"], belanja=j["belanja"])
                if j["tanggal"] is None:
                    lp.catatan = f"Tanggal tidak ditulis; dianggap {tgl:%d-%m-%Y} mengikuti laporan sebelumnya."
                if j["belanja"]:
                    lp.catatan = (lp.catatan + " " if lp.catatan else "") + (
                        "Daftar belanja: dicatat sebagai order, bukan barang masuk, supaya barang yang juga ditulis di "
                        "laporan barang masuk tidak terhitung dua kali.")
                hasil.append(lp)
                isi.append([])
                terakhir = tgl
                continue
        if hasil:
            isi[-1].append(baris)
    for lp, b in zip(hasil, isi):
        lp.teks = "\n".join(b)
    return hasil


def koreksi_tanggal_order(laporan: list[Laporan]) -> list[Laporan]:
    """Order dengan tanggal tertulis ganda: order dikirim besoknya, jadi order yang isinya cocok dengan barang
    masuk hari H dianggap order hari H-1. Order lain dengan tanggal sama tidak diubah."""
    order = [lp for lp in laporan if lp.jenis == "order"]
    masuk = {}                                         # tanggal -> SKU barang masuk (bisa dari beberapa laporan)
    for lp in laporan:
        if lp.jenis == "masuk":
            masuk.setdefault(lp.tanggal_tertulis, set()).update(b["sku"] for b in lp.baris if b.get("sku"))
    per_tgl = {}
    for lp in order:
        per_tgl.setdefault(lp.tanggal_tertulis, []).append(lp)
    for tgl, daftar in per_tgl.items():
        if len(daftar) < 2:
            continue
        tgl_lain = {lp.tanggal_tertulis for lp in order}
        for lp in daftar:
            kemarin = tgl - timedelta(days=1)
            sku_m = masuk.get(tgl)
            if kemarin in tgl_lain or sku_m is None or lp.belanja:
                continue
            sku_o = {b["sku"] for b in lp.baris if b.get("sku")}
            if sku_o and len(sku_o & sku_m) / len(sku_o) >= 0.6:
                lp.tanggal = kemarin
                lp.catatan = (f"Tertulis {tgl:%d-%m-%Y}, tetapi isinya cocok dengan barang masuk {tgl:%d-%m-%Y}; "
                              f"dianggap order {kemarin:%d-%m-%Y}.")
                tgl_lain.add(kemarin)
                break
    return laporan


_KARYAWAN = re.compile(r"kar[iy]?a?w")     # karyawan, karywan, karyawam, mkn karyawan, ...


def _bagian(baris: str) -> str | None:
    """Baris judul bagian: "*bar (depan) lafabrica* :", "# Bar kitchen lafabrica#", "*mkan karywan*"."""
    s = baris.lower()
    karyawan = bool(_KARYAWAN.search(s)) and len(re.findall(r"[a-z]+", s)) <= 4
    if karyawan:
        return BAGIAN["makan karyawan"]
    if not s.strip().startswith(("*", "#")) and "lafabrica" not in s:
        return None
    if re.search(r"\d", s):
        return None                               # "* gas 4 tbung (1 tabung sama bar kitchen)" adalah baris barang
    return _nama_bagian(s)


def normalkan_nama(nama: str) -> str:
    s = nama.lower()
    s = re.sub(r"[^a-z0-9./\s]", " ", s)
    for pola, ganti in _SINGKATAN:
        s = re.sub(pola, ganti, s)
    s = re.sub(r"\b(yg|yang|sedang|kupas|pesan|segar)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def urai_baris(teks: str) -> dict:
    """Satu baris barang -> nama, jumlah, satuan, isi per satuan (dari tanda kurung), keterangan."""
    asli = teks.strip()
    s = re.sub(r"^[\-\*•\s]+", "", asli)
    s = re.sub(r"^\d{1,2}[.)]\s+", "", s)                       # nomor urut daftar: "3. Timun 3 kg"
    s = s.replace("⁶", "").replace("¹/²", " 1/2")
    s = re.sub(r"(?i)\b(\d{1,3})\.(\d{3})(?=\s*(?:gr|g|gram|ml)\b)", r"\1\2", s)   # "1.585 gr" = 1585 g
    s = re.sub(r"(?i)\b0ns\b", "ons", s)                       # "1 0ns" -> "1 ons"
    s = re.sub(r"(?i)\bs(\d)", r"\1", s)                       # "s1bks" -> "1bks"
    ragu = []
    if re.search(r"(?i)\d\s*/\s+kg", s):                       # "Tomat 1/ kg": pecahan tidak lengkap
        s = re.sub(r"(?i)(\d)\s*/\s+(?=kg)", r"\1 ", s)
        ragu.append("jumlah tertulis tidak lengkap (\"1/ kg\"), dibaca 1 kg")
    s = re.sub(r"(?i)([a-z])(\d)", r"\1 \2", s)                 # "rawit1/4" -> "rawit 1/4"
    kurung = re.findall(r"\(([^()]*)\)?", s)
    utama = re.sub(r"\([^()]*\)?", " ", s)
    # "(sisa display dan 1 pack cadangan)" adalah sisa stok, bukan jumlah: angkanya tidak dipakai
    sisa = [k for k in kurung if re.search(r"(?i)\bsisa\b", k)]
    kurung = [k for k in kurung if k not in sisa]
    ket = "; ".join(k.strip() for k in sisa + kurung if k.strip() and (k in sisa or not re.search(r"\d", k)))
    out = {"teks": asli, "nama": utama.strip(), "jumlah": None, "satuan": None, "isi": None, "satuan_isi": None,
           "keterangan": ket, "rupiah": None, "ragu": "; ".join(ragu)}
    cands = list(_RE_JUMLAH.finditer(utama.lower()))
    bersatuan = [c for c in cands if c.group(2) and SATUAN[c.group(2)] != "rb"]
    harga = [c for c in cands if c.group(2) and SATUAN[c.group(2)] == "rb"]
    if bersatuan and harga:                                     # "kecap bango 3rb 2bks": 3rb = ukuran sachet
        out["rupiah"] = _angka(harga[0].group(1)) * 1000
    m = bersatuan[0] if bersatuan else (harga[0] if harga else (cands[-1] if cands else None))
    if m:
        out["nama"] = utama[:m.start()].strip(" -:")
        out["jumlah"] = _angka(m.group(1))
        sat = SATUAN.get((m.group(2) or "").lower())
        out["satuan"] = sat
        sisa = utama[m.end():].strip()
        if sisa:
            out["keterangan"] = "; ".join(x for x in (sisa, out["keterangan"]) if x)
        if sat == "rb":
            out["rupiah"] = out["jumlah"] * 1000
            out["jumlah"], out["satuan"] = None, None
            out["nama"] = re.sub(r"\s+", " ", utama.replace(m.group(0), " ")).strip(" -:")
        elif "*" in utama[m.start():m.end() + 2]:
            out["keterangan"] = (out["keterangan"] + "; " if out["keterangan"] else "") + utama[m.start():].strip()
    else:
        out["nama"] = utama.strip(" -:")
    # isi atau jumlah di dalam kurung: "760gr (1botol)", "2bks(200gr)", "( 2 kg )"
    for k in kurung:
        mk = _RE_JUMLAH.search(k.lower())
        if not mk:
            continue
        if out["satuan"] in WADAH and SATUAN.get(mk.group(2) or "") not in BERAT:
            # "1 dus( 6 bks 13 liter)": yang dipakai berat isi wadahnya, bukan banyaknya bungkus di dalamnya
            berat = [c for c in _RE_JUMLAH.finditer(k.lower()) if SATUAN.get(c.group(2) or "") in BERAT]
            if berat:
                mk = berat[-1]
                out["keterangan"] = "; ".join(x for x in (out["keterangan"], k.strip()) if x)
        if re.fullmatch(r"\s*\d+(?:[.,]\d+)?\s*gram\s*", k.lower()) and out["jumlah"] is not None:
            # gaya catatan bar belakang: "bubuk kopi 2 bks ( 2000 gram )" = berat total
            out["keterangan"] = "; ".join(x for x in (f"{out['jumlah']:g} {out['satuan']}", out["keterangan"]) if x)
            out["jumlah"], out["satuan"] = _angka(mk.group(1)), "g"
            continue
        n = _angka(mk.group(1))
        sk = SATUAN.get((mk.group(2) or "").lower())
        if sk == "rb":
            out["rupiah"] = n * 1000
            continue
        if out["jumlah"] is None:
            out["jumlah"], out["satuan"] = n, sk
        elif out["satuan"] in BERAT and sk not in BERAT:          # 760gr (1botol): ukuran x banyaknya
            out["isi"], out["satuan_isi"] = out["jumlah"], out["satuan"]
            out["jumlah"], out["satuan"] = n, sk
            out["berat_dulu"] = True                              # berat ditulis dulu: bisa juga berarti berat total
        elif sk in BERAT and out["satuan"] not in BERAT:          # 2bks(200gr): banyaknya x ukuran
            out["isi"], out["satuan_isi"] = n, sk
        elif sk in ("potong",):
            out["keterangan"] = (out["keterangan"] + "; " if out["keterangan"] else "") + k.strip()
    if out["jumlah"] is not None and out["satuan"] is None and out["isi"] is None:
        out["satuan"] = "tanpa satuan"
    out["nama"] = re.sub(r"\s+", " ", out["nama"]).strip()
    return out


def urai_laporan(lp: Laporan) -> list[dict]:
    bagian = lp.bagian
    rows = []
    for baris in lp.teks.splitlines():
        b = baris.strip()
        if not b:
            continue
        bg = _bagian(b)
        if bg:
            bagian = bg
            continue
        j = _judul(b, lp.tanggal_tertulis)
        if j:                                                 # sub-judul: "Orderan bar kitchen", "orderan waiters :"
            bagian = j["bagian"] or bagian
            continue
        low = b.lower()
        if low.startswith("noted"):
            note = b.split(":", 1)[1].strip() if ":" in b else ""
            if note and note != "-":
                lp.catatan = (lp.catatan + " " if lp.catatan else "") + note
            continue
        if low.startswith("terimakasih") or re.match(r"^(orderan|barang masuk)\b.*\d{4}", low):
            continue
        if re.fullmatch(r"[\-\*\s:]*", b) or low.rstrip(" :") in ("", "-"):
            continue
        r = urai_baris(b)
        if not r["nama"] and r["jumlah"] is None:
            continue
        r.update({"jenis": lp.jenis, "tanggal": lp.tanggal, "tanggal_tertulis": lp.tanggal_tertulis,
                  "laporan": lp.urutan, "bagian": bagian or TIDAK_DIKETAHUI})
        if lp.belanja:
            r["keterangan"] = "; ".join(x for x in (KET_BELANJA, r["keterangan"]) if x)
        rows.append(r)
    lp.baris = rows
    return rows


KET_BELANJA = "daftar belanja"


def tebak_bagian(rows: list[dict]) -> str | None:
    """Bagian untuk daftar yang judul bagiannya tidak ditulis (mis. "Barang masuk hari ini tnggl 8 november 2026"
    langsung diikuti barang kitchen): kelompok bagian yang paling banyak mengenali nama barangnya."""
    suara = {}
    for r in rows:
        nn = normalkan_nama(r["nama"])
        for (pola, *_), kelompok in zip(ALIAS, _KELOMPOK_ALIAS):
            if re.search(pola, nn):
                if kelompok:
                    suara[kelompok] = suara.get(kelompok, 0) + 1
                break
    if not suara:
        return None
    urut = sorted(suara.items(), key=lambda kv: -kv[1])
    return urut[0][0] if len(urut) == 1 or urut[0][1] > urut[1][1] else None


def buang_kiriman_ulang(laporan: list[Laporan]) -> None:
    """Laporan yang dikirim ulang (jenis dan tanggal sama, isi satu bagian sama persis) tidak dihitung dua kali:
    bagian yang sama persis dengan bagian itu di laporan sebelumnya dibuang dari laporan yang lebih baru."""
    terlihat = {}                                             # (jenis, tanggal, bagian, isi) -> nomor laporan
    for lp in laporan:
        per_bagian = {}
        for r in lp.baris:
            per_bagian.setdefault(r["bagian"], []).append(r)
        buang = {}
        for bg, rows in per_bagian.items():
            kunci = (lp.jenis, lp.tanggal_tertulis, bg, tuple(re.sub(r"\s+", " ", r["teks"].lower()).strip() for r in rows))
            if kunci in terlihat:
                buang[bg] = terlihat[kunci]
            else:
                terlihat[kunci] = lp.urutan
        if buang:
            lp.baris = [r for r in lp.baris if r["bagian"] not in buang]
            ket = ", ".join(f"{bg} (sama dengan laporan no. {n})" for bg, n in buang.items())
            lp.catatan = (lp.catatan + " " if lp.catatan else "") + f"Kiriman ulang, tidak dihitung dua kali: {ket}."


@dataclass
class Master:
    """Ringkasan data bahan untuk pencocokan: SKU -> nama, satuan dasar, isi kemasan, konversi satuan lain."""
    nama: dict
    satuan: dict
    kemasan: dict
    konversi: dict               # (sku, satuan baku) -> isi dalam satuan dasar

    @classmethod
    def dari_db(cls, db):
        from app.models import Bahan
        nama, satuan, kemasan, konversi = {}, {}, {}, {}
        for b in db.query(Bahan).all():
            nama[b.sku], satuan[b.sku], kemasan[b.sku] = b.nama, b.satuan, (b.kemasan_isi or 1.0)
            for u in b.satuan_lain:
                sat = SATUAN.get(u.satuan.strip().lower(), u.satuan.strip().lower())
                if not u.dasar and (u.konversi or 0) > 1:
                    konversi[(b.sku, sat)] = float(u.konversi)
            if (b.kemasan_nama or "").strip().lower() not in ("", "kemasan") and (b.kemasan_isi or 0) > 1:
                sat = SATUAN.get(b.kemasan_nama.strip().lower(), b.kemasan_nama.strip().lower())
                konversi.setdefault((b.sku, sat), float(b.kemasan_isi))
        return cls(nama, satuan, kemasan, konversi)

    @classmethod
    def dari_tabel(cls, master: pd.DataFrame):
        """Sama seperti dari_db, dari tabel master ml.master.susun_master() (dipakai pipeline baris perintah)."""
        nama, satuan, kemasan, konversi = {}, {}, {}, {}
        for r in master.to_dict("records"):
            sku = r["sku"]
            nama[sku], satuan[sku], kemasan[sku] = r["nama"], r["satuan"], float(r.get("kemasan_isi") or 1.0)
            for u in r.get("satuan_lain") or []:
                sat = SATUAN.get(str(u["satuan"]).strip().lower(), str(u["satuan"]).strip().lower())
                if float(u.get("konv") or 0) > 1:
                    konversi[(sku, sat)] = float(u["konv"])
            kn = str(r.get("kemasan_nama") or "").strip().lower()
            if kn not in ("", "kemasan") and float(r.get("kemasan_isi") or 0) > 1:
                konversi.setdefault((sku, SATUAN.get(kn, kn)), float(r["kemasan_isi"]))
        return cls(nama, satuan, kemasan, konversi)


def cocokkan(nama_norm: str, bagian: str):
    for pola, bg, hasil, ket in ALIAS:
        if bg is not None and bg != bagian:
            continue
        if re.search(pola, nama_norm):
            return hasil, ket
    return None, ""


WADAH = ("dus", "kardus", "crate")       # wadah besar: isinya tidak tertulis di catatan


def ke_satuan_dasar(sku: str, r: dict, M: Master):
    """Jumlah dalam satuan dasar bahan.

    Mengembalikan (jumlah atau None, cara konversi, asumsi). Konversi dari data bahan (satuan lain majoo) tidak
    dianggap asumsi; konversi dari tabel ISI_ASUMSI atau aturan tebakan dianggap asumsi dan baris diberi status
    "perlu dicek".
    """
    n, sat = r["jumlah"], r["satuan"]
    if n is None:
        return None, "", ""
    dasar_asli = M.satuan.get(sku) or ""
    dasar = dasar_asli.lower()
    berat_dasar = dasar in ("gram", "ml")
    if sat == "tanpa satuan" and n <= 1 and r.get("bagian") in ("Kitchen", "Makan karyawan"):
        # "Cabe caplak 1/4", "Wortel 1/4": pecahan tanpa satuan di kitchen ditulis dalam kg
        q, konv, a = ke_satuan_dasar(sku, {**r, "satuan": "kg"}, M)
        return q, konv, "; ".join(x for x in ("angka pecahan tanpa satuan dianggap kg", a) if x)
    if sat == "tanpa satuan" and n <= 25 and berat_dasar and r.get("bagian") in ("Kitchen", "Makan karyawan"):
        # "Beras 10": angka kecil tanpa satuan untuk bahan yang ditimbang ditulis dalam kg, bukan gram
        q, konv, a = ke_satuan_dasar(sku, {**r, "satuan": "kg"}, M)
        return q, konv, "; ".join(x for x in ("angka tanpa satuan dianggap kg", a) if x)
    isi, sat_isi = r.get("isi"), r.get("satuan_isi")
    k_master = M.konversi.get((sku, sat))
    a_tabel = ISI_ASUMSI.get((sku, sat))

    def dari_tabel():
        if a_tabel is None:
            return None, "", f"isi 1 {sat} belum diketahui"
        if a_tabel[0] is None:
            return None, "", a_tabel[1]
        return n * a_tabel[0], f"{n:g} {sat} x {a_tabel[0]:g} {dasar}", a_tabel[1]

    if isi is not None and sat_isi in BERAT and berat_dasar:
        ukuran = isi * BERAT[sat_isi]
        if sat in WADAH:
            if not r.get("berat_dulu"):
                # "1 dus (6 bks 13 liter)": tanda kurung menjelaskan isi wadahnya
                beda = (f"isi 1 {sat} tertulis {isi:g} {sat_isi} di catatan; data bahan mencatat {k_master:,.0f} g"
                        if k_master and abs(k_master - ukuran) > 1e-6 else "")
                return n * ukuran, f"{n:g} {sat} x {ukuran:g} g (isi tertulis di catatan)", beda
            if k_master and k_master > ukuran:
                return (n * k_master, f"{n:g} {sat} x {k_master:,.0f} g (data bahan)",
                        f"catatan menulis {isi:g} {sat_isi} per {sat}; dipakai isi {sat} dari data bahan")
            return dari_tabel()
        isi_biasa = k_master or (a_tabel[0] if a_tabel else None)
        ragu_total = n > 1 and r.get("berat_dulu")
        if ragu_total and isi_biasa:
            # "Totole 80gr(2bks)": bar menulis ukuran x banyaknya, kitchen kadang menulis berat total (banyaknya).
            # Dipilih bacaan yang paling dekat dengan isi kemasan yang biasa.
            harap = n * isi_biasa
            if abs(ukuran - harap) < abs(n * ukuran - harap):
                return ukuran, f"{ukuran:g} g ({n:g} {sat})", (
                    f"tertulis {isi:g} {sat_isi} ({n:g} {sat}): dibaca berat total karena 1 {sat} biasanya "
                    f"{isi_biasa:g} g")
        if ragu_total and r.get("bagian") == "Kitchen":
            return n * ukuran, f"{n:g} {sat} x {ukuran:g} g", (
                f"tertulis {isi:g} {sat_isi} ({n:g} {sat}): dibaca {n:g} x {ukuran:g} g; cek apakah itu berat total")
        return n * ukuran, f"{n:g} {sat} x {ukuran:g} g", ""
    if sat in BERAT and berat_dasar:
        return n * BERAT[sat], (f"{n:g} {sat} = {n * BERAT[sat]:g} g" if sat != "g" else ""), ""
    if sat in BERAT:
        k = M.konversi.get((sku, "kg"))
        kg = n * BERAT[sat] / 1000.0
        if k:
            return kg * k, f"{kg:g} kg x {k:g} {dasar}/kg (data bahan)", ""
        a = ISI_ASUMSI.get((sku, "kg"))
        if a and a[0] is not None:
            return kg * a[0], f"{kg:g} kg x {a[0]:g} {dasar}/kg", a[1]
        return None, "", a[1] if a else f"dicatat dalam {sat}, satuan dasar {dasar_asli}"
    if sat == "tanpa satuan":
        if berat_dasar:
            return n, "", "angka tanpa satuan dianggap gram"
        return n, "", f"angka tanpa satuan dianggap {dasar_asli}"
    if not berat_dasar and (sat == dasar or (sat in ("pcs", "butir", "keping") and dasar in ("pcs", "keping"))
                            or (sat in ("bungkus", "pack") and dasar == "pack")):
        return n, "", ""
    if sat == "ekor" and sku == "BB132":
        return n, f"{n:g} ekor = {n:g} Pcs", ("majoo mencatat Ayam Penyet dalam Pcs dengan Ekor = 1; catatan 1 Nov: "
                                             "5 ekor = 20 potong")
    if sat == "ekor" and sku == "BB176":
        return n * 8.0, f"{n:g} ekor x 8 Pcs", "1 ekor ayam special dianggap 1 kg = 8 potong (catatan 1 Nov)"
    if k_master and sat not in WADAH:
        return n * k_master, f"{n:g} {sat} x {k_master:g} {dasar} (data bahan)", ""
    if k_master:
        return n * k_master, f"{n:g} {sat} x {k_master:g} {dasar} (data bahan)", ""
    return dari_tabel()


def petakan(rows: list[dict], M: Master) -> pd.DataFrame:
    out = []
    for r in rows:
        nn = normalkan_nama(r["nama"])
        r = dict(r)
        r["nama_normal"] = nn
        if r["bagian"] == BAGIAN["makan karyawan"]:
            hasil, ket = KARYAWAN, ""
        elif r["rupiah"] is not None and r["jumlah"] is None:
            hasil, ket = RUPIAH, ""
        else:
            hasil, ket = cocokkan(nn, r["bagian"])
        sku = hasil if hasil in M.nama else None
        r["sku"] = sku
        r["nama_bahan"] = M.nama.get(sku, "")
        r["satuan_dasar"] = M.satuan.get(sku, "")
        r["konversi"] = ""
        asumsi = [ket] if ket and sku else []
        if r.get("ragu") and sku:
            asumsi.append(r["ragu"])
        if sku is None:
            r["status"] = hasil if hasil in (KARYAWAN, RUPIAH, BELUM_ADA, BUKAN_BAHAN) else BELUM_ADA
            r["jumlah_dasar"] = None
            if hasil is None:
                asumsi.append("nama belum dikenali")
            elif ket:
                asumsi.append(ket)
        elif r["jumlah"] is None:
            r["status"], r["jumlah_dasar"] = TANPA_JUMLAH, None
        else:
            q, konv, a = ke_satuan_dasar(sku, r, M)
            r["jumlah_dasar"], r["konversi"] = q, konv
            if a:
                asumsi.append(a)
            r["status"] = PERLU_DICEK if (q is None or asumsi) else DIPAKAI
        r["asumsi"] = "; ".join(asumsi)
        out.append(r)
    kolom = ["jenis", "tanggal", "tanggal_tertulis", "laporan", "bagian", "teks", "nama", "jumlah", "satuan", "isi",
             "satuan_isi", "rupiah", "keterangan", "nama_normal", "sku", "nama_bahan", "satuan_dasar", "jumlah_dasar",
             "konversi", "status", "asumsi"]
    return pd.DataFrame(out, columns=kolom)


def rapikan(teks: str, M: Master) -> tuple[pd.DataFrame, list[Laporan]]:
    """Teks catatan -> tabel baris terstruktur (order dan barang masuk) dan daftar laporan."""
    laporan = pisah_laporan(teks)
    for lp in laporan:
        rows = urai_laporan(lp)
        tanpa = [r for r in rows if r["bagian"] == TIDAK_DIKETAHUI]
        if tanpa:
            bg = tebak_bagian(tanpa)
            if bg:
                for r in tanpa:
                    r["bagian"] = bg
                lp.catatan = (lp.catatan + " " if lp.catatan else "") + (
                    f"Bagian tidak ditulis; dianggap {bg} dari isi barangnya.")
    buang_kiriman_ulang(laporan)
    semua = []
    for lp in laporan:
        df = petakan(lp.baris, M)
        lp.baris = df.to_dict("records")
        semua.append(df)
    koreksi_tanggal_order(laporan)
    for lp, df in zip(laporan, semua):
        df["tanggal"] = lp.tanggal
    df = pd.concat(semua, ignore_index=True) if semua else petakan([], M)
    return df, laporan


def rekap_masuk(df: pd.DataFrame) -> pd.DataFrame:
    """Barang masuk per tanggal per SKU (satuan dasar), hanya baris yang dipakai simulasi."""
    m = df[(df["jenis"] == "masuk") & df["status"].isin(STATUS_DIPAKAI) & df["jumlah_dasar"].notna()]
    return (m.groupby(["tanggal", "sku", "nama_bahan", "satuan_dasar"], as_index=False)["jumlah_dasar"].sum()
            .sort_values(["tanggal", "sku"]))


def order_vs_masuk(df: pd.DataFrame) -> pd.DataFrame:
    """Order hari H dibandingkan barang masuk hari H+1 per SKU."""
    belanja = (df["keterangan"].fillna("").astype(str).str.startswith(KET_BELANJA) if "keterangan" in df
               else pd.Series(False, index=df.index))
    o = df[(df["jenis"] == "order") & df["sku"].notna() & ~belanja].copy()
    m = df[(df["jenis"] == "masuk") & df["sku"].notna()].copy()
    o["tanggal_tiba"] = o["tanggal"].map(lambda d: d + timedelta(days=1))
    og = o.groupby(["tanggal", "tanggal_tiba", "sku", "nama_bahan"], as_index=False).agg(
        jumlah_order=("jumlah_dasar", lambda s: s.sum(min_count=1)), teks_order=("teks", "; ".join))
    mg = m.groupby(["tanggal", "sku"], as_index=False).agg(jumlah_masuk=("jumlah_dasar", lambda s: s.sum(min_count=1)),
                                                         teks_masuk=("teks", "; ".join))
    mg = mg.rename(columns={"tanggal": "tanggal_tiba"})
    tgl_masuk = set(m["tanggal"])
    g = og.merge(mg, on=["tanggal_tiba", "sku"], how="left")
    g = g[g["tanggal_tiba"].isin(tgl_masuk)]

    def status(r):
        if pd.isna(r["teks_masuk"]):
            return "tidak datang"
        if pd.isna(r["jumlah_order"]):
            return "datang (jumlah order tidak ditulis)"
        if pd.isna(r["jumlah_masuk"]):
            return "datang (jumlah masuk belum diketahui)"
        if abs(r["jumlah_masuk"] - r["jumlah_order"]) <= 1e-6:
            return "sesuai"
        return "lebih" if r["jumlah_masuk"] > r["jumlah_order"] else "kurang"
    g["status"] = g.apply(status, axis=1)
    return g.sort_values(["tanggal", "sku"])


# ---------------------------------------------------------------------------------------------- Excel terstruktur
KOLOM_EXCEL = [
    # (judul kolom, kunci, lebar)
    ("Tanggal", "tanggal", 11),
    ("Bagian", "bagian", 13),
    ("Catatan Asli", "teks", 40),
    ("Nama Barang", "nama", 26),
    ("Jumlah", "jumlah", 8),
    ("Satuan", "satuan", 10),
    ("Isi per Satuan", "isi_satuan", 11),
    ("SKU", "sku", 9),
    ("Nama Bahan (majoo)", "nama_bahan", 30),
    ("Satuan Dasar", "satuan_dasar", 10),
    ("Jumlah (Satuan Dasar)", "jumlah_dasar", 13),
    ("Cara Konversi", "konversi", 30),
    ("Status", "status", 22),
    ("Asumsi / Perlu Dicek", "asumsi", 60),
    ("Keterangan", "keterangan", 22),
]
SEMUA_STATUS = [DIPAKAI, PERLU_DICEK, TANPA_JUMLAH, BELUM_ADA, BUKAN_BAHAN, KARYAWAN, RUPIAH]
ARTI_STATUS = {
    DIPAKAI: "Cocok dengan data bahan dan jumlahnya jelas. Dipakai K1 aktual.",
    PERLU_DICEK: "Dipakai K1 aktual, tetapi nama atau isi kemasannya memakai asumsi. Cek dengan staf cafe.",
    TANPA_JUMLAH: "Barang disebut tanpa jumlah (biasanya order \"sisa display\"). Tidak dipakai.",
    BELUM_ADA: "Bahan belum terdaftar di data bahan majoo/aplikasi. Tidak dipakai.",
    BUKAN_BAHAN: "Perlengkapan (cup, sedotan, plastik, ...). Tidak dipakai.",
    KARYAWAN: "Belanja makan karyawan, tidak tercatat di stok keluar menu. Tidak dipakai.",
    RUPIAH: "Jumlah ditulis dalam rupiah. Tidak dipakai.",
}


def isi_satuan_teks(r) -> str:
    isi, sat = r.get("isi"), r.get("satuan_isi")
    if isi is None or (isinstance(isi, float) and pd.isna(isi)) or not sat:
        return ""
    return f"{isi:g} {sat}"


def _sel_tanggal(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return pd.Timestamp(v).to_pydatetime()


def rekap_harian_lebar(df: pd.DataFrame) -> pd.DataFrame:
    """Barang masuk per SKU (baris) x tanggal (kolom) dalam satuan dasar."""
    r = rekap_masuk(df)
    if r.empty:
        return pd.DataFrame()
    w = r.pivot_table(index=["sku", "nama_bahan", "satuan_dasar"], columns="tanggal", values="jumlah_dasar",
                      aggfunc="sum")
    hari = pd.date_range(min(df.loc[df["jenis"] == "masuk", "tanggal"]), max(df.loc[df["jenis"] == "masuk", "tanggal"]))
    w.columns = [pd.Timestamp(c) for c in w.columns]
    w = w.reindex(columns=hari)
    w["Total"] = w.sum(axis=1)
    return w.reset_index()


def daftar_perlu_dicek(df: pd.DataFrame) -> pd.DataFrame:
    """Hal yang perlu dikonfirmasi ke cafe untuk barang masuk: satu baris per bahan (atau per barang yang belum
    terdaftar), berisi semua asumsi yang dipakai, tanggal, dan contoh catatan."""
    kol = ["status", "sku", "nama_bahan", "asumsi", "n", "tanggal", "contoh", "jumlah_dasar"]
    x = df[(df["jenis"] == "masuk") & df["status"].isin([PERLU_DICEK, BELUM_ADA, RUPIAH, TANPA_JUMLAH])].copy()
    if x.empty:
        return pd.DataFrame(columns=kol)
    x["sku"] = x["sku"].fillna("")
    x["asumsi"] = x["asumsi"].fillna("")
    x["kunci"] = x["sku"].where(x["sku"] != "", x["asumsi"].where(x["asumsi"] != "", x["nama_normal"]))
    x["nama_tampil"] = x["nama_bahan"].where(x["sku"] != "", x["nama_normal"])

    def gabung_asumsi(s):
        bag = []
        for a in s:
            for b in str(a).split("; "):
                if b and b not in bag:
                    bag.append(b)
        return "; ".join(bag)

    g = x.groupby(["status", "kunci"], dropna=False)
    out = g.agg(sku=("sku", "first"), nama_bahan=("nama_tampil", lambda s: " / ".join(dict.fromkeys(s))),
                asumsi=("asumsi", gabung_asumsi), n=("teks", "size"),
                tanggal=("tanggal", lambda s: ", ".join(f"{d:%d/%m}" for d in sorted({pd.Timestamp(v) for v in s}))),
                contoh=("teks", lambda s: " | ".join(list(dict.fromkeys(t.strip(" -*") for t in s))[:3])),
                jumlah_dasar=("jumlah_dasar", lambda s: s.sum(min_count=1))).reset_index()
    urut_status = {PERLU_DICEK: 0, BELUM_ADA: 1, TANPA_JUMLAH: 2, RUPIAH: 3}
    out["_s"] = out["status"].map(urut_status)
    return out.sort_values(["_s", "n", "sku"], ascending=[True, False, True])[kol]


def tulis_excel(df: pd.DataFrame, laporan: list | None, tujuan, judul_sumber: str = ""):
    """Tulis catatan yang sudah dirapikan ke Excel (tujuan: path atau file-like)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    hijau, kuning, abu, merah = "E3F6EE", "FFF4CC", "EEEEEE", "FBE3E3"
    warna_status = {DIPAKAI: hijau, PERLU_DICEK: kuning, BELUM_ADA: merah, TANPA_JUMLAH: abu, BUKAN_BAHAN: abu,
                    KARYAWAN: abu, RUPIAH: abu}
    kepala_font = Font(bold=True, color="FFFFFF")
    kepala_isi = PatternFill("solid", fgColor="1F6F5C")
    tipis = Side(style="thin", color="D0D0D0")
    garis = Border(bottom=tipis)
    wb = Workbook()

    def kepala(ws, judul_kolom, lebar, baris=1):
        for j, (t, w) in enumerate(zip(judul_kolom, lebar), start=1):
            c = ws.cell(row=baris, column=j, value=t)
            c.font, c.fill = kepala_font, kepala_isi
            c.alignment = Alignment(wrap_text=True, vertical="center")
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.row_dimensions[baris].height = 30
        ws.freeze_panes = ws.cell(row=baris + 1, column=1)

    def lembar_baris(nama, jenis):
        ws = wb.create_sheet(nama)
        kol = list(KOLOM_EXCEL)
        if jenis == "order":
            kol.insert(1, ("Tanggal Tertulis", "tanggal_tertulis", 11))
        kepala(ws, [k[0] for k in kol], [k[2] for k in kol])
        x = df[df["jenis"] == jenis]
        i_status = [k[1] for k in kol].index("status") + 1
        for i, r in enumerate(x.to_dict("records"), start=2):
            if "isi" in r:
                r["isi_satuan"] = isi_satuan_teks(r)
            for j, (_, key, _) in enumerate(kol, start=1):
                v = r.get(key)
                if key in ("tanggal", "tanggal_tertulis"):
                    v = _sel_tanggal(v)
                elif isinstance(v, float) and pd.isna(v):
                    v = None
                c = ws.cell(row=i, column=j, value=v)
                c.border = garis
                if key in ("tanggal", "tanggal_tertulis"):
                    c.number_format = "DD/MM/YYYY"
                elif key in ("jumlah", "jumlah_dasar"):
                    c.number_format = "#,##0.##"
                elif key in ("teks", "asumsi", "konversi"):
                    c.alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(row=i, column=i_status).fill = PatternFill("solid", fgColor=warna_status.get(r["status"], abu))
        n = max(len(x) + 1, 2)
        ws.auto_filter.ref = f"A1:{get_column_letter(len(kol))}{n}"
        dv = DataValidation(type="list", formula1='"' + ",".join(SEMUA_STATUS) + '"', allow_blank=False)
        dv.add(f"{get_column_letter(i_status)}2:{get_column_letter(i_status)}{max(n, 500)}")
        ws.add_data_validation(dv)
        return ws

    # ---- Ringkasan
    ws = wb.active
    ws.title = "Ringkasan"
    ws.column_dimensions["A"].width = 34
    for c in "BCDEFGH":
        ws.column_dimensions[c].width = 16
    m = df[df["jenis"] == "masuk"]
    o = df[df["jenis"] == "order"]
    tgl = sorted(set(df["tanggal"]))
    baris = [
        ("Catatan Order dan Barang Masuk Lafabrica Coffee", None),
        (f"Sumber: {judul_sumber}" if judul_sumber else "Sumber: laporan WhatsApp harian cafe", None),
        (f"Periode: {pd.Timestamp(tgl[0]):%d/%m/%Y} s.d. {pd.Timestamp(tgl[-1]):%d/%m/%Y}" if tgl else "Periode: -", None),
        ("", None),
    ]
    for t, _ in baris:
        ws.append([t])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Status", "Barang masuk", "Order", "Arti"])
    for c in ws[5]:
        c.font, c.fill = kepala_font, kepala_isi
    for st in SEMUA_STATUS:
        ws.append([st, int((m["status"] == st).sum()), int((o["status"] == st).sum()), ARTI_STATUS[st]])
        ws.cell(row=ws.max_row, column=1).fill = PatternFill("solid", fgColor=warna_status[st])
    ws.append(["Jumlah baris", len(m), len(o)])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    ws.append([])
    rk = rekap_masuk(df)
    ws.append(["Barang masuk untuk K1 aktual", f"{len(rk)} pasangan tanggal-bahan, {rk['sku'].nunique()} bahan, "
               f"{m['tanggal'].nunique()} hari laporan"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    ovm = order_vs_masuk(df)
    if len(ovm):
        hit = ovm["status"].value_counts()
        ws.append(["Order hari H vs barang masuk H+1", ", ".join(f"{k}: {v}" for k, v in hit.items())])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    ws.append([])
    ws.append(["Cara memakai file ini"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    for t in [
        "1. Buka lembar \"Perlu Dicek\" (barang masuk saja) dan konfirmasi setiap asumsi ke staf cafe.",
        "2. Perbaiki baris di lembar \"Barang Masuk\" bila perlu: kolom SKU, Jumlah (Satuan Dasar), dan Status.",
        "   Setelah dicek, ubah Status \"perlu dicek\" menjadi \"dipakai\" (atau status lain bila barang tidak dipakai).",
        "3. Impor file ini di aplikasi: Inventori > Kelola Stok > Catatan Barang Masuk > Impor Excel.",
        "   Saat impor yang dibaca adalah Tanggal, Bagian, Catatan Asli, SKU, Jumlah (Satuan Dasar), dan Status.",
        "4. K1 aktual memakai baris berstatus \"dipakai\" dan \"perlu dicek\" yang jumlah satuan dasarnya terisi.",
        "Lembar \"Rekap Masuk Harian\" berisi jumlah barang masuk per bahan per hari (satuan dasar majoo).",
        "Lembar \"Order vs Masuk\" membandingkan order hari H dengan barang yang datang hari H+1 (lead time 1 hari).",
    ]:
        ws.append([t])
    if laporan:
        ws.append([])
        ws.append(["Koreksi tanggal dan catatan laporan"])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        for lp in laporan:
            if lp.catatan:
                ws.append([f"{'Order' if lp.jenis == 'order' else 'Barang masuk'} {lp.tanggal_tertulis:%d/%m/%Y}",
                           lp.catatan])

    # ---- baris
    lembar_baris("Barang Masuk", "masuk")
    lembar_baris("Order", "order")

    # ---- rekap harian
    ws = wb.create_sheet("Rekap Masuk Harian")
    w = rekap_harian_lebar(df)
    if len(w):
        hari = [c for c in w.columns if isinstance(c, pd.Timestamp)]
        judul_kol = ["SKU", "Nama Bahan", "Satuan Dasar"] + [f"{h:%d/%m}" for h in hari] + ["Total"]
        kepala(ws, judul_kol, [9, 30, 10] + [9] * len(hari) + [11])
        ws.freeze_panes = "D2"
        for i, r in enumerate(w.itertuples(index=False), start=2):
            vals = list(r)
            for j, v in enumerate(vals, start=1):
                v = None if isinstance(v, float) and pd.isna(v) else v
                c = ws.cell(row=i, column=j, value=v)
                c.border = garis
                if j > 3:
                    c.number_format = "#,##0.##"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(judul_kol))}{len(w) + 1}"

    # ---- order vs masuk
    ws = wb.create_sheet("Order vs Masuk")
    judul_kol = ["Tanggal Order", "Tanggal Tiba (H+1)", "SKU", "Nama Bahan", "Catatan Order", "Jumlah Order",
                 "Catatan Masuk", "Jumlah Masuk", "Selisih", "Status"]
    kepala(ws, judul_kol, [12, 12, 9, 30, 34, 12, 34, 12, 11, 22])
    for i, r in enumerate(ovm.to_dict("records"), start=2):
        jo, jm = r["jumlah_order"], r["jumlah_masuk"]
        sel = (jm - jo) if pd.notna(jo) and pd.notna(jm) else None
        vals = [_sel_tanggal(r["tanggal"]), _sel_tanggal(r["tanggal_tiba"]), r["sku"], r["nama_bahan"],
                r["teks_order"], None if pd.isna(jo) else jo, None if pd.isna(r["teks_masuk"]) else r["teks_masuk"],
                None if pd.isna(jm) else jm, sel, r["status"]]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(row=i, column=j, value=v)
            c.border = garis
            if j in (1, 2):
                c.number_format = "DD/MM/YYYY"
            elif j in (6, 8, 9):
                c.number_format = "#,##0.##"
            elif j in (5, 7):
                c.alignment = Alignment(wrap_text=True, vertical="top")
        warna = {"sesuai": hijau, "tidak datang": merah, "kurang": kuning, "lebih": kuning}.get(r["status"], abu)
        ws.cell(row=i, column=10).fill = PatternFill("solid", fgColor=warna)
    ws.auto_filter.ref = f"A1:J{max(len(ovm) + 1, 2)}"

    # ---- perlu dicek
    ws = wb.create_sheet("Perlu Dicek")
    pd_ = daftar_perlu_dicek(df)
    judul_kol = ["Status", "SKU", "Nama Bahan / Barang", "Yang Perlu Dicek", "Jumlah Baris", "Tanggal",
                 "Contoh Catatan", "Jawaban / Koreksi dari Cafe"]
    kepala(ws, judul_kol, [20, 9, 28, 62, 9, 26, 50, 34])
    for i, r in enumerate(pd_.to_dict("records"), start=2):
        vals = [r["status"], r["sku"] or None, r["nama_bahan"], r["asumsi"], int(r["n"]), r["tanggal"],
                r["contoh"], None]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(row=i, column=j, value=v)
            c.border = garis
            if j in (4, 6, 7):
                c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=i, column=1).fill = PatternFill("solid", fgColor=warna_status.get(r["status"], abu))
    ws.auto_filter.ref = f"A1:H{max(len(pd_) + 1, 2)}"

    # ---- laporan
    if laporan:
        ws = wb.create_sheet("Laporan")
        kepala(ws, ["No", "Jenis", "Tanggal Tertulis", "Tanggal Dipakai", "Jumlah Baris", "Baris Bahan Dipakai",
                    "Catatan"], [5, 13, 13, 13, 11, 13, 80])
        for i, lp in enumerate(laporan, start=2):
            n_pakai = sum(1 for b in lp.baris if b.get("status") in STATUS_DIPAKAI)
            vals = [lp.urutan, "barang masuk" if lp.jenis == "masuk" else "order", _sel_tanggal(lp.tanggal_tertulis),
                    _sel_tanggal(lp.tanggal), len(lp.baris), n_pakai, lp.catatan]
            for j, v in enumerate(vals, start=1):
                c = ws.cell(row=i, column=j, value=v)
                c.border = garis
                if j in (3, 4):
                    c.number_format = "DD/MM/YYYY"
                if j == 7:
                    c.alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(tujuan)


def baca_excel(berkas, M: Master) -> pd.DataFrame:
    """Baca kembali Excel hasil tulis_excel (yang mungkin sudah dikoreksi pengguna).

    Yang dibaca: Tanggal, Bagian, Catatan Asli, Nama Barang, Jumlah, Satuan, SKU, Jumlah (Satuan Dasar), Status,
    Asumsi / Perlu Dicek, Cara Konversi. Nama bahan dan satuan dasar diambil ulang dari data bahan sesuai SKU.
    """
    xl = pd.ExcelFile(berkas, engine="openpyxl")
    bagian = []
    for sheet, jenis in (("Barang Masuk", "masuk"), ("Order", "order")):
        if sheet not in xl.sheet_names:
            continue
        x = xl.parse(sheet)
        if "Tanggal" not in x.columns or "SKU" not in x.columns:
            continue
        x = x[x["Tanggal"].notna()]
        out = pd.DataFrame({
            "jenis": jenis,
            "tanggal": pd.to_datetime(x["Tanggal"], dayfirst=True).dt.date,
            "tanggal_tertulis": (pd.to_datetime(x["Tanggal Tertulis"], dayfirst=True).dt.date
                                 if "Tanggal Tertulis" in x else pd.to_datetime(x["Tanggal"], dayfirst=True).dt.date),
            "bagian": x.get("Bagian", "").fillna("") if "Bagian" in x else "",
            "teks": x.get("Catatan Asli", pd.Series("", index=x.index)).fillna("").astype(str),
            "nama": x.get("Nama Barang", pd.Series("", index=x.index)).fillna("").astype(str),
            "jumlah": pd.to_numeric(x.get("Jumlah"), errors="coerce") if "Jumlah" in x else None,
            "satuan": x.get("Satuan", pd.Series("", index=x.index)).fillna("").astype(str),
            "isi_satuan": x.get("Isi per Satuan", pd.Series("", index=x.index)).fillna("").astype(str),
            "sku": x["SKU"].map(lambda v: str(v).strip() if pd.notna(v) and str(v).strip() else None),
            "jumlah_dasar": pd.to_numeric(x.get("Jumlah (Satuan Dasar)"), errors="coerce"),
            "konversi": x.get("Cara Konversi", pd.Series("", index=x.index)).fillna("").astype(str),
            "status": x.get("Status", pd.Series(DIPAKAI, index=x.index)).fillna("").astype(str).str.strip().str.lower(),
            "asumsi": x.get("Asumsi / Perlu Dicek", pd.Series("", index=x.index)).fillna("").astype(str),
        })
        bagian.append(out)
    if not bagian:
        raise ValueError("Lembar \"Barang Masuk\" atau \"Order\" dengan kolom Tanggal dan SKU tidak ditemukan.")
    df = pd.concat(bagian, ignore_index=True)
    tidak_dikenal = sorted({s for s in df["sku"].dropna() if s not in M.nama})
    if tidak_dikenal:
        raise ValueError("SKU tidak ada di data bahan: " + ", ".join(tidak_dikenal[:10]))
    salah = sorted(set(df["status"]) - set(SEMUA_STATUS))
    if salah:
        raise ValueError(f"Status tidak dikenal: {', '.join(salah)}. Pilihan: {', '.join(SEMUA_STATUS)}")
    df["nama_bahan"] = df["sku"].map(lambda s: M.nama.get(s, "") if s else "")
    df["satuan_dasar"] = df["sku"].map(lambda s: M.satuan.get(s, "") if s else "")
    pakai_tanpa_sku = df["status"].isin(STATUS_DIPAKAI) & df["sku"].isna()
    df.loc[pakai_tanpa_sku, "status"] = BELUM_ADA
    return df


# ---------------------------------------------------------------------------------------------- basis data
def simpan_ke_db(db, df: pd.DataFrame, sumber: str = "", oleh: str = "") -> dict:
    """Simpan baris catatan ke tabel catatan_barang.

    Baris lama dengan jenis dan tanggal yang sama diganti, jadi mengimpor ulang catatan (atau Excel yang sudah
    dikoreksi) untuk hari yang sama tidak menggandakan data.
    """
    from sqlalchemy import insert

    from app.models import Bahan, CatatanBarang
    if df.empty:
        return {"baris": 0, "masuk": 0, "order": 0, "hari_masuk": [], "perlu_dicek": 0}
    ids = {s: i for s, i in db.query(Bahan.sku, Bahan.id).all()}
    for jenis in ("masuk", "order"):
        tgl = sorted(set(df.loc[df["jenis"] == jenis, "tanggal"]))
        if tgl:
            (db.query(CatatanBarang).filter(CatatanBarang.jenis == jenis, CatatanBarang.tanggal.in_(tgl))
             .delete(synchronize_session=False))

    def teks(v, n):
        return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)[:n]

    def angka(v):
        return None if v is None or pd.isna(v) else float(v)

    rows = []
    for r in df.to_dict("records"):
        isi = r.get("isi_satuan") if "isi_satuan" in r else isi_satuan_teks(r)
        rows.append({
            "jenis": r["jenis"], "tanggal": pd.Timestamp(r["tanggal"]).date(),
            "tanggal_tertulis": pd.Timestamp(r["tanggal_tertulis"]).date() if pd.notna(r.get("tanggal_tertulis"))
            else None,
            "bagian": teks(r.get("bagian"), 30), "teks": teks(r.get("teks"), 300), "nama": teks(r.get("nama"), 150),
            "jumlah": angka(r.get("jumlah")), "satuan": teks(r.get("satuan"), 30), "isi_satuan": teks(isi, 30),
            "bahan_id": ids.get(r.get("sku")), "jumlah_dasar": angka(r.get("jumlah_dasar")),
            "konversi": teks(r.get("konversi"), 120), "status": teks(r.get("status"), 30),
            "asumsi": teks(r.get("asumsi"), 300), "keterangan": teks(r.get("keterangan"), 150),
            "sumber": sumber[:120], "dibuat_oleh": oleh[:50],
        })
    db.execute(insert(CatatanBarang), rows)
    db.commit()
    m = df[df["jenis"] == "masuk"]
    return {"baris": len(rows), "masuk": len(m), "order": len(df) - len(m),
            "hari_masuk": sorted({pd.Timestamp(t).date() for t in m["tanggal"]}),
            "perlu_dicek": int((m["status"] == PERLU_DICEK).sum()),
            "dipakai": int(m["status"].isin(STATUS_DIPAKAI).sum())}


def dari_db(db, jenis: str | None = None) -> pd.DataFrame:
    """Isi tabel catatan_barang sebagai DataFrame dengan kolom yang sama seperti hasil rapikan()."""
    from app.models import Bahan, CatatanBarang
    q = db.query(CatatanBarang, Bahan.sku, Bahan.nama, Bahan.satuan).outerjoin(Bahan, Bahan.id == CatatanBarang.bahan_id)
    if jenis:
        q = q.filter(CatatanBarang.jenis == jenis)
    rows = []
    for c, sku, nama_bahan, satuan in q.order_by(CatatanBarang.tanggal, CatatanBarang.jenis, CatatanBarang.id).all():
        rows.append({"id": c.id, "jenis": c.jenis, "tanggal": c.tanggal, "tanggal_tertulis": c.tanggal_tertulis,
                     "bagian": c.bagian, "teks": c.teks, "nama": c.nama, "jumlah": c.jumlah, "satuan": c.satuan,
                     "isi_satuan": c.isi_satuan, "rupiah": None, "keterangan": c.keterangan,
                     "nama_normal": normalkan_nama(c.nama), "sku": sku, "nama_bahan": nama_bahan or "",
                     "satuan_dasar": satuan or "", "jumlah_dasar": c.jumlah_dasar, "konversi": c.konversi,
                     "status": c.status, "asumsi": c.asumsi, "sumber": c.sumber})
    kolom = ["id", "jenis", "tanggal", "tanggal_tertulis", "bagian", "teks", "nama", "jumlah", "satuan", "isi_satuan",
             "rupiah", "keterangan", "nama_normal", "sku", "nama_bahan", "satuan_dasar", "jumlah_dasar", "konversi",
             "status", "asumsi", "sumber"]
    df = pd.DataFrame(rows, columns=kolom)
    df["jumlah_dasar"] = pd.to_numeric(df["jumlah_dasar"], errors="coerce")
    return df


def data_k1_aktual(df: pd.DataFrame) -> dict | None:
    """Masukan simulasi K1 aktual dari catatan barang masuk.

    baris : DataFrame tanggal (Timestamp), sku, jumlah (satuan dasar; NaN = jumlah belum diketahui)
    hari  : tanggal yang punya laporan barang masuk. Pada hari berlaporan, bahan yang tidak disebut dianggap
            tidak datang (0); hari tanpa laporan tidak diketahui sehingga tidak dipakai.
    """
    m = df[df["jenis"] == "masuk"]
    if m.empty:
        return None
    pakai = m[m["status"].isin(STATUS_DIPAKAI) & m["sku"].notna()]
    baris = pd.DataFrame({"tanggal": pd.to_datetime(pakai["tanggal"]), "sku": pakai["sku"].astype(str),
                          "jumlah": pd.to_numeric(pakai["jumlah_dasar"], errors="coerce")})
    return {"baris": baris.reset_index(drop=True), "hari": sorted(pd.to_datetime(m["tanggal"].unique()))}


def dari_folder(folder, M: Master) -> tuple[pd.DataFrame, list]:
    """Rapikan semua file .txt di folder (dipakai isi awal basis data dan pipeline baris perintah)."""
    from pathlib import Path
    files = sorted(Path(folder).glob("*.txt"))
    if not files:
        return petakan([], M), []
    return rapikan("\n".join(f.read_text(encoding="utf-8") for f in files), M)

