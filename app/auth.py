"""Login berbasis sesi dan hash kata sandi PBKDF2 (pustaka standar Python)."""
import hashlib
import hmac
import secrets

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Pengguna

ITERASI = 200_000


def hash_sandi(sandi: str) -> str:
    garam = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", sandi.encode(), bytes.fromhex(garam), ITERASI).hex()
    return f"pbkdf2_sha256${ITERASI}${garam}${h}"


def cek_sandi(sandi: str, tersimpan: str) -> bool:
    try:
        _, it, garam, h = tersimpan.split("$")
        uji = hashlib.pbkdf2_hmac("sha256", sandi.encode(), bytes.fromhex(garam), int(it)).hex()
        return hmac.compare_digest(uji, h)
    except (ValueError, AttributeError):
        return False


class BelumLogin(Exception):
    pass


class BukanAdmin(Exception):
    pass


def pengguna_aktif(request: Request, db: Session = Depends(get_db)) -> Pengguna:
    uid = request.session.get("uid")
    p = db.get(Pengguna, uid) if uid else None
    if p is None or not p.aktif:
        request.session.pop("uid", None)
        raise BelumLogin()
    request.state.pengguna = p
    return p


def admin_saja(p: Pengguna = Depends(pengguna_aktif)) -> Pengguna:
    if p.peran != "admin":
        raise BukanAdmin()
    return p


def token_csrf(request: Request) -> str:
    t = request.session.get("csrf")
    if not t:
        t = secrets.token_urlsafe(24)
        request.session["csrf"] = t
    return t


async def verifikasi_csrf(request: Request):
    """Semua formulir POST wajib membawa token sesi (mencegah pengiriman formulir dari situs lain)."""
    if request.method != "POST":
        return
    form = await request.form()
    kirim = form.get("csrf") or request.headers.get("x-csrf-token")
    if not kirim or not hmac.compare_digest(str(kirim), request.session.get("csrf", "")):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Sesi formulir kedaluwarsa. Muat ulang halaman lalu coba lagi.")
