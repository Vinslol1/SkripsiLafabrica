#!/usr/bin/env sh
# PrediStok untuk macOS/Linux: ./jalankan.sh  (tambahkan --demo untuk basis data demo)
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Menyiapkan lingkungan Python untuk pertama kali..."
  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt || { rm -rf .venv; exit 1; }
  cp requirements.txt .venv/requirements-terpasang.txt
fi
# versi aplikasi baru dengan requirements.txt berbeda: pasang pustaka yang kurang tanpa menghapus .venv
if ! cmp -s requirements.txt .venv/requirements-terpasang.txt; then
  echo "Memeriksa pustaka Python untuk versi aplikasi ini..."
  if .venv/bin/python -m pip install -r requirements.txt; then
    cp requirements.txt .venv/requirements-terpasang.txt
  else
    echo "Sebagian pustaka gagal dipasang. Aplikasi tetap dijalankan, coba lagi saat internet stabil."
  fi
fi
exec .venv/bin/python run.py "$@"
