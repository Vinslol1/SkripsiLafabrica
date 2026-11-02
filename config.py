"""Konfigurasi aplikasi dan parameter model.

Semua nilai di sini adalah nilai awal (Tabel 5 proposal). Parameter biaya dan
pelatihan juga bisa diubah dari halaman Pengaturan; nilai di basis data
mengalahkan nilai di file ini.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_AWAL = BASE_DIR / "data_awal"
ARTEFAK = BASE_DIR / "artefak"
LAPORAN = BASE_DIR / "laporan"

# Mode demo (python run.py --demo): basis data terpisah berisi riwayat stok hasil simulasi.
DEMO = os.environ.get("PREDISTOK_DEMO") == "1"

# SQLite secara bawaan. Untuk MySQL (sesuai Tabel 3 proposal) isi variabel lingkungan, mis.
#   DATABASE_URL=mysql+pymysql://user:sandi@localhost/predistok
DATABASE_URL = os.environ.get("DATABASE_URL",
                              f"sqlite:///{BASE_DIR / ('predistok_demo.db' if DEMO else 'predistok.db')}")
# Artefak setiap pelatihan disimpan di FOLDER_MODEL/run_<id>, terpisah untuk mode demo.
FOLDER_MODEL = Path(os.environ["PREDISTOK_FOLDER_MODEL"]) if os.environ.get("PREDISTOK_FOLDER_MODEL") \
    else ARTEFAK / ("model_demo" if DEMO else "model")


def _kunci_rahasia() -> str:
    """Kunci penanda sesi login: dari variabel lingkungan, atau dibuat acak sekali lalu disimpan di .kunci_sesi."""
    if os.environ.get("PREDISTOK_SECRET"):
        return os.environ["PREDISTOK_SECRET"]
    f = BASE_DIR / ".kunci_sesi"
    if not f.exists():
        import secrets
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


SECRET_KEY = _kunci_rahasia()

FILE_STOK_KELUAR = DATA_AWAL / "Stok_Keluar_Harian_Bahan_Baku.xlsx"
FILE_EKSPOR_BAHAN = DATA_AWAL / "Ekspor_Daftar_Bahan_Baku_28okt.xlsx"
FILE_RESEP = DATA_AWAL / "Ekspor_Resep_Produk_LF_13okt.xlsx"
FOLDER_CATATAN = DATA_AWAL / "catatan_manual"         # catatan WhatsApp order dan barang masuk (K1 aktual)

NAMA_OUTLET = "Lafabrica Coffee"
NAMA_APLIKASI = "PrediStok"
PENGGUNA_AWAL = ("admin", "admin123")   # wajib diganti setelah login pertama

# ---------------- XGBoost (sama dengan sel PARAMETER notebook) ----------------
SPLIT_MODE = "auto"          # auto / bulan / terakhir
TEST_DAYS = 28
VAL_DAYS = 28
LAGS = [1, 7]
ROLL_WINDOW = 7
HARI_AKHIR_PEKAN = [5, 6]
TARGET_MODE = "koreksi_ma"   # prediksi = MA-7 + koreksi XGBoost
PARAM_GRID = {
    "n_estimators": [100, 200, 400],
    "max_depth": [2, 3, 4],
    "learning_rate": [0.03, 0.05, 0.1],
    "subsample": [0.8, 1.0],
    "colsample_bytree": [0.8, 1.0],
}
MANUAL_PARAMS = {"n_estimators": 100, "max_depth": 2, "learning_rate": 0.03, "subsample": 0.8, "colsample_bytree": 1.0}
FIXED_PARAMS = {"min_child_weight": 1, "reg_lambda": 1.0, "gamma": 0.0,
                "objective": "reg:squarederror", "tree_method": "hist", "random_state": 42}
CV_FOLDS = 4
CV_FOLD_LEN = 7
HORIZON = 7
# Prediksi yang dipakai pada integrasi: "xgboost" (semua bahan) atau "hibrida"
# (bahan yang XGBoost-nya kalah dari baseline di data validasi memakai baseline terbaik).
PREDIKSI_INTEGRASI = "xgboost"
OOS_MIN_HARI = 28            # prediksi out-of-sample expanding window mulai setelah 28 hari data

# ---------------- ROP dan kebijakan ----------------
Z_LAYANAN = 1.65
LEAD_TIME = 1

# ---------------- Biaya (nilai sementara, ganti dengan hasil wawancara) ----------------
BIAYA_PESAN = 2000.0          # c_o: biaya per pesanan satu bahan (Rp), mis. ongkos kirim dibagi jumlah bahan per kiriman
BIAYA_SIMPAN_PERSEN = 0.1     # c_h: persen harga beli per satuan per hari (0,1% per hari)

# ---------------- Q-Learning (Tabel 5) ----------------
QL_EPISODE = 5000
QL_PANJANG_EPISODE = 28       # 4 blok minggu
QL_ALPHA = 0.1
QL_GAMMA = 0.95
QL_EPS_AWAL = 1.0
QL_EPS_AKHIR = 0.01
QL_EPS_SAMPAI = 0.8           # epsilon mencapai 0,01 pada 80% episode, lalu tetap
QL_BIN_IP = 9                 # jumlah interval posisi persediaan
QL_BIN_D = 5                  # jumlah interval prediksi kebutuhan
QL_BIN_E = 5                  # jumlah interval stok hampir kedaluwarsa
QL_M_MAKS = 20                # batas atas m (kelipatan pemesanan maksimum) bila kapasitas simpan belum diisi
QL_MODE_ALPHA = "tetap"       # "tetap" = Persamaan (17); "tak_bias" = langkah tak bias Sutton & Barto (2018)
QL_MIN_KUNJUNGAN = 1          # aksi dipakai saat inferensi bila pernah dicoba sekian kali pada state itu
QL_TUNING_GRID = {"alpha": [0.05, 0.1, 0.2], "gamma": [0.9, 0.95]}

# ---------------- Simulasi K1/K2/K3 ----------------
SIM_STOK_AWAL = [0.0, 0.5, 1.0, 2.0, 3.0]   # kelipatan rata-rata pemakaian harian
SIM_SEED = [11, 22, 33, 44, 55]
