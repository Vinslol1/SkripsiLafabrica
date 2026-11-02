"""Template Jinja2, format angka/tanggal gaya Indonesia, dan pesan kilat (flash)."""
import json
import math
from datetime import date, datetime
from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

import config as C
from app.auth import token_csrf

BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
BULAN_PANJANG = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
                 "November", "Desember"]
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def kosong(x) -> bool:
    """None, NaN, atau tak hingga (nilai yang tidak dapat ditampilkan sebagai angka)."""
    if x is None:
        return True
    try:
        v = float(x)
    except (TypeError, ValueError):
        return True
    return math.isnan(v) or math.isinf(v)


def bersih(obj):
    """Ganti NaN/inf di struktur JSON (dict/list) menjadi None agar aman ditampilkan di template."""
    if isinstance(obj, dict):
        return {k: bersih(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [bersih(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _angka(x, d=0):
    if kosong(x):
        return "-"
    s = f"{abs(float(x)):,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    if d > 0:
        s = s.rstrip("0").rstrip(",") if "," in s else s
    return ("-" if float(x) < 0 and s not in ("0",) else "") + s


def angka(x, d=0):
    """1234.5 -> '1.234,5' (desimal tidak bermakna dibuang)."""
    return _angka(x, d)


def angka_pas(x):
    """Angka stok: tanpa desimal bila bulat, paling banyak 2 desimal."""
    if kosong(x):
        return "-"
    return _angka(x, 0 if abs(float(x) - round(float(x))) < 1e-9 else 2)


def stok(x):
    """Gaya Daftar Stok majoo: negatif ditulis dalam kurung, mis. (195)."""
    if kosong(x):
        return "-"
    v = float(x)
    if v < -1e-9:
        return f"({angka_pas(-v)})"
    return angka_pas(0.0 if abs(v) < 1e-9 else v)


def isian(x):
    """Nilai untuk kotak isian: tanpa pemisah ribuan, koma desimal, presisi penuh (maks. 6 desimal)."""
    if kosong(x):
        return ""
    v = float(x)
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.6f}".rstrip("0").rstrip(".").replace(".", ",")


def berbeda(lama, baru) -> bool:
    if isinstance(baru, float) or isinstance(lama, float):
        if lama is None or baru is None:
            return lama is not baru
        return abs(float(lama) - float(baru)) > 1e-6 * max(1.0, abs(float(lama)))
    return lama != baru


def rupiah(x, d=0):
    if kosong(x):
        return "-"
    return f"Rp {_angka(x, d)}"


def tgl(d):
    if d is None:
        return "-"
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return f"{d.day:02d} {BULAN[d.month - 1]} {d.year}"


def tgl_panjang(d):
    if d is None:
        return "-"
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return f"{HARI[d.weekday()]}, {d.day} {BULAN_PANJANG[d.month - 1]} {d.year}"


def waktu(dt):
    if dt is None:
        return "-"
    return f"{tgl(dt.date())} {dt:%H:%M}"


def persen(x, d=1):
    if kosong(x):
        return "-"
    return f"{_angka(100 * float(x), d)}%"


def kemasan(jumlah, isi, nama="kemasan"):
    """'3 Botol' atau '2,5 Kemasan' dari jumlah satuan dasar."""
    if kosong(isi) or isi <= 0 or kosong(jumlah):
        return "-"
    n = jumlah / isi
    return f"{angka_pas(n)} {nama}"


templates.env.filters.update(angka=angka, angka_pas=angka_pas, stok=stok, rupiah=rupiah, tgl=tgl, isian=isian,
                             tgl_panjang=tgl_panjang, waktu=waktu, persen=persen, kemasan=kemasan,
                             json=lambda x: json.dumps(x, default=str))
templates.env.globals.update(NAMA_APLIKASI=C.NAMA_APLIKASI, sekarang=datetime.now)


def flash(request: Request, pesan: str, jenis: str = "sukses"):
    # ditetapkan ulang (bukan append) agar sesi Starlette tahu isinya berubah dan cookie ditulis lagi
    request.session["flash"] = [*request.session.get("flash", []), {"pesan": pesan, "jenis": jenis}]


def render(request: Request, nama: str, menu: str = "", status_code: int = 200, **ctx) -> Response:
    from app.db import SesiLokal
    from app.layanan import pengaturan as PG
    flash_list = request.session.pop("flash", [])
    p = getattr(request.state, "pengguna", None)
    with SesiLokal() as db:
        cfg = PG.semua(db)
        notif = _notifikasi(db) if p else {"kritis": 0, "terlambat": 0, "total": 0}
    ctx.update(request=request, pengguna=p, csrf=token_csrf(request), menu=menu, flash=flash_list,
               nama_outlet=cfg["nama_outlet"], notif=notif, mode_demo=bool(cfg.get("mode_demo")))
    return templates.TemplateResponse(request, nama, ctx, status_code=status_code)


def _notifikasi(db):
    from app.models import Pesanan, Rekomendasi
    t = db.query(Rekomendasi.tanggal).order_by(Rekomendasi.tanggal.desc()).limit(1).scalar()
    kritis = db.query(Rekomendasi).filter(Rekomendasi.tanggal == t, Rekomendasi.kritis.is_(True)).count() if t else 0
    terlambat = db.query(Pesanan).filter(Pesanan.status == "dipesan",
                                         Pesanan.tanggal_perkiraan < date.today()).count()
    return {"kritis": kritis, "terlambat": terlambat, "total": kritis + terlambat, "tanggal": t}


def ke(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def unduh(data: bytes, nama_file: str) -> Response:
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{nama_file}"'})
