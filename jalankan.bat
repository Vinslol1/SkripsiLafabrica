@echo off
rem PrediStok: klik dua kali file ini untuk menjalankan aplikasi di komputer ini.
rem Pertama kali dijalankan, lingkungan Python (.venv) dan pustaka akan dipasang otomatis.
rem Bila requirements.txt berubah (versi aplikasi baru), pustaka yang kurang dipasang tanpa menghapus .venv.
setlocal
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python belum terpasang. Pasang Python 3.12 atau 3.13 dari https://www.python.org/downloads/
  echo dan centang "Add python.exe to PATH" saat instalasi, lalu jalankan file ini lagi.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Menyiapkan lingkungan Python untuk pertama kali. Mohon tunggu 3-10 menit...
  %PY% -m venv .venv
  if errorlevel 1 goto gagal
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto gagal
  copy /y requirements.txt ".venv\requirements-terpasang.txt" >nul
)
fc /b requirements.txt ".venv\requirements-terpasang.txt" >nul 2>nul
if errorlevel 1 (
  echo Memeriksa pustaka Python untuk versi aplikasi ini...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Sebagian pustaka gagal dipasang. Aplikasi tetap dijalankan, coba lagi saat internet stabil.
  ) else (
    copy /y requirements.txt ".venv\requirements-terpasang.txt" >nul
  )
)
".venv\Scripts\python.exe" run.py %*
pause
exit /b 0

:gagal
echo.
echo Gagal menyiapkan Python. Periksa koneksi internet, lalu jalankan file ini lagi.
if exist ".venv" rmdir /s /q ".venv"
pause
exit /b 1
