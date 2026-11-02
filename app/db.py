"""Koneksi basis data (SQLite secara bawaan, MySQL bila DATABASE_URL diisi)."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

import config as C

_sqlite = C.DATABASE_URL.startswith("sqlite")
engine = create_engine(C.DATABASE_URL, connect_args={"check_same_thread": False} if _sqlite else {},
                       pool_pre_ping=True)

if _sqlite:
    @event.listens_for(engine, "connect")
    def _pragma(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

SesiLokal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SesiLokal()
    try:
        yield db
    finally:
        db.close()
