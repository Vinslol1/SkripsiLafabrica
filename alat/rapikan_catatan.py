"""Rapikan catatan WhatsApp cafe (REPORT ORDER dan barang masuk) menjadi Excel terstruktur.

    python alat/rapikan_catatan.py                                   semua .txt di data_awal/catatan_manual
    python alat/rapikan_catatan.py catatan.txt -o hasil.xlsx         satu file

Nama barang dicocokkan dengan data bahan dari file ekspor majoo di data_awal (sama seperti isi awal aplikasi).
Hasilnya bisa dicek, dikoreksi, lalu diimpor di aplikasi: Inventori > Kelola Stok > Catatan Barang Masuk.
"""
import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import config as C  # noqa: E402
from app.layanan import catatan_manual as CM  # noqa: E402
from ml.master import susun_master  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("berkas", nargs="*", help="file teks catatan (bawaan: semua .txt di data_awal/catatan_manual)")
    ap.add_argument("-o", "--keluaran", help="file Excel keluaran")
    a = ap.parse_args()
    files = [Path(f) for f in a.berkas] or sorted(C.FOLDER_CATATAN.glob("*.txt"))
    if not files:
        sys.exit("Tidak ada file catatan.")
    teks = "\n".join(f.read_text(encoding="utf-8") for f in files)
    M = CM.Master.dari_tabel(susun_master(log=lambda *_: None))
    df, laporan = CM.rapikan(teks, M)
    keluaran = Path(a.keluaran) if a.keluaran else files[0].with_name(f"Catatan_Rapi_{files[0].stem}.xlsx")
    CM.tulis_excel(df, laporan, keluaran, judul_sumber=", ".join(f.name for f in files))
    m = df[df["jenis"] == "masuk"]
    print(f"{len(laporan)} laporan, {len(df)} baris ({len(m)} barang masuk, {len(df) - len(m)} order)")
    print(m["status"].value_counts().to_string())
    print(f"Tersimpan: {keluaran}")


if __name__ == "__main__":
    main()
