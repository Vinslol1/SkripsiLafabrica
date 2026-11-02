# PrediStok: Rekomendasi Pemesanan Bahan Baku Lafabrica Coffee

Aplikasi web lokal untuk penelitian skripsi Muhammad Kevin Gibran Lubis (231401065). Halaman **Daftar Bahan Baku** dan
**Daftar Stok** dibuat mengikuti tampilan majoo. Di atasnya ditambahkan alur pada proposal (Gambar 3):

1. prediksi pemakaian harian dengan XGBoost (target koreksi MA-7, `TARGET_MODE = "koreksi_ma"`),
2. ROP dinamis (Persamaan 21) yang ditulis ke **Stok Minimum** setiap bahan,
3. rekomendasi jumlah pesan dengan Q-Learning (Persamaan 27–31),
4. simulasi pembanding K1, K2, K3 (Tabel 4) untuk Bab 4. K1 ada dua versi: **K1 aktual** memutar ulang barang
   yang benar-benar diterima cafe (catatan barang masuk WhatsApp), dan **K1 statis** (ROP statis + EOQ).

Semua berjalan di komputer sendiri. Tidak ada data yang dikirim ke internet.

---

## 1. Menjalankan di Windows 11

1. Pasang **Python 3.12 atau 3.13** dari <https://www.python.org/downloads/>. Saat instalasi, centang
   **Add python.exe to PATH**.
2. Salin folder `aplikasi` (atau ekstrak `PrediStok.zip`) ke folder biasa, misalnya `D:\PrediStok`. Sebaiknya bukan
   folder OneDrive yang sedang sinkron, karena file basis data bisa terkunci.
3. Klik dua kali **`jalankan.bat`**. Saat pertama kali, file ini membuat lingkungan Python `.venv` dan memasang pustaka.
   Langkah ini perlu internet dan memakan waktu 3–10 menit. Setelah itu browser terbuka sendiri di
   <http://localhost:8000>.
4. Masuk dengan **`admin` / `admin123`**, lalu ganti kata sandi di **Pengaturan**.
5. Untuk berhenti, tutup jendela hitam (Command Prompt).

Saat pertama dijalankan, basis data `predistok.db` diisi dari folder `data_awal` (tiga file Excel asli) dan model hasil
pelatihan awal di folder `artefak`.

### Memperbarui ke versi baru

Ekstrak `PrediStok.zip` yang baru ke folder yang sama dan pilih **Replace** untuk semua file. Basis data
(`predistok.db`), lingkungan Python (`.venv`), dan kunci sesi tidak ada di dalam zip, jadi semuanya tetap tersimpan.
Bila daftar pustaka di `requirements.txt` berubah, `jalankan.bat` memasang pustaka yang kurang saat dijalankan
berikutnya tanpa menghapus `.venv`.

### Mode demo untuk presentasi

Klik dua kali **`jalankan_demo.bat`**. Mode ini memakai basis data terpisah (`predistok_demo.db`) yang berisi riwayat
4 minggu terakhir, sehingga semua halaman terisi contoh. Stok keluarnya adalah data asli. Stok opname awal, pembelian,
stok terbuang, dan pembelian darurat adalah hasil simulasi kebijakan K3. Data demo tidak mengubah data utama. Untuk
membuat ulang data demo, jalankan `jalankan_demo.bat --ulang-demo`.

### Opsi tambahan

Opsi ditulis di belakang perintah, misalnya `jalankan.bat --port 8080`:

| Opsi | Fungsi |
|---|---|
| `--port 8080` | memakai port lain bila 8000 sudah dipakai |
| `--host 0.0.0.0` | bisa dibuka dari HP atau laptop lain di Wi-Fi yang sama lewat `http://<IP-komputer>:8000` (izinkan di Windows Firewall) |
| `--tanpa-browser` | tidak membuka browser otomatis |

Di macOS/Linux, jalankan `./jalankan.sh` (bisa ditambah `--demo`).

---

## 2. Alur kerja harian (Gambar 3)

| Kapan | Menu | Yang dilakukan |
|---|---|---|
| Sekali di awal, lalu berkala (misalnya mingguan) | Inventori → **Stok Opname** | Catat stok fisik. Tanpa stok opname, posisi stok tidak diketahui, jadi aplikasi hanya menghitung ROP dan belum menghitung jumlah pesan. |
| Setiap akhir hari | Inventori → **Stok Keluar Harian** | Isi pemakaian hari itu secara manual, impor Excel (kolom `Tanggal`, `SKU`, `Jumlah Keluar`), atau impor ekspor Daftar Stok majoo (kolom `SKU` dan `TERJUAL`). Untuk hari libur, tekan **Tandai kafe tutup** (pemakaian 0). |
| Setelah stok keluar tercatat | Rekomendasi → **Hitung Rekomendasi** | Prediksi XGBoost untuk besok dan lusa, lalu ROP dinamis (ditulis ke Stok Minimum), state, dan jumlah pesan dari Q-table. |
| Setelah memeriksa rekomendasi | Rekomendasi → centang bahan → **Buat Pesanan** | Membuat pesanan pembelian (PO). Jumlahnya masih bisa diubah. Barang dihitung sebagai stok dalam perjalanan. |
| Awal hari berikutnya | Inventori → Pembelian Stok → buka pesanan → **Terima pesanan** | Barang masuk sebagai batch baru (FIFO) dengan tanggal kedaluwarsa = tanggal terima + masa simpan. |
| Bila ada bahan dibuang | Inventori → **Stok Terbuang** | Halaman ini menandai batch yang sudah atau hampir melewati masa simpan. |
| Setiap hari, selama cafe masih mencatat manual | Inventori → Kelola Stok → **Catatan Barang Masuk** | Tempel laporan WhatsApp "REPORT ORDER tanggal ..." dan "barang masuk hari ini tanggal ...". Aplikasi merapikannya per baris, mencocokkan nama barang dengan data bahan, dan mengubah jumlahnya ke satuan dasar. Barang masuk dipakai Simulasi **K1 aktual**. Catatan ini tidak mengubah Daftar Stok. |

Rekomendasi tidak dihitung bila ada hari dalam 7 hari terakhir yang belum dicatat, karena fitur lag dan rata-rata
bergerak membutuhkan pemakaian 7 hari berturut-turut. Data bawaan berakhir **25 Oktober 2026**, jadi stok keluar sejak
26 Oktober perlu dicatat (atau ditandai tutup) sebelum rekomendasi hari ini bisa dihitung.

### Membaca rekomendasi

- Kolom **Sumber** berisi *Q-Learning* (aksi terbaik di Q-table) atau *Cadangan K2*. Cadangan K2 (aturan order-up-to)
  dipakai bila state hari itu tidak pernah ditemui saat pelatihan.
- Ikon mata membuka perhitungan lengkap satu bahan: Persamaan 21, 24, 25, dan 27 dengan angka, nilai Q setiap aksi,
  kapasitas simpan, serta grafik pemakaian dan prediksi.
- K3 bisa sengaja merekomendasikan **0** untuk bahan cepat rusak yang jarang dipakai. Contohnya Bomboloni: hanya
  dipakai 2 pcs dalam 28 hari, dengan masa simpan 3 hari. Di sini perkiraan biaya terbuang lebih besar daripada biaya
  kehabisan. Jumlah tetap bisa diubah sebelum pesanan dibuat.

---

## 3. Menu

| Menu | Isi |
|---|---|
| **Dashboard** | Langkah harian, bahan kritis (posisi ≤ ROP), perkiraan nilai pesanan, pesanan dalam perjalanan, bahan hampir kedaluwarsa, ringkasan model aktif |
| **Rekomendasi** | Rekomendasi Pemesanan (dengan detail per bahan), Prediksi Kebutuhan 7 hari, riwayat, ekspor Excel |
| **Inventori** | Daftar Bahan Baku (format majoo, impor/ekspor Excel, sheet *Parameter PrediStok*), Pembelian Stok, Daftar Stok (awal, masuk, terjual, terbuang, selisih opname, akhir, stok minimum, dalam perjalanan, dan nilai stok per periode, mirip majoo), Kartu Stok per bahan, Stok Keluar Harian, Stok Opname, Stok Terbuang, Catatan Barang Masuk (tempel/impor laporan WhatsApp, unduh Excel terstruktur) |
| **Analisis Model** | Evaluasi Prediksi (XGBoost dibanding naive mingguan, MA-7, dan rata-rata historis), Simulasi K1/K2/K3 (K1 aktual dan K1 statis, Tabel 4, unduh laporan Excel), Pelatihan Ulang beserta riwayat model |
| **Pengaturan** | Biaya pesan dan biaya simpan, opsi pelatihan, pengguna, kata sandi |

**Hak akses.** *Admin* bisa melakukan semuanya. *Staf* bisa mencatat stok keluar, stok opname, dan stok terbuang,
menghitung rekomendasi, serta membuat dan menerima pesanan. Staf tidak bisa mengubah data bahan, pengaturan, model,
atau pengguna.

---

## 4. Metode (ringkas)

**Data.** Stok keluar harian 1 Juli – 25 Oktober 2026 (117 hari, 20.124 baris) dari `Stok_Keluar_Harian_Bahan_Baku.xlsx`.
Daftar bahan dari ekspor majoo (191 bahan, 179 dimonitor). Resep produk dipakai untuk memperkirakan harga (HPP) dan
biaya kehabisan (margin menu). Pembagian waktu: **latih** 1 Jul – 30 Agu, **validasi** 31 Agu – 27 Sep, **uji**
28 Sep – 25 Okt 2026 (28 hari). Ada 140 bahan yang memiliki riwayat cukup untuk dimodelkan.

1. **XGBoost** (subbab 8.4–8.5, porting dari notebook). Satu model global untuk semua bahan.
   - Fitur: lag 1 dan 7, rata-rata dan simpangan baku bergerak 7 hari, hari, akhir pekan, identitas bahan.
   - Data dinormalisasi terhadap rata-rata data latih (Persamaan 7). Targetnya adalah koreksi terhadap MA-7.
   - Grid search 108 kombinasi dengan validasi silang *rolling origin* 4 lipatan mingguan. Hasil terbaik:
     `n_estimators` 100, `max_depth` 2, `learning_rate` 0,03, `subsample` 0,8, `colsample_bytree` 1,0.
   - σe diambil dari galat *out-of-sample* (Persamaan 22–23). Prediksi dibuat rekursif hingga 7 hari.
2. **ROP dinamis** (21): ROP = ŷ(t+1) + Z·σe·√L, dengan Z = 1,65 dan L = 1 hari. Nilainya ditulis ke Stok Minimum.
3. **Stok target** (25): OUT = ŷ(t+1) + ŷ(t+2) + Z·σe·√(L+1).
4. **K1 statis** = ROP statis (1–2) + EOQ (3). **K1 aktual** = barang yang benar-benar diterima cafe (bagian 4
   nomor 8). **K2** = ROP dinamis + order-up-to (26). **K3** = ROP dinamis + Q-Learning.
5. **Q-Learning (K3).**
   - State (27): 9 interval posisi persediaan × 5 interval prediksi kebutuhan × 5 interval stok hampir kedaluwarsa ×
     penanda IP ≤ ROP, sehingga ada 450 state.
   - Aksi (28): pesan i × k, dengan i = 0..m dan k = isi kemasan.
   - Reward (31): −(biaya simpan + kehabisan + terbuang + pesan). Pembaruan nilai Q memakai Persamaan 17.
   - ε turun dari 1 ke 0,01.
   - α dan γ dipilih dari {0,05; 0,1; 0,2} × {0,9; 0,95} berdasarkan total biaya periode validasi. Terpilih
     α = 0,2 dan γ = 0,9.
   - Pelatihan 5.000 episode × 28 hari.
6. **Kapasitas simpan.** Sebuah aksi hanya boleh dipilih bila IP + i·k ≤ kapasitas (aksi 0 selalu boleh). Aturan ini
   berlaku saat pelatihan, saat simulasi ketiga kebijakan, dan pada rekomendasi harian.
   - Bila kolom *Kapasitas Simpan Maks (kemasan)* diisi, kapasitas = isian × k.
   - Bila kosong, kapasitas dihitung otomatis: maks(1,2 × OUT terbesar di data latih, ROP_K1 + Q_K1), dibulatkan ke
     atas ke kemasan, minimal 2 kemasan, dengan m antara 2 dan 20.
7. **Simulasi (Tabel 4).** 28 hari uji, dengan lingkungan yang sama untuk K1, K2, dan K3.
   - Keputusan diambil di akhir hari dan pesanan tiba di awal hari berikutnya.
   - Stok dipakai FIFO dan dibuang setelah melewati masa simpan. Kekurangan dihitung sebagai penjualan hilang.
   - Ada 5 tingkat stok awal (0; 0,5; 1; 2; 3 × rata-rata harian) dan 5 seed.
   - Metrik: TC (34), FR (35), WR (36), dan hari kehabisan. Perbandingan per bahan memakai uji Wilcoxon.
8. **K1 aktual (data histori cafe).** Barang masuk dari catatan WhatsApp cafe diputar ulang apa adanya: jumlah yang
   tercatat masuk pada hari t tiba di awal hari t (tanpa pembulatan kemasan dan tanpa batas kapasitas), lalu dipakai
   pemakaian aktual hari itu di lingkungan yang sama dengan nomor 7.
   - **Periode** = hari berurutan yang punya laporan barang masuk dan juga punya data stok keluar, di dalam periode uji.
     Hari tanpa laporan menghentikan periode, karena barang masuk hari itu tidak diketahui.
   - **Bahan** = bahan yang dimodelkan dan punya barang masuk tercatat di periode itu. Bahan dengan barang masuk yang
     isi kemasannya belum diketahui (misalnya SKM per dus) dikecualikan.
   - **Stok awal.** Skenario utama memakai taksiran stok awal aktual, yaitu stok terkecil yang membuat barang masuk
     aktual cukup untuk pemakaian aktual setiap hari: maks_t Σ(pemakaian − barang masuk). Pemakaian di stok keluar
     benar-benar terjadi, jadi stok cafe paling sedikit sebesar itu. K1 statis, K2, dan K3 mulai dari stok yang sama.
     Lima tingkat stok awal seperti nomor 7 dihitung sebagai uji kepekaan.
   - Perbandingan per bahan: K3, K2, dan K1 statis masing-masing dibanding K1 aktual, serta K3 dibanding K2 (Wilcoxon
     satu arah). Hasil dengan periode kurang dari 7 hari ditandai belum layak disimpulkan.

---

## 5. Hasil model aktif (pelatihan awal, data stok keluar s.d. 25 Oktober 2026)

**Prediksi (periode uji, 140 bahan).** nRMSE median XGBoost **0,794**. Pembanding: MA-7 0,850, rata-rata historis
0,925, naive mingguan 1,190. RMSE XGBoost lebih kecil daripada MA-7 pada **114 dari 140** bahan.

**Simulasi 28 hari, bahan utama (47 bahan cepat rusak yang rutin dipakai):**

| | K1 statis (ROP statis + EOQ) | K2 ROP dinamis + order-up-to | K3 ROP dinamis + Q-Learning |
|---|---:|---:|---:|
| Total biaya 28 hari (TC) | Rp 8.250.039 | Rp 6.338.814 | **Rp 3.981.405** |
| Fill rate (FR) | 94,3% | 95,5% | **98,0%** |
| Rasio terbuang (WR) | 24,9% | 20,6% | **19,8%** |
| Hari kehabisan (bahan-hari) | 66,8 | 50,6 | **27,8** |

Hasil uji per bahan:

- K3 lebih murah daripada K1 pada 38 dari 47 bahan (p Wilcoxon = 4,9 × 10⁻⁸, median rasio biaya 0,70).
- K3 lebih murah daripada K2 pada 37 dari 47 bahan (p = 1,6 × 10⁻⁶, median rasio 0,75).
- K2 lebih murah daripada K1 pada 27 dari 47 bahan (p = 0,031, median rasio 0,95).

**Simulasi, semua bahan (140):**

- TC: K1 Rp 11.768.239, K2 Rp 10.416.119, K3 Rp 6.870.764.
- FR: 95,9% / 97,0% / 95,4%.
- K3 lebih murah daripada K2 pada 99 dari 140 bahan (p = 6,4 × 10⁻¹⁰) dan daripada K1 pada 81 dari 140 bahan
  (p = 0,0011).
- K2 dibanding K1 tidak berbeda nyata (p = 0,82).

**K1 aktual.** Catatan barang masuk tersedia 24 Oktober – 1 November 2026, sedangkan stok keluar baru sampai
25 Oktober. Jadi K1 aktual pada model ini hanya mencakup 2 hari (24–25 Oktober, 53 bahan) dan ditandai belum layak disimpulkan.
Setelah stok keluar majoo 26 Oktober – 1 November (dan catatan minggu berikutnya) diimpor, jalankan Pelatihan Ulang.

Pada kelompok semua bahan, fill rate K3 sedikit di bawah K2. Penyebabnya, untuk bahan cepat rusak yang jarang dipakai,
Q-Learning memilih tidak menyetok bila perkiraan biaya terbuang lebih besar daripada biaya kehabisan. Semua angka biaya
masih bergantung pada parameter sementara di bagian 6.

Laporan lengkap ada di folder `laporan/`. `evaluasi_xgboost.xlsx` memuat metrik per bahan dan per horizon.
`simulasi_K1_K2_K3.xlsx` memuat Tabel 4, komponen biaya, per bahan, dan tuning. Keduanya juga bisa diunduh dari menu
Analisis Model.

---

## 6. Data yang masih kurang

Daftar ini diurutkan dari yang paling berpengaruh. Semua angka di bawah berasal dari data bawaan.

1. **Stok fisik awal (stok opname).** Data majoo hanya berisi stok keluar, sehingga posisi stok tidak diketahui. Tanpa
   satu kali stok opname, aplikasi baru menghitung ROP dan belum menghitung jumlah pesan.
2. **Stok keluar sejak 26 Oktober 2026.** Rekomendasi membutuhkan catatan 7 hari terakhir yang lengkap. Data ini
   juga dibutuhkan K1 aktual: catatan barang masuk sudah ada sampai 1 November, tetapi baru beririsan 2 hari dengan
   stok keluar.
3. **Konfirmasi catatan barang masuk.** Unduh Excel di Catatan Barang Masuk, lalu cek lembar *Perlu Dicek* dengan staf
   cafe: isi kemasan yang masih ditebak (misalnya 1 bungkus kerupuk, 1 sisir pisang, 1 buah paprika), nama yang
   dicocokkan dengan asumsi (madu bar depan/belakang, ayam dada, ubi roti), dan barang yang belum terdaftar di data
   bahan (gabin, donat, cabe giling, terasi, lemon, beans Ciwidey, sawi manis bar belakang, rosemary).
4. **Biaya pesan (c_o) dan biaya simpan (c_h).** Nilai Rp 2.000 per pesanan per bahan dan 0,1% harga per hari masih
   sementara. Karena c_h kecil, Q-Learning (dan EOQ pada K1) cenderung memesan banyak sekaligus untuk bahan yang cukup
   tahan lama. Contohnya Kentang: 10 kg, sementara aturan K2 menyarankan 2 kg. Isi di menu **Pengaturan** atau di sheet
   *Biaya Umum* pada template.
5. **Ukuran kemasan beli.** Hanya 27 bahan yang punya konversi satuan di majoo dan 4 bahan memakai ukuran umum. Ada
   160 bahan yang masih memakai ukuran sementara hasil hitungan dari pemakaian. Ukuran kemasan menentukan kelipatan
   pesan (Persamaan 28).
6. **Harga beli per satuan dasar.** 96 bahan diperkirakan dari HPP resep majoo dan 95 bahan memakai nilai umum
   kelompok. Harga memengaruhi biaya simpan dan biaya terbuang.
7. **Masa simpan per bahan.** Semua bahan masih memakai nilai umum kelompok, misalnya 180 hari (46 bahan), 3 hari
   (35 bahan), 30 hari (32 bahan), dan 5 hari (30 bahan).
8. **Biaya kehabisan (c_s).** 168 bahan dihitung dari margin menu dan 23 bahan memakai 2 × harga. Bumbu yang dipakai
   sangat sedikit per porsi menghasilkan nilai ekstrem. Totole, Sasa, Merica, dan Garam bernilai sekitar
   Rp 163.000–179.000 per gram, atau 5.400–6.000 kali harganya. Untuk bahan seperti ini, biaya beli darurat di warung
   terdekat lebih masuk akal.
9. **Kapasitas simpan maksimum** (dalam kemasan) belum diisi untuk satu bahan pun, jadi masih dihitung otomatis.
10. **Waktu tunggu pemasok (lead time)** diasumsikan 1 hari untuk semua bahan. Catatan WhatsApp 24–31 Oktober
    mendukung asumsi ini: dari 232 baris order yang mencantumkan jumlah, 216 (93%) datang keesokan harinya dan 204
    (88%) datang tepat sesuai jumlah order (lembar *Order vs Masuk*). Kolom Lead Time sudah dipakai untuk ROP, stok
    target, dan perkiraan tanggal barang tiba. Namun Q-Learning dan simulasi masih dilatih dengan L = 1 hari sesuai
    proposal.
11. **46 bahan dimonitor belum punya riwayat pemakaian** yang cukup, sehingga belum punya prediksi dan Q-table. Jalankan
    Pelatihan Ulang setelah datanya terkumpul, atau ubah Monitor menjadi T bila bahan tersebut tidak perlu dipantau.
12. **Satuan Jasmine Tea** tercatat "Kantung" dengan pemakaian sekitar 635 per hari. Kemungkinan satuan sebenarnya gram.

**Cara melengkapi:**

1. Buka `Template_Data_Master_PrediStok.xlsx` (atau unduh dari Inventori → Daftar Bahan Baku → Ekspor).
2. Di sheet **Parameter PrediStok**, ganti nilai di sel berwarna kuning dengan data sebenarnya, lalu tulis **Y** di kolom
   *Data sudah benar (Y/T)* untuk baris yang sudah benar.
3. Impor file itu lewat tombol **Impor Bahan Baku** di halaman Daftar Bahan Baku.
4. Jalankan **Analisis Model → Pelatihan Ulang (lengkap)** agar Q-table dan simulasi memakai data baru.

Sheet *Ekspor Daftar Bahan Baku* mengikuti format ekspor majoo, dan kolom Stok Minimum di sana sudah berisi ROP
dinamis per 25 Oktober 2026. Bila majoo menerima impor dengan format yang sama, kolom ini bisa dipakai untuk memperbarui
stok minimum di majoo (belum dicoba).

---

## 7. Penyesuaian terhadap proposal (untuk dicatat di Bab 3/4)

1. ε turun secara eksponensial dari 1 ke 0,01 sampai 80% episode, lalu tetap 0,01. Tidak memakai *early stopping*.
   Sebagai gantinya, kurva pembelajaran (biaya per episode) ditampilkan di halaman Simulasi.
2. Batas kapasitas simpan ditambahkan pada pemilihan aksi dan pada ketiga kebijakan. Bila kapasitas belum diketahui,
   kapasitas dan m ditentukan otomatis (bagian 4 nomor 6). Tanpa batas ini, agen cenderung menimbun bahan yang biaya
   simpannya kecil.
3. Saat inferensi, aksi terbaik hanya dipilih di antara aksi yang pernah dicoba pada state itu. State yang tidak pernah
   ditemui memakai aturan K2.
4. Simpangan baku bergerak memakai pembagi w (ddof = 0) seperti notebook, sedangkan Persamaan 6 memakai w − 1.
5. Setiap episode pelatihan terdiri dari 4 minggu acak dari prediksi *out-of-sample*, dengan stok awal acak 0–3 ×
   rata-rata harian. Untuk simulasi, minggu yang dipakai hanya yang sebelum periode uji. Model yang dipakai aplikasi
   dilatih ulang dengan semua minggu.
6. Q pada K1 (EOQ) dibatasi pemakaian selama masa simpan, lalu dibulatkan ke atas ke kemasan.
7. Kekurangan stok dianggap penjualan hilang (*lost sales*), bukan *backorder*.
8. "Bahan utama" didefinisikan sebagai bahan dengan masa simpan ≤ 30 hari yang dipakai pada ≥ 50% hari data, tanpa
   kelompok Air & Minuman.
9. K1 pada proposal (ROP statis + EOQ) disimpan sebagai **K1 statis**. Karena cafe kini mencatat barang masuk secara
   manual, ditambahkan **K1 aktual** yang memutar ulang barang yang benar-benar diterima (bagian 4 nomor 8) sebagai
   pembanding praktik cafe yang sebenarnya.

---

## 8. Struktur folder

```
aplikasi/
├─ jalankan.bat, jalankan_demo.bat, jalankan.sh   peluncur
├─ run.py          menyiapkan basis data lalu menjalankan server
├─ config.py       parameter tetap (Z, L, biaya bawaan, Q-Learning, pembagian data)
├─ app/            aplikasi web (FastAPI, SQLAlchemy, Jinja2)
│  ├─ rute/        halaman: bahan, stok, rekomendasi, pembelian, model, pengaturan
│  ├─ layanan/     buku stok FIFO, rekomendasi harian, impor/ekspor Excel, pelatihan, catatan_manual (WhatsApp)
│  ├─ templates/   tampilan HTML
│  ├─ static/      CSS, JS, Chart.js (tersimpan lokal, tanpa CDN)
│  ├─ seed.py      pengisian awal dari data_awal dan artefak
│  └─ demo.py      riwayat simulasi untuk mode demo
├─ ml/             xgb.py, kebijakan.py, lingkungan.py, qlearning.py, simulasi.py, master.py, pipeline.py
├─ data_awal/      tiga file Excel asli dari majoo; catatan_manual/ berisi laporan WhatsApp order dan barang masuk
├─ alat/           rapikan_catatan.py: catatan WhatsApp -> Excel terstruktur dari baris perintah
├─ artefak/        model hasil pelatihan awal (XGBoost, Q-table, evaluasi)
├─ laporan/        laporan Excel untuk Bab 4
└─ tests/          uji otomatis
```

**Pelatihan ulang.** Buka Analisis Model → Pelatihan Ulang. Mode *lengkap* (grid search XGBoost, tuning α/γ, 5 seed)
memakan sekitar 12 menit di komputer pengujian. Mode *cepat* memakai hiperparameter model aktif. Model baru langsung
aktif, dan model lama bisa diaktifkan kembali dari riwayat. Dari baris perintah, jalankan
`.venv\Scripts\python -m ml.pipeline --tuning`. Perintah ini menulis ulang folder `artefak` dan `laporan`.

**Basis data.** Data tersimpan di satu file SQLite, `predistok.db`. Untuk cadangan, salin file itu (beserta
`predistok.db-wal` bila ada) saat aplikasi ditutup. Pemakaian MySQL dimungkinkan lewat SQLAlchemy tetapi **belum diuji**.
Caranya: pasang `pymysql`, lalu atur variabel lingkungan
`DATABASE_URL=mysql+pymysql://user:sandi@localhost/predistok?charset=utf8mb4` sebelum menjalankan.

**Pengujian.** `.venv\Scripts\python -m pytest` menjalankan 29 uji. Cakupannya: rumus Persamaan 1–3, 17, 21, dan
25–28, lingkungan FIFO, batas kapasitas, jadwal ε, K1 aktual (pemutaran ulang barang masuk, taksiran stok awal,
rentang hari berlaporan), perapian catatan WhatsApp (jumlah, satuan, pecahan, pencocokan bahan), alur harian lewat
HTTP (opname, rekomendasi, pesan, terima, hari belum tercatat, kafe tutup), alur Catatan Barang Masuk (tempel, unduh,
koreksi, impor, hapus), CSRF, hak akses, serta impor/ekspor Excel.

**Keamanan.** Secara bawaan server hanya bisa dibuka dari komputer itu sendiri (127.0.0.1). Setiap halaman wajib login
dan setiap formulir memakai token CSRF. Kunci sesi dibuat acak saat pertama dijalankan dan disimpan di `.kunci_sesi`.
Jangan bagikan file itu.
