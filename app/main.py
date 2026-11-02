"""Aplikasi web PrediStok (FastAPI)."""
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import config as C
from app.auth import BelumLogin, BukanAdmin, verifikasi_csrf
from app.rute import bahan, model, pembelian, pengaturan, rekomendasi, stok, umum
from app.web import flash, ke, render

app = FastAPI(title=C.NAMA_APLIKASI, docs_url=None, redoc_url=None, openapi_url=None,
              dependencies=[Depends(verifikasi_csrf)])
app.add_middleware(SessionMiddleware, secret_key=C.SECRET_KEY, session_cookie="predistok_sesi",
                   max_age=12 * 3600, same_site="lax")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

for r in (umum, bahan, stok, pembelian, rekomendasi, model, pengaturan):
    app.include_router(r.router)


@app.exception_handler(BelumLogin)
async def _belum_login(request: Request, exc: BelumLogin):
    if request.url.path.startswith("/api/"):
        return PlainTextResponse("Belum login", status_code=401)
    tujuan = request.url.path
    return ke(f"/masuk?lanjut={tujuan}" if tujuan not in ("/", "/masuk") else "/masuk")


@app.exception_handler(BukanAdmin)
async def _bukan_admin(request: Request, exc: BukanAdmin):
    flash(request, "Perubahan ini hanya dapat dilakukan oleh admin.", "galat")
    asal = urlsplit(request.headers.get("referer") or "").path
    return ke(asal if asal.startswith("/") and not asal.startswith("//") else "/dasbor")


@app.exception_handler(HTTPException)
async def _http(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/") or exc.status_code not in (400, 403, 404):
        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)
    return render(request, "galat.html", status_code=exc.status_code, kode=exc.status_code, pesan=exc.detail)


@app.get("/kesehatan", response_class=HTMLResponse, include_in_schema=False)
def kesehatan():
    return "ok"
