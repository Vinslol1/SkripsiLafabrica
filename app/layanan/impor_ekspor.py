"""Impor dan ekspor Excel: Daftar Bahan Baku (format majoo + parameter PrediStok), stok keluar, opname, laporan."""
import io
import math
import re
from datetime import date, datetime

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

import config as C
from app.layanan import pengaturan as PG
from app.models import Bahan, MutasiStok, PencatatanHarian, SatuanBahan, StokKeluar

KUNING = PatternFill("solid", fgColor="FFF2CC")
HIJAU = PatternFill("solid", fgColor="D9F2EA")
ABU = PatternFill("solid", fgColor="EEEEEE")
TEBAL = Font(bold=True)

KOLOM_PARAMETER = [
    # (judul kolom, atribut, penanda asumsi)
    ("SKU", "sku", None),
    ("Nama Bahan", "nama", None),
    ("Satuan Dasar", "satuan", None),
    ("Kategori", "kategori", None),
    ("Nama Kemasan Beli", "kemasan_nama", "kemasan"),
    ("Isi Kemasan (satuan dasar)", "kemasan_isi", "kemasan"),
    ("Harga Beli per Satuan Dasar (Rp)", "harga_satuan", "harga"),
    ("Masa Simpan (hari)", "masa_simpan", "masa_simpan"),
    ("Lead Time (hari)", "lead_time", "lead_time"),
    ("Kapasitas Simpan Maks (kemasan)", "maks_kelipatan", "kapasitas"),
    ("Biaya Kehabisan per Satuan (Rp)", "biaya_kehabisan", "biaya_kehabisan"),
    ("Dimonitor (Y/T)", "monitor", None),
]
JUDUL_KONFIRMASI = "Data sudah benar (Y/T)"
JUDUL_KETERANGAN = "Keterangan nilai sementara"

KETERANGAN_ASUMSI = {
    "harga": "harga diperkirakan dari HPP resep majoo",
    "kemasan": "ukuran kemasan beli belum diketahui",
    "masa_simpan": "masa simpan memakai nilai umum kelompok bahan",
    "lead_time": "lead time pemasok diasumsikan 1 hari",
    "kapasitas": "kapasitas simpan belum diisi (dihitung otomatis dari data pemakaian)",
    "biaya_kehabisan": "biaya kehabisan dari margin menu",
}


# ---------------------------------------------------------------------- utilitas
def angka(x):
    """Angka dari sel Excel/teks gaya Indonesia: '97.076' -> 97076, '(195)' -> -195, '1,5' -> 1.5."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip().replace(" ", "").replace("Rp", "")
    if s in ("", "-", "nan", "None"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def baca_excel(data: bytes, **kw) -> dict:
    """Semua sheet sebagai DataFrame tanpa header; pakai calamine bila openpyxl gagal (file majoo)."""
    for engine in ("calamine", "openpyxl"):
        try:
            return pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, engine=engine, **kw)
        except Exception:  # noqa: BLE001
            continue
    raise ValueError("File tidak dapat dibaca. Pastikan formatnya .xlsx.")


def _cari_header(df: pd.DataFrame, wajib) -> int | None:
    for i in range(min(len(df), 15)):
        sel = [str(v).strip().lower() for v in df.iloc[i].values]
        if all(any(w in s for s in sel) for w in wajib):
            return i
    return None


def _dengan_header(df: pd.DataFrame, i: int) -> pd.DataFrame:
    out = df.iloc[i + 1:].copy()
    out.columns = [str(c).strip() for c in df.iloc[i].values]
    return out.dropna(how="all")


def _lebar_kolom(ws, lebar):
    for i, w in enumerate(lebar, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def ke_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------- bahan baku
def _isi_satuan(b: Bahan, u: SatuanBahan) -> float | None:
    """Isi satu satuan majoo dalam satuan dasar (None bila konversi majoo tidak dapat dipercaya)."""
    dasar = next((x for x in b.satuan_lain if x.dasar), None)
    if dasar is None or u.dasar:
        return 1.0
    if dasar.no == 1:
        return float(u.konversi)
    return None


def buku_bahan(db: Session, petunjuk: bool = True) -> Workbook:
    """Ekspor Daftar Bahan Baku: sheet format ekspor majoo + sheet parameter PrediStok."""
    bahan = db.query(Bahan).filter(Bahan.aktif.is_(True)).order_by(Bahan.nama).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Ekspor Daftar Bahan Baku"
    ws["A1"] = "Daftar Bahan Baku"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"], ws["B2"] = "Tanggal Ekspor", datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    hdr = ["Nama Bahan*", "Monitor Persediaan (Y / T)*", "Stok Minimum", "Satuan #1*", "Harga Beli #1*", "SKU #1*"]
    for i in range(2, 6):
        hdr += [f"Satuan #{i}", f"Konversi #{i}", f"Harga Beli #{i}", f"SKU #{i}"]
    ws.append([])
    ws.append(hdr)
    for c in ws[4]:
        c.font = TEBAL
        c.fill = HIJAU
    for b in bahan:
        units = sorted(b.satuan_lain, key=lambda u: u.no) or [SatuanBahan(no=1, satuan=b.satuan, sku=b.sku,
                                                                             konversi=1.0, dasar=True)]
        dasar = next((u for u in units if u.dasar), units[0])
        konv_dasar = 1.0 if dasar.no == 1 else float(dasar.konversi or 1.0)
        stokmin = round((b.stok_minimum or 0) * konv_dasar, 2)
        harga_pasti = "harga" not in b.daftar_asumsi

        def harga_unit(u):
            if harga_pasti:
                isi = _isi_satuan(b, u)
                if isi is not None:
                    return round(b.harga_satuan * isi, 2)
            return u.harga_beli or 0

        u1 = units[0]
        row = [b.nama, "Y" if b.monitor else "T", stokmin, u1.satuan, harga_unit(u1), u1.sku]
        for u in units[1:5]:
            row += [u.satuan, u.konversi, harga_unit(u), u.sku]
        ws.append(row)
    _lebar_kolom(ws, [34, 14, 12, 10, 12, 10] + [10, 10, 10, 10] * 4)
    _sheet_parameter(wb, bahan)
    _sheet_biaya(wb, PG.semua(db))
    if petunjuk:
        _sheet_petunjuk(wb)
    return wb


def _sheet_parameter(wb: Workbook, bahan):
    ws = wb.create_sheet("Parameter PrediStok")
    judul = [k[0] for k in KOLOM_PARAMETER] + [JUDUL_KONFIRMASI, JUDUL_KETERANGAN]
    ws.append(judul)
    for c in ws[1]:
        c.font = TEBAL
        c.fill = HIJAU
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for b in bahan:
        asumsi = set(b.daftar_asumsi)
        if not b.maks_kelipatan:
            asumsi.add("kapasitas")
        vals = []
        for _, attr, _ in KOLOM_PARAMETER:
            v = getattr(b, attr)
            if attr == "monitor":
                v = "Y" if v else "T"
            vals.append(v)
        ket = "; ".join(KETERANGAN_ASUMSI[a] for a in KETERANGAN_ASUMSI if a in asumsi)
        ws.append(vals + ["", ket])
        r = ws.max_row
        for j, (_, attr, tanda) in enumerate(KOLOM_PARAMETER, 1):
            if tanda and tanda in asumsi:
                ws.cell(r, j).fill = KUNING
            if j <= 4:
                ws.cell(r, j).fill = ABU
    ws.freeze_panes = "C2"
    _lebar_kolom(ws, [10, 30, 10, 18, 14, 14, 16, 12, 10, 14, 16, 11, 14, 60])
    ws.row_dimensions[1].height = 45


def _sheet_biaya(wb: Workbook, cfg: dict):
    ws = wb.create_sheet("Biaya Umum")
    ws.append(["Parameter", "Nilai", "Keterangan"])
    for c in ws[1]:
        c.font = TEBAL
        c.fill = HIJAU
    ws.append(["Biaya per pesanan satu bahan (Rp)", cfg["biaya_pesan"],
               "c_o: ongkos kirim atau biaya transaksi satu kali belanja dibagi rata-rata jumlah bahan per belanja"])
    ws.append(["Biaya simpan per hari (% harga beli)", cfg["biaya_simpan_persen"],
               "c_h: biaya modal dan penyimpanan, mis. 0,1 berarti 0,1% dari harga beli per satuan per hari"])
    for r in (2, 3):
        ws.cell(r, 2).fill = KUNING
    _lebar_kolom(ws, [38, 12, 100])


def _sheet_petunjuk(wb: Workbook):
    ws = wb.create_sheet("Petunjuk")
    teks = [
        "Cara melengkapi data master PrediStok",
        "",
        "1. Buka sheet 'Parameter PrediStok'. Sel berwarna kuning masih berisi nilai sementara (perkiraan).",
        "2. Ganti nilai kuning dengan data sebenarnya bila diketahui: harga beli per satuan dasar (dari nota),",
        "   isi kemasan beli (mis. susu 1 liter = 1000 gram), masa simpan (hari), dan kapasitas simpan maksimum",
        "   (berapa kemasan paling banyak yang muat disimpan). Kosongkan kapasitas bila belum diketahui;",
        "   PrediStok lalu memakai kapasitas otomatis dari pola pemakaian (stok target tertinggi + 20%, atau",
        "   ROP + jumlah pesan kebijakan K1 bila lebih besar; paling sedikit 2 kemasan).",
        "3. Bila semua nilai satu baris sudah benar, isi kolom 'Data sudah benar (Y/T)' dengan Y.",
        "4. Isi sheet 'Biaya Umum' (ongkos kirim per pesanan dan biaya simpan).",
        "5. Simpan file, lalu impor lewat menu Daftar Bahan Baku > Impor Bahan Baku.",
        "",
        "Sheet 'Ekspor Daftar Bahan Baku' memakai format ekspor majoo. Kolom Stok Minimum berisi ROP dinamis",
        "(batas pesan ulang) terbaru dari PrediStok. Bila majoo menerima impor dengan format yang sama, kolom ini",
        "dapat dipakai untuk memperbarui stok minimum di majoo (belum dicoba).",
        "",
        "Satuan dasar adalah satuan yang dipakai resep majoo (mis. Gram atau Pcs). Semua jumlah di PrediStok",
        "memakai satuan dasar ini.",
    ]
    for t in teks:
        ws.append([t])
    ws["A1"].font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 110


def _berbeda(lama, baru) -> bool:
    from app.web import berbeda
    return berbeda(lama, baru)


def _kelompok(nama, satuan):
    from ml.master import _kelompok as kel
    return kel(nama, satuan)


def impor_bahan(db: Session, data: bytes) -> dict:
    """Impor file Daftar Bahan Baku (ekspor majoo atau file PrediStok yang sudah dilengkapi)."""
    sheets = baca_excel(data)
    hasil = {"baru": 0, "diubah": 0, "parameter": 0, "biaya": False, "galat": []}
    per_sku = {}
    for b in db.query(Bahan).all():
        per_sku[b.sku] = b
        for u in b.satuan_lain:
            per_sku.setdefault(u.sku, b)
    for nama, df in sheets.items():
        i = _cari_header(df, ["nama bahan", "satuan #1", "sku #1"])
        if i is None:
            continue
        tabel = _dengan_header(df, i)
        for _, r in tabel.iterrows():
            nm = str(r.get("Nama Bahan*", "") or "").strip()
            if not nm or nm.lower().startswith("powered") or nm == "nan":
                continue
            units = []
            for n in range(1, 6):
                sat = r.get(f"Satuan #{n}*" if n == 1 else f"Satuan #{n}")
                sku = r.get(f"SKU #{n}*" if n == 1 else f"SKU #{n}")
                if pd.isna(sat) or pd.isna(sku) or str(sku).strip() == "":
                    continue
                konv = 1.0 if n == 1 else (angka(r.get(f"Konversi #{n}")) or 1.0)
                harga = angka(r.get(f"Harga Beli #{n}*" if n == 1 else f"Harga Beli #{n}")) or 0.0
                units.append((n, str(sat).strip(), str(sku).strip(), konv, harga))
            if not units:
                hasil["galat"].append(f"{nm}: tidak ada satuan/SKU")
                continue
            mon = str(r.get("Monitor Persediaan (Y / T)*", "Y")).strip().upper() != "T"
            b = next((per_sku[u[2]] for u in units if u[2] in per_sku), None)
            if b is None:
                n0, sat0, sku0, _, harga0 = units[0]
                kel, tau, h_kel = _kelompok(nm, sat0)
                b = Bahan(sku=sku0, nama=nm, kategori=kel, satuan=sat0, monitor=mon,
                          stok_minimum=angka(r.get("Stok Minimum")) or 0.0, kemasan_nama="Kemasan", kemasan_isi=1.0,
                          harga_satuan=harga0 or h_kel, masa_simpan=tau, lead_time=C.LEAD_TIME,
                          biaya_kehabisan=2 * (harga0 or h_kel), sumber_harga="majoo" if harga0 else "asumsi kelompok",
                          sumber_kemasan="asumsi", sumber_biaya_kehabisan="2x harga",
                          asumsi=",".join(["masa_simpan", "lead_time", "kemasan"] + ([] if harga0 else ["harga"])),
                          catatan="Ditambahkan dari impor; belum ada riwayat pemakaian")
                andal = [u for u in units[1:] if u[3] > 1]
                if andal:
                    b.kemasan_nama, b.kemasan_isi = andal[0][1], float(andal[0][3])
                    b.asumsi = ",".join(a for a in b.daftar_asumsi if a != "kemasan")
                    b.sumber_kemasan = "majoo"
                db.add(b)
                for n, sat, sku, konv, harga in units:
                    b.satuan_lain.append(SatuanBahan(no=n, satuan=sat, sku=sku, konversi=konv, harga_beli=harga,
                                                     dasar=(sku == b.sku)))
                    per_sku[sku] = b
                hasil["baru"] += 1
                continue
            berubah = b.nama != nm or b.monitor != mon
            b.nama, b.monitor = nm, mon
            lama = {u.sku: u for u in b.satuan_lain}
            for n, sat, sku, konv, harga in units:
                u = lama.get(sku)
                if u is None:
                    b.satuan_lain.append(SatuanBahan(no=n, satuan=sat, sku=sku, konversi=konv, harga_beli=harga,
                                                     dasar=(sku == b.sku)))
                    berubah = True
                elif (u.no, u.satuan, u.konversi, u.harga_beli) != (n, sat, konv, harga):
                    u.no, u.satuan, u.konversi, u.harga_beli = n, sat, konv, harga
                    berubah = True
            hasil["diubah"] += int(berubah)
    if "Parameter PrediStok" in sheets:
        hasil["parameter"] = _impor_parameter(db, sheets["Parameter PrediStok"], per_sku, hasil["galat"])
    if "Biaya Umum" in sheets:
        hasil["biaya"] = _impor_biaya(db, sheets["Biaya Umum"])
    db.commit()
    return hasil


def _impor_parameter(db: Session, df: pd.DataFrame, per_sku: dict, galat: list) -> int:
    i = _cari_header(df, ["sku", "isi kemasan", "masa simpan"])
    if i is None:
        return 0
    t = _dengan_header(df, i)
    n_ubah = 0
    for _, r in t.iterrows():
        sku = str(r.get("SKU", "")).strip()
        b = per_sku.get(sku)
        if b is None:
            if sku and sku != "nan":
                galat.append(f"SKU {sku} tidak ditemukan")
            continue
        asumsi = set(b.daftar_asumsi)
        ubah = False
        for judul, attr, tanda in KOLOM_PARAMETER[3:]:
            if judul not in t.columns:
                continue
            v = r.get(judul)
            if attr in ("satuan", "kategori", "kemasan_nama"):
                if pd.isna(v) or str(v).strip() == "":
                    continue
                v = str(v).strip()
            elif attr == "monitor":
                if pd.isna(v):
                    continue
                v = str(v).strip().upper() != "T"
            else:
                v = angka(v)
                if v is None:
                    if attr == "maks_kelipatan" and b.maks_kelipatan is not None:
                        b.maks_kelipatan = None   # dikosongkan: kapasitas dihitung otomatis dari data
                        ubah = True
                    continue
                if attr in ("masa_simpan", "lead_time", "maks_kelipatan"):
                    v = int(round(v))
                if v < 0 or (attr in ("kemasan_isi", "masa_simpan") and v <= 0):
                    galat.append(f"{sku}: nilai {judul} tidak valid ({v})")
                    continue
            if _berbeda(getattr(b, attr), v):
                setattr(b, attr, v)
                ubah = True
                if tanda:
                    asumsi.discard(tanda)
                    if tanda == "harga":
                        b.sumber_harga = "diisi kafe"
                    elif tanda == "kemasan":
                        b.sumber_kemasan = "diisi kafe"
                    elif tanda == "biaya_kehabisan":
                        b.sumber_biaya_kehabisan = "diisi kafe"
        if str(r.get(JUDUL_KONFIRMASI, "")).strip().upper() == "Y":
            asumsi.clear()
            b.sumber_harga = b.sumber_kemasan = b.sumber_biaya_kehabisan = "diisi kafe"
            ubah = True
        baru = ",".join(sorted(asumsi))
        if baru != (b.asumsi or ""):
            b.asumsi = baru
            ubah = True
        n_ubah += int(ubah)
    return n_ubah


def _impor_biaya(db: Session, df: pd.DataFrame) -> bool:
    nilai = {}
    for _, r in df.iterrows():
        k = str(r.iloc[0]).lower()
        v = angka(r.iloc[1]) if len(r) > 1 else None
        if v is None:
            continue
        if "per pesanan" in k:
            nilai["biaya_pesan"] = v
        elif "biaya simpan" in k:
            nilai["biaya_simpan_persen"] = v
    if nilai:
        PG.simpan(db, nilai)
    return bool(nilai)


# ---------------------------------------------------------------------- stok keluar
def impor_stok_keluar(db: Session, data: bytes, tanggal: date | None = None, oleh: str = "") -> dict:
    """Impor stok keluar harian.

    Format yang diterima:
      1. tabel panjang: kolom Tanggal, SKU (atau SKU Bahan), Jumlah Keluar,
      2. ekspor Daftar Stok majoo untuk satu hari: kolom SKU dan TERJUAL (pilih tanggalnya di formulir).
    Setiap tanggal di file dianggap catatan lengkap hari itu: bahan yang tidak ada di file dianggap 0.
    """
    sheets = baca_excel(data)
    per_sku = {}
    for b in db.query(Bahan).all():
        per_sku[b.sku] = b
        for u in b.satuan_lain:
            per_sku.setdefault(u.sku, b)
    catatan = {}
    tidak_dikenal = set()
    for _, df in sheets.items():
        i = _cari_header(df, ["tanggal", "sku"])
        j = _cari_header(df, ["sku", "terjual"])
        if i is not None:
            t = _dengan_header(df, i)
            kol_sku = next(c for c in t.columns if "sku" in c.lower())
            kol_q = next((c for c in t.columns if c.lower() in ("jumlah keluar", "jumlah", "keluar", "terjual",
                                                                  "stok keluar")), None)
            if kol_q is None:
                continue
            kol_t = next(c for c in t.columns if "tanggal" in c.lower())
            for _, r in t.iterrows():
                tg = pd.to_datetime(r[kol_t], errors="coerce", dayfirst=True)
                q = angka(r[kol_q])
                sku = str(r[kol_sku]).strip()
                if pd.isna(tg) or q is None:
                    continue
                if sku not in per_sku:
                    tidak_dikenal.add(sku)
                    continue
                key = (tg.date(), per_sku[sku].id)
                catatan[key] = catatan.get(key, 0.0) + q
        elif j is not None:
            if tanggal is None:
                raise ValueError("File Daftar Stok majoo: pilih tanggal pemakaian di formulir impor.")
            t = _dengan_header(df, j)
            kol_sku = next(c for c in t.columns if c.lower().startswith("sku"))
            kol_q = next(c for c in t.columns if "terjual" in c.lower())
            for _, r in t.iterrows():
                sku = str(r[kol_sku]).strip()
                q = angka(r[kol_q])
                if q is None or sku in ("", "nan"):
                    continue
                if sku not in per_sku:
                    tidak_dikenal.add(sku)
                    continue
                key = (tanggal, per_sku[sku].id)
                catatan[key] = catatan.get(key, 0.0) + q
    if not catatan:
        raise ValueError("Tidak ada baris stok keluar yang dikenali. Gunakan kolom Tanggal, SKU, Jumlah Keluar "
                         "atau ekspor Daftar Stok majoo (kolom SKU dan TERJUAL).")
    tgl_set = sorted({k[0] for k in catatan})
    simpan_stok_keluar(db, {t: {b: q for (tt, b), q in catatan.items() if tt == t} for t in tgl_set},
                       sumber="impor", ganti_hari=True)
    return {"hari": len(tgl_set), "baris": len(catatan), "mulai": tgl_set[0], "sampai": tgl_set[-1],
            "tidak_dikenal": sorted(tidak_dikenal)}


def simpan_stok_keluar(db: Session, per_tanggal: dict, sumber: str = "manual", ganti_hari: bool = True,
                       status: str = "tercatat"):
    """per_tanggal: {tanggal: {bahan_id: jumlah}}. ganti_hari: bahan yang tidak disebut pada hari itu = 0."""
    for t, isi in per_tanggal.items():
        ada = {r.bahan_id: r for r in db.query(StokKeluar).filter(StokKeluar.tanggal == t).all()}
        if ganti_hari:
            for bid, r in ada.items():
                if bid not in isi:
                    r.jumlah = 0.0
        for bid, q in isi.items():
            q = max(float(q), 0.0)
            if bid in ada:
                ada[bid].jumlah = q
            else:
                db.add(StokKeluar(bahan_id=bid, tanggal=t, jumlah=q))
        p = db.get(PencatatanHarian, t)
        if p is None:
            db.add(PencatatanHarian(tanggal=t, status=status, sumber=sumber))
        else:
            p.status, p.sumber = status, sumber
    db.commit()


# ---------------------------------------------------------------------- opname
def buku_opname(db: Session, tanggal: date, stok_tercatat: dict) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Stok Opname"
    ws.append(["Tanggal opname", tanggal.strftime("%d/%m/%Y")])
    ws.append([])
    ws.append(["SKU", "Nama Bahan", "Kategori", "Satuan", "Stok Tercatat", "Stok Fisik"])
    for c in ws[3]:
        c.font = TEBAL
        c.fill = HIJAU
    for b in db.query(Bahan).filter(Bahan.aktif.is_(True), Bahan.monitor.is_(True)).order_by(Bahan.kategori,
                                                                                               Bahan.nama).all():
        ws.append([b.sku, b.nama, b.kategori, b.satuan, round(stok_tercatat.get(b.id, 0.0), 2), None])
        ws.cell(ws.max_row, 6).fill = KUNING
    ws["F3"].comment = Comment("Isi hasil hitung fisik dalam satuan dasar. Biarkan kosong bila tidak dihitung.",
                               "PrediStok")
    _lebar_kolom(ws, [10, 34, 18, 10, 14, 14])
    ws.freeze_panes = "A4"
    return wb


def impor_opname(db: Session, data: bytes, tanggal: date, oleh: str = "") -> dict:
    sheets = baca_excel(data)
    per_sku = {b.sku: b for b in db.query(Bahan).all()}
    n, galat = 0, []
    for _, df in sheets.items():
        i = _cari_header(df, ["sku", "stok fisik"])
        if i is None:
            continue
        t = _dengan_header(df, i)
        for _, r in t.iterrows():
            sku = str(r.get("SKU", "")).strip()
            q = angka(r.get("Stok Fisik"))
            if q is None:
                continue
            b = per_sku.get(sku)
            if b is None:
                galat.append(f"SKU {sku} tidak ditemukan")
                continue
            if q < 0:
                galat.append(f"{sku}: stok fisik negatif")
                continue
            db.add(MutasiStok(bahan_id=b.id, tanggal=tanggal, jenis="opname", jumlah=q, keterangan="impor opname",
                              dibuat_oleh=oleh))
            n += 1
    db.commit()
    return {"baris": n, "galat": galat}


# ---------------------------------------------------------------------- laporan tabel
def _lebar_isi(df: pd.DataFrame, kolom) -> int:
    """Lebar kolom Excel dari teks terpanjang (judul atau isi), 10-40 karakter."""
    n = [len(str(kolom))] + [len(str(v)) for v in df[kolom].tolist()
                             if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return max(10, min(40, max(n) + 2))


def buku_tabel(judul: str, df: pd.DataFrame, info: list = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = judul[:31]
    ws.append([judul])
    ws["A1"].font = Font(bold=True, size=13)
    for baris in info or []:
        ws.append(baris)
    ws.append([])
    ws.append(list(df.columns))
    r0 = ws.max_row
    for c in ws[r0]:
        c.font = TEBAL
        c.fill = HIJAU
    for row in df.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and math.isnan(v)) else v for v in row])
    _lebar_kolom(ws, [_lebar_isi(df, c) for c in df.columns])
    ws.freeze_panes = ws.cell(r0 + 1, 1)
    return ke_bytes(wb)
