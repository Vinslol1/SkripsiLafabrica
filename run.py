"""Menjalankan PrediStok di komputer sendiri.

    python run.py              aplikasi dengan basis data utama (predistok.db)
    python run.py --demo       basis data demo terpisah berisi riwayat stok hasil simulasi
    python run.py --port 8080  port lain bila 8000 sudah dipakai

Saat pertama dijalankan, basis data diisi dari folder data_awal dan model hasil pelatihan awal (artefak/).
"""
import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description="PrediStok: rekomendasi pemesanan bahan baku")
    ap.add_argument("--demo", action="store_true", help="pakai basis data demo (predistok_demo.db)")
    ap.add_argument("--ulang-demo", action="store_true", help="hapus lalu buat ulang basis data demo")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 agar bisa dibuka dari perangkat lain di jaringan")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--tanpa-browser", action="store_true", help="jangan membuka browser otomatis")
    a = ap.parse_args()

    os.chdir(BASE)
    sys.path.insert(0, str(BASE))
    if a.demo or a.ulang_demo:
        os.environ["PREDISTOK_DEMO"] = "1"
        if a.ulang_demo and "DATABASE_URL" not in os.environ:
            for akhiran in ("", "-wal", "-shm"):
                f = BASE / f"predistok_demo.db{akhiran}"
                if f.exists():
                    f.unlink()

    import config as C
    from app import seed
    print(f"{C.NAMA_APLIKASI}: menyiapkan basis data {'DEMO ' if C.DEMO else ''}...")
    seed.jalankan(log=lambda m: print("  " + m))
    if C.DEMO:
        from app import demo
        demo.jalankan(log=lambda m: print("  " + m))

    import uvicorn
    from app.main import app
    url = f"http://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:{a.port}"
    print(f"\n{C.NAMA_APLIKASI} berjalan di {url}  (tutup jendela ini atau tekan Ctrl+C untuk berhenti)")
    if not a.tanpa_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
