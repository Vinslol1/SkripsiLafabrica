"""Basis data uji sementara, diisi sekali dari data_awal dan model hasil pelatihan awal (artefak/).

Variabel lingkungan diatur sebelum modul aplikasi diimpor, sehingga basis data dan folder model
aplikasi yang sebenarnya tidak tersentuh.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

AKAR = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="predistok_uji_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'uji.db').as_posix()}"
os.environ["PREDISTOK_SECRET"] = "kunci-sesi-uji"
os.environ["PREDISTOK_FOLDER_MODEL"] = str(_TMP / "model")
os.environ.pop("PREDISTOK_DEMO", None)
sys.path.insert(0, str(AKAR))


def token(teks: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', teks).group(1)


def masuk(app, username="admin", sandi="admin123"):
    """TestClient yang sudah login; token CSRF dikirim lewat header di setiap permintaan."""
    from fastapi.testclient import TestClient
    c = TestClient(app)
    c.headers["x-csrf-token"] = token(c.get("/masuk").text)
    r = c.post("/masuk", data={"username": username, "sandi": sandi}, follow_redirects=False)
    assert r.status_code == 303
    c.headers["x-csrf-token"] = token(c.get("/pengaturan").text)   # token baru setelah login
    return c


@pytest.fixture(scope="session")
def aplikasi():
    from app import seed
    seed.jalankan(log=lambda *_: None)
    from app.main import app
    return app


@pytest.fixture(scope="session")
def admin(aplikasi):
    return masuk(aplikasi)


@pytest.fixture
def tamu(aplikasi):
    from fastapi.testclient import TestClient
    return TestClient(aplikasi)


@pytest.fixture
def db(aplikasi):
    from app.db import SesiLokal
    s = SesiLokal()
    yield s
    s.close()


def pesan_kilat(teks: str) -> list:
    return [re.sub(r"\s+", " ", m).strip() for m in re.findall(r'<div class="(?:sukses|galat|peringatan)"><span>(.*?)</span>', teks, re.S)]
