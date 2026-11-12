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

Saat dijalankan, aplikasi menambahkan data bawaan versi baru ke basis data yang lama. Yang ditambahkan hanya yang belum
ada: hari stok keluar yang belum tercatat, hari catatan order atau barang masuk yang belum ada, dan model bawaan bila
datanya lebih baru daripada semua model di riwayat. Model bawaan versi baru dengan data yang sama juga dipasang bila
model aktif adalah model bawaan versi lama (misalnya versi ini menambahkan rincian harian simulasi), tetapi model hasil
Pelatihan Ulang sendiri tidak diganti. Model itu langsung aktif, dan model sebelumnya tetap bisa diaktifkan kembali dari
riwayat Pelatihan Ulang. Nilai bahan yang masih berupa perkiraan dari data (isi kemasan, harga, dan biaya
kehabisan yang belum dikonfirmasi) dihitung ulang seperti pada instalasi baru. Data yang sudah ada di basis data,
termasuk nilai yang diisi atau dikoreksi sendiri, tidak diubah. Untuk mode demo, buat ulang datanya dengan
`jalankan_demo.bat --ulang-demo`.

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
| Setiap hari, selama cafe masih mencatat manual | Inventori → Kelola Stok → **Catatan Barang Masuk** | Tempel laporan WhatsApp "REPORT ORDER tanggal ..." dan "barang masuk hari ini tanggal ...". Beberapa pesan yang diteruskan sekaligus (dengan awalan `[tanggal, jam] nama:`) juga bisa ditempel apa adanya. Aplikasi merapikannya per baris, mencocokkan nama barang dengan data bahan, dan mengubah jumlahnya ke satuan dasar. Barang masuk dipakai Simulasi **K1 aktual**. Catatan ini tidak mengubah Daftar Stok. |

Rekomendasi tidak dihitung bila ada hari dalam 7 hari terakhir yang belum dicatat, karena fitur lag dan rata-rata
bergerak membutuhkan pemakaian 7 hari berturut-turut. Data bawaan berakhir **10 November 2026**, jadi stok keluar sejak
11 November perlu dicatat (atau ditandai tutup) sebelum rekomendasi hari ini bisa dihitung.

### Membaca rekomendasi

- Kolom **Sumber** berisi *Q-Learning* (aksi terbaik di Q-table) atau *Cadangan K2*. Cadangan K2 (aturan order-up-to)
  dipakai bila state hari itu tidak pernah ditemui saat pelatihan.
- Ikon mata membuka perhitungan lengkap satu bahan: Persamaan 21, 24, 25, dan 27 dengan angka, nilai Q setiap aksi,
  kapasitas simpan, serta grafik pemakaian dan prediksi.
- Rekomendasi hanya dibuat untuk **10 bahan target penelitian** (bagian 4), karena model aktif hanya dilatih untuk
  bahan itu. Bahan lain tetap bisa dicatat stok keluar, stok opname, dan pembeliannya, tetapi tidak punya prediksi, ROP
  dinamis, dan jumlah pesan. Untuk memodelkan semua bahan yang lolos saringan data, ubah `CAKUPAN_MODEL = "lolos"` di
  `config.py`, lalu jalankan Pelatihan Ulang.

---

## 3. Menu

| Menu | Isi |
|---|---|
| **Dashboard** | Langkah harian, bahan kritis (posisi ≤ ROP), perkiraan nilai pesanan, pesanan dalam perjalanan, bahan hampir kedaluwarsa, ringkasan model aktif |
| **Rekomendasi** | Rekomendasi Pemesanan (dengan detail per bahan), Prediksi Kebutuhan 7 hari, riwayat, ekspor Excel |
| **Inventori** | Daftar Bahan Baku (format majoo, impor/ekspor Excel, sheet *Parameter PrediStok*), Pembelian Stok, Daftar Stok (awal, masuk, terjual, terbuang, selisih opname, akhir, stok minimum, dalam perjalanan, dan nilai stok per periode, mirip majoo), Kartu Stok per bahan, Stok Keluar Harian, Stok Opname, Stok Terbuang, Catatan Barang Masuk (tempel/impor laporan WhatsApp, unduh Excel terstruktur) |
| **Analisis Model** | Evaluasi Prediksi (praproses dan pemilihan 10 bahan target, XGBoost dibanding naive mingguan, MA-7, dan rata-rata historis), Simulasi K1/K2/K3 (K1 aktual dan K1 statis, Tabel 4, asal biaya dan neraca nilai barang, rincian per bahan dengan sisa stok setiap hari, unduh laporan Excel), Pelatihan Ulang beserta riwayat model |
| **Pengaturan** | Biaya pesan dan biaya simpan, opsi pelatihan, pengguna, kata sandi |

**Hak akses.** *Admin* bisa melakukan semuanya. *Staf* bisa mencatat stok keluar, stok opname, dan stok terbuang,
menghitung rekomendasi, serta membuat dan menerima pesanan. Staf tidak bisa mengubah data bahan, pengaturan, model,
atau pengguna.

---

## 4. Metode (ringkas)

**Data.** Stok keluar harian 1 Juli – 10 November 2026 (133 hari, 172 bahan, 22.876 baris) dari
`Stok_Keluar_Harian_Bahan_Baku.xlsx`, hasil perkalian transaksi penjualan majoo dengan resep produk
(`alat/bangun_stok_keluar.py`, sumber di `data_awal/penjualan/`). Daftar bahan dari ekspor majoo (191 bahan, 179
dimonitor). Resep produk dipakai untuk memperkirakan harga (HPP) dan biaya kehabisan (margin menu). Pembagian waktu:
**latih** 1 Jul – 15 Sep, **validasi** 16 Sep – 13 Okt, **uji** 14 Okt – 10 Nov 2026 (28 hari).

**Praproses dan bahan target** (`ml/praproses.py`). Keduanya dihitung dari data sebelum periode uji (1 Jul – 13 Okt,
105 hari), supaya data uji tidak ikut menentukan bahan yang diteliti.

- **Saringan data.** Bahan dikeluarkan dari dataset bila *kosong* (tidak pernah terpakai, 4 bahan) atau *didominasi
  nilai 0* (103 bahan). Didominasi nilai 0 berarti jarak rata-rata antarhari pemakaian (ADI = jumlah hari ÷ jumlah hari
  terpakai) lebih dari 1,32, yaitu pemakaian 0 pada lebih dari 24,2% hari. Angka 1,32 adalah batas pola permintaan
  intermiten pada klasifikasi Syntetos, Boylan & Croston (2005). Yang lolos 65 dari 172 bahan.
- **Bahan target.** Dari 65 bahan itu diambil yang cepat rusak (masa simpan ≤ 30 hari sesuai batasan masalah) dan bukan
  kelompok Air & Minuman, tersisa 30 bahan. Bahan diurutkan menurut rata-rata dua peringkat: seberapa sering dipakai
  (proporsi hari terpakai) dan seberapa besar nilai pemakaiannya per hari (rata-rata pemakaian × harga satuan). Sepuluh
  teratas menjadi bahan target.

| # | Bahan target | Masa simpan | Hari terpakai | Rata-rata per hari | Nilai pemakaian per hari | Peringkat frekuensi / nilai |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Beans Arabica (BB01) | 30 hari | 105 / 105 | 781 g | Rp 258.484 | 1 / 1 |
| 2 | Beans House Blend (BB02) | 30 hari | 105 / 105 | 426 g | Rp 82.068 | 1 / 2 |
| 3 | Fresh Milk (BB08) | 7 hari | 105 / 105 | 2.762 g | Rp 65.827 | 1 / 3 |
| 4 | Telur (ST001) | 14 hari | 105 / 105 | 20,4 pcs | Rp 33.525 | 1 / 5 |
| 5 | SKM (BB19) | 30 hari | 105 / 105 | 748 g | Rp 33.078 | 1 / 6 |
| 6 | Gold Label (BB18) | 30 hari | 105 / 105 | 148 g | Rp 6.762 | 1 / 16 |
| 7 | Timun (BB46) | 5 hari | 105 / 105 | 563 g | Rp 6.278 | 1 / 17 |
| 8 | Kentang (BB93) | 21 hari | 103 / 105 | 867 g | Rp 27.532 | 13 / 7 |
| 9 | Powder Beans Wine (BB20) | 30 hari | 104 / 105 | 52 g | Rp 18.788 | 10 / 10 |
| 10 | Ayam Penyet (BB132) | 3 hari | 100 / 105 | 4,3 pcs | Rp 25.543 | 15 / 8 |

Urutan berikutnya adalah Daun Pre, Selada (harga keduanya masih asumsi kelompok), dan Ayam Slice. Beras dipakai setiap
hari dan nilainya besar, tetapi masa simpannya 180 hari sehingga bukan bahan cepat rusak. Daftar target dikunci di
`config.BAHAN_TARGET` supaya tidak bergeser ketika data bertambah. Tabel pemilihan tetap dihitung ulang pada setiap
pelatihan dan ditampilkan di halaman Evaluasi Prediksi serta lembar *Aturan Pemilihan* dan *Pemilihan Bahan* di
`evaluasi_xgboost.xlsx`.

Model hanya dilatih dan diuji pada 10 bahan target (`CAKUPAN_MODEL = "target"`). Akurasi pada 10 bahan itu tidak
berkurang: nRMSE rata-rata XGBoost 0,405 bila dilatih pada 10 bahan, 0,405 pada 65 bahan yang lolos saringan, dan 0,403
pada 143 bahan yang punya riwayat (MA-7 0,423).

1. **XGBoost** (subbab 8.4–8.5, porting dari notebook). Satu model global untuk semua bahan.
   - Fitur: lag 1 dan 7, rata-rata dan simpangan baku bergerak 7 hari, hari, akhir pekan, identitas bahan.
   - Data dinormalisasi terhadap rata-rata data latih (Persamaan 7). Targetnya adalah koreksi terhadap MA-7.
   - Grid search 108 kombinasi dengan validasi silang *rolling origin* 4 lipatan mingguan. Hasil terbaik:
     `n_estimators` 100, `max_depth` 2, `learning_rate` 0,03, `subsample` 0,8, `colsample_bytree` 0,8.
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
   - Pelatihan 5.000 episode × 28 hari, dari 10 minggu prediksi *out-of-sample* sebelum periode uji.
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
   - Setiap run mencatat rincian harian: stok sebelum, ROP, barang datang, terbuang, pemakaian, kekurangan, sisa stok
     akhir hari (setara hasil stok opname setelah pemakaian hari itu), dan biaya per komponen. Dari catatan ini terlihat
     asal setiap komponen biaya: simpan = c_h × jumlah sisa harian, kehabisan = c_s × kekurangan, terbuang = harga ×
     jumlah terbuang, pesan = c_o × jumlah pemesanan. Neraca setiap run: stok awal + barang datang = terpakai +
     terbuang + sisa stok akhir.
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

## 5. Hasil model aktif (pelatihan 11 November 2026, data stok keluar s.d. 10 November 2026)

**Prediksi (periode uji 14 Oktober – 10 November, 10 bahan target).** Galat dinormalisasi terhadap rata-rata pemakaian
data latih setiap bahan.

| Metode | nMAE rata-rata | nRMSE rata-rata | nRMSE median | XGBoost lebih akurat |
|---|---:|---:|---:|---:|
| XGBoost (koreksi MA-7) | **0,336** | **0,405** | **0,375** | |
| Rata-rata bergerak 7 hari (MA-7) | 0,343 | 0,423 | 0,390 | 8 dari 10 bahan |
| Rata-rata historis | 0,406 | 0,476 | 0,513 | 9 dari 10 bahan |
| Naive mingguan | 0,448 | 0,560 | 0,579 | 10 dari 10 bahan |

nRMSE XGBoost per bahan: Beans Arabica 0,19; SKM 0,24; Beans House Blend 0,28; Fresh Milk 0,28; Timun 0,37; Telur 0,38;
Kentang 0,46; Gold Label 0,53; Ayam Penyet 0,66; Powder Beans Wine 0,67. MA-7 lebih akurat pada Beans Arabica dan
Powder Beans Wine. Keunggulan XGBoost atas MA-7 kecil (nRMSE rata-rata 4% lebih rendah), jadi yang bisa disimpulkan
adalah XGBoost tidak lebih buruk daripada pembanding terbaik dan lebih akurat pada sebagian besar bahan. Galat prediksi
rekursif 1 sampai 7 hari ke depan naik sedikit, dari nMAE 0,344 ke 0,362.

**Simulasi 28 hari, 10 bahan target:**

| | K1 statis (ROP statis + EOQ) | K2 ROP dinamis + order-up-to | K3 ROP dinamis + Q-Learning |
|---|---:|---:|---:|
| Total biaya 28 hari (TC) | Rp 2.292.657 | **Rp 476.106** | Rp 485.143 |
| Fill rate (FR) | 98,0% | 99,9% | **99,9%** |
| Rasio terbuang (WR) | 11,0% | **3,2%** | 5,7% |
| Hari kehabisan (bahan-hari) | 6,6 | 0,8 | **0,4** |

Hasil uji per bahan (Wilcoxon satu arah):

- K3 lebih murah daripada K1 pada 8 dari 10 bahan (p = 0,0068, median rasio biaya 0,50).
- K2 lebih murah daripada K1 pada 9 dari 10 bahan (p = 0,0068, median rasio 0,69).
- K3 dibanding K2 **tidak berbeda nyata**: K3 lebih murah pada 5 dari 10 bahan (p = 0,385, median rasio 1,00), dan
  total biayanya 1,9% lebih tinggi daripada K2.

Jadi pada 10 bahan ini kedua kebijakan dengan ROP dinamis memangkas sekitar 79% biaya K1 statis, tetapi Q-Learning belum
terbukti lebih murah daripada aturan order-up-to. K3 lebih murah pada Fresh Milk, Ayam Penyet, Kentang, dan Gold Label,
dan lebih mahal pada Telur (Rp 83.593 dibanding Rp 16.593) serta Timun. Biaya K1 statis terkumpul di empat bahan
(Timun, Fresh Milk, Telur, dan Ayam Penyet, 94% TC), karena pesanan EOQ yang jarang dan besar membuat bahan itu
bergantian kehabisan dan terbuang.

**Asal biaya dan sisa stok, 10 bahan target 28 hari (rata-rata semua run).** Persen adalah bagian dari TC. Neraca nilai
barang memakai harga beli: stok awal + barang datang = terpakai + terbuang + sisa stok akhir.

| | K1 statis | K2 | K3 |
|---|---:|---:|---:|
| Biaya simpan | Rp 79.381 (3,5%) | Rp 42.419 (8,9%) | Rp 59.396 (12,2%) |
| Biaya kehabisan | Rp 1.304.371 (56,9%) | Rp 63.551 (13,3%) | Rp 15.532 (3,2%) |
| Biaya terbuang | Rp 828.505 (36,1%) | Rp 205.336 (43,1%) | Rp 264.775 (54,6%) |
| Biaya pesan | Rp 80.400 (3,5%) | Rp 164.800 (34,6%) | Rp 145.440 (30,0%) |
| Jumlah pemesanan | 40,2 | 82,4 | 72,7 |
| Nilai stok awal | Rp 731.229 | Rp 731.229 | Rp 731.229 |
| Nilai barang datang | Rp 15.827.688 | Rp 14.087.540 | Rp 14.799.215 |
| Nilai terpakai | Rp 12.900.833 | Rp 12.996.189 | Rp 12.994.527 |
| Nilai terbuang | Rp 828.505 | Rp 205.336 | Rp 264.775 |
| Nilai sisa stok akhir (malam 10 November) | Rp 2.829.579 | Rp 1.617.244 | Rp 2.271.142 |

Dibanding K2, K3 menekan biaya kehabisan (Rp 15.532 dibanding Rp 63.551) dan lebih jarang memesan, tetapi membuang lebih
banyak (Rp 264.775 dibanding Rp 205.336) dan menyimpan stok lebih banyak, sehingga totalnya hampir sama.

**K1 aktual (24 Oktober – 10 November 2026, 18 hari, 8 bahan target).** Barang masuk dari catatan WhatsApp diputar
ulang dengan taksiran stok awal aktual. SKM tidak ikut karena isi 1 dus atau 1 kotak belum diketahui, dan Powder Beans
Wine tidak punya catatan barang masuk pada periode itu.

| | K1 aktual | K1 statis | K2 | K3 |
|---|---:|---:|---:|---:|
| Total biaya 18 hari | Rp 2.283.172 | Rp 1.058.634 | Rp 204.617 | **Rp 165.040** |
| Fill rate | 97,6% | 98,0% | 100% | 100% |
| Biaya terbuang | Rp 679.688 | Rp 489.005 | Rp 82.909 | Rp 41.197 |
| Biaya kehabisan | Rp 1.433.324 | Rp 479.753 | Rp 0 | Rp 2.858 |
| Nilai sisa stok akhir | Rp 5.244.393 | Rp 2.063.256 | Rp 1.116.042 | Rp 1.933.969 |

K3 dan K2 masing-masing lebih murah daripada K1 aktual pada 7 dari 8 bahan, tetapi dengan 8 bahan uji Wilcoxon belum
nyata pada taraf 5% (p = 0,055 untuk keduanya). Pada uji kepekaan dengan lima tingkat stok awal, p = 0,008 (K3) dan
0,020 (K2). K3 dibanding K2 tidak berbeda nyata (p = 0,23).

Hasil K1 aktual perlu dibaca hati-hati karena dua hal:

- **81% biaya K1 aktual berasal dari Fresh Milk (Rp 1.844.243).** Catatan hanya memuat dua kali barang masuk: 3 dus
  pada 29 Oktober (dibaca 36 kg, 1 dus = 12 botol 1.000 g menurut data bahan) dan 6 botol pada 4 November, sedangkan
  pemakaian menurut resep 44,2 kg. Dengan masa simpan 7 hari, simulasi membuang 16,9 kg pada 5 November lalu kehabisan
  pada 7–10 November. Penjualan pada hari itu
  tetap berjalan, jadi kemungkinan besar susu 29 Oktober masih dipakai setelah 7 hari (masa simpan sebenarnya lebih
  panjang) atau ada pembelian yang tidak tercatat. Tanpa Fresh Milk, total 7 bahan lainnya adalah K1 aktual Rp 438.929,
  K1 statis Rp 981.090, K2 Rp 186.842, dan K3 Rp 150.564.
- **Barang masuk beberapa bahan jauh di atas pemakaian menurut resep.** Selama 18 hari: Timun 49 kg dibanding 6,2 kg,
  Gold Label 13,6 kg dibanding 3,3 kg, Telur 600 butir dibanding 185, dan Kentang 27 kg dibanding 9,1 kg. Kemungkinan
  penyebabnya pemakaian di luar resep (lalapan, makan karyawan), takaran resep yang kurang tepat, atau stok untuk lebih
  dari 18 hari. Untuk Ayam Penyet keduanya hampir sama (93 ekor masuk, 92 pcs terpakai).

Jadi selisih K3 dan K2 terhadap K1 aktual adalah batas atas sampai kedua hal itu dikonfirmasi ke cafe (bagian 6).
Semua angka biaya juga masih bergantung pada parameter sementara di bagian 6.

Laporan lengkap ada di folder `laporan/`. `evaluasi_xgboost.xlsx` memuat metrik per bahan dan per horizon, serta lembar *Aturan Pemilihan* dan *Pemilihan Bahan*
(statistik 172 bahan, alasan bahan dikeluarkan, dan peringkat bahan target).
`simulasi_K1_K2_K3.xlsx` memuat Tabel 4, komponen biaya, per bahan, dan tuning, ditambah lembar rincian:
- *Cara Membaca Rincian*: arti setiap kolom dan rumus komponen biaya.
- *Rincian Biaya*: komponen biaya (Rp dan persen dari TC) dan neraca nilai barang per kebijakan dan kelompok bahan.
- *Rincian Per Bahan*: untuk setiap bahan dan kebijakan, parameter biaya, neraca barang, sisa stok akhir periode, dan
  dasar perhitungan setiap komponen (rata-rata semua run).
- *Harian Uji* dan *Sisa Stok Harian*: catatan harian satu run contoh (stok awal 1 × rata-rata pemakaian, K3 seed
  pertama) dan sisa stok akhir setiap hari, untuk semua bahan.
- *Rincian K1 Aktual* dan *Harian K1 Aktual*: hal yang sama untuk periode K1 aktual (taksiran stok awal aktual).

Keduanya juga bisa diunduh dari menu Analisis Model. Di halaman Simulasi, klik nama bahan untuk melihat rincian bahan
itu: asal biaya, neraca barang, grafik sisa stok, dan catatan harian setiap kebijakan untuk stok awal dan seed yang
dipilih.

---

## 6. Data yang masih kurang

Daftar ini diurutkan dari yang paling berpengaruh. Semua angka di bawah berasal dari data bawaan.

1. **Stok fisik awal (stok opname).** Data majoo hanya berisi stok keluar, sehingga posisi stok tidak diketahui. Tanpa
   satu kali stok opname, aplikasi baru menghitung ROP dan belum menghitung jumlah pesan.
2. **Stok keluar sejak 11 November 2026 dan laporan barang masuk setiap hari.** Data majoo sampai 10 November sudah
   dimasukkan. Mulai 11 November, isi stok keluar setiap hari di menu Stok Keluar Harian, karena rekomendasi membutuhkan
   catatan 7 hari terakhir yang lengkap. Laporan barang masuk WhatsApp juga perlu ditempel setiap hari agar periode
   K1 aktual bertambah.
3. **Masa simpan Fresh Milk dan pembelian susu yang tidak tercatat.** Masa simpan Fresh Milk masih nilai umum 7 hari,
   padahal catatan menunjukkan 3 dus (dibaca 36 kg) yang masuk 29 Oktober dipakai sampai sekitar 10 November. Tanyakan masa
   simpan susu yang dipakai (Greenfields) dan apakah ada pembelian susu lain yang tidak ditulis di laporan. Hal ini
   menentukan 81% biaya K1 aktual (bagian 5).
4. **Pemakaian di luar resep.** Barang masuk Timun, Telur, Gold Label, dan Kentang 3 sampai 8 kali pemakaian menurut
   resep (bagian 5). Tanyakan ke cafe apakah ada pemakaian yang tidak tercatat di majoo, misalnya lalapan, bahan untuk
   makan karyawan, atau telur untuk menu yang resepnya belum memuat telur. Bila pemakaian sebenarnya lebih besar,
   prediksi dan rekomendasi untuk bahan itu ikut terlalu kecil.
5. **Konfirmasi catatan barang masuk untuk bahan target.** Unduh Excel di Catatan Barang Masuk, lalu cek lembar
   *Perlu Dicek* dengan staf cafe. Untuk 10 bahan target yang perlu dipastikan: isi 1 dus dan 1 kotak SKM (sekarang
   SKM tidak ikut K1 aktual), "Gold label 3 kotak" (dianggap 3 botol 907 g), "Ayam penyet 5 ekor" (majoo mencatat Pcs
   dengan 1 ekor = 1 pcs, sedangkan catatan 1 November menulis 5 ekor = 20 potong), 1 bag beans (dianggap 1.000 g), dan
   "kentang goreng 1000gr (2bks)" (dibaca 2 × 1.000 g). Untuk bahan lain: isi kemasan yang masih ditebak (misalnya 1
   bungkus kerupuk, 1 sisir pisang, 1 dus minyak makan yang ditulis "6 bks 13 liter"), dua pesan "barang masuk bar
   kitchen" 9 November yang sama-sama memuat Alpukat 3 kg (keduanya dihitung), dan barang yang belum terdaftar di data
   bahan (gabin, donat, cabe giling, terasi, lemon, beans Ciwidey, kue kering).
6. **Biaya pesan (c_o) dan biaya simpan (c_h).** Nilai Rp 2.000 per pesanan per bahan dan 0,1% harga per hari masih
   sementara. Biaya pesan kini 30–35% TC pada K2 dan K3, jadi nilainya sangat menentukan perbandingan K2 dan K3. Isi di
   menu **Pengaturan** atau di sheet *Biaya Umum* pada template.
7. **Ukuran kemasan beli.** Dari 10 bahan target, kemasan Beans House Blend, SKM, Powder Beans Wine, Timun, Kentang, dan
   Ayam Penyet masih ukuran sementara. Catatan barang masuk menunjukkan Beans House Blend dibeli per pack 1.000 g
   (sementara: 5.000 g) dan kentang goreng per bungkus 1.000 g (sementara: 500 g). Secara keseluruhan hanya 27 bahan yang punya konversi satuan di majoo dan 4 bahan memakai ukuran umum. Ada
   160 bahan yang masih memakai ukuran sementara hasil hitungan dari pemakaian. Ukuran kemasan menentukan kelipatan
   pesan (Persamaan 28).
8. **Harga beli per satuan dasar.** Harga 10 bahan target diperkirakan dari HPP resep majoo. Secara keseluruhan 96 bahan diperkirakan dari HPP resep majoo dan 95 bahan memakai nilai umum
   kelompok. Harga memengaruhi biaya simpan dan biaya terbuang.
9. **Masa simpan per bahan.** Semua bahan masih memakai nilai umum kelompok, misalnya 180 hari (46 bahan), 3 hari
   (35 bahan), 30 hari (32 bahan), dan 5 hari (30 bahan). Yang paling berpengaruh adalah ayam, daging, dan seafood
   yang kini bernilai 3 hari. Bila bahan ini disimpan beku, isi masa simpan sebenarnya, karena sebagian besar nilai
   terbuang K1 aktual berasal dari bahan-bahan ini.
10. **Biaya kehabisan (c_s).** 168 bahan dihitung dari margin menu dan 23 bahan memakai 2 × harga. Bumbu yang dipakai
   sangat sedikit per porsi menghasilkan nilai ekstrem. Totole, Sasa, Merica, dan Garam bernilai sekitar
   Rp 163.000–179.000 per gram, atau 5.400–6.000 kali harganya. Untuk bahan seperti ini, biaya beli darurat di warung
   terdekat lebih masuk akal.
11. **Kapasitas simpan maksimum** (dalam kemasan) belum diisi untuk satu bahan pun, jadi masih dihitung otomatis.
12. **Waktu tunggu pemasok (lead time)** diasumsikan 1 hari untuk semua bahan. Catatan WhatsApp 24 Oktober –
    10 November mendukung asumsi ini untuk sebagian besar order: dari 628 baris order per bahan per hari yang bisa
    dibandingkan, 495 (79%) tercatat masuk keesokan harinya dan 393 (63%) dengan jumlah yang persis sama (lembar *Order
    vs Masuk*). Kolom Lead Time sudah dipakai untuk ROP, stok target, dan perkiraan tanggal barang tiba. Namun
    Q-Learning dan simulasi masih dilatih dengan L = 1 hari sesuai proposal.
13. **169 bahan dimonitor berada di luar bahan target**, sehingga tidak punya prediksi dan Q-table. Ini sesuai cakupan
    penelitian (10 bahan). Bila semua bahan yang lolos saringan data ingin direkomendasikan, ubah `CAKUPAN_MODEL` di
    `config.py` menjadi `"lolos"` dan jalankan Pelatihan Ulang.
14. **Satuan Jasmine Tea** tercatat "Kantung" dengan pemakaian sekitar 635 per hari. Kemungkinan satuan sebenarnya gram.

**Cara melengkapi:**

1. Buka `Template_Data_Master_PrediStok.xlsx` (atau unduh dari Inventori → Daftar Bahan Baku → Ekspor).
2. Di sheet **Parameter PrediStok**, ganti nilai di sel berwarna kuning dengan data sebenarnya, lalu tulis **Y** di kolom
   *Data sudah benar (Y/T)* untuk baris yang sudah benar.
3. Impor file itu lewat tombol **Impor Bahan Baku** di halaman Daftar Bahan Baku.
4. Jalankan **Analisis Model → Pelatihan Ulang (lengkap)** agar Q-table dan simulasi memakai data baru.

Sheet *Ekspor Daftar Bahan Baku* mengikuti format ekspor majoo. Kolom Stok Minimum di sana sudah berisi ROP dinamis per
10 November 2026 untuk 10 bahan target, sedangkan bahan lain memakai stok minimum dari majoo. Bila majoo menerima impor dengan format yang sama, kolom ini bisa dipakai untuk memperbarui
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
8. Dataset disaring lebih dulu (bahan kosong dan bahan yang didominasi nilai 0 dikeluarkan), lalu penelitian dibatasi
   pada 10 bahan target: bahan cepat rusak (masa simpan ≤ 30 hari, bukan Air & Minuman) yang paling sering dipakai dan
   paling besar nilai pemakaiannya (bagian 4). Sebelumnya "bahan utama" adalah semua bahan cepat rusak yang dipakai pada
   ≥ 50% hari data.
9. K1 pada proposal (ROP statis + EOQ) disimpan sebagai **K1 statis**. Karena cafe kini mencatat barang masuk secara
   manual, ditambahkan **K1 aktual** yang memutar ulang barang yang benar-benar diterima (bagian 4 nomor 8) sebagai
   pembanding praktik cafe yang sebenarnya.
10. Model global XGBoost dan Q-table hanya dilatih untuk 10 bahan target, bukan semua bahan, sehingga rekomendasi
    aplikasi juga hanya untuk 10 bahan itu.

---

## 8. Struktur folder

```
aplikasi/
├─ jalankan.bat, jalankan_demo.bat, jalankan.sh   peluncur
├─ run.py          menyiapkan basis data lalu menjalankan server
├─ config.py       parameter tetap (Z, L, biaya bawaan, Q-Learning, pembagian data, saringan data dan bahan target)
├─ app/            aplikasi web (FastAPI, SQLAlchemy, Jinja2)
│  ├─ rute/        halaman: bahan, stok, rekomendasi, pembelian, model, pengaturan
│  ├─ layanan/     buku stok FIFO, rekomendasi harian, impor/ekspor Excel, pelatihan, catatan_manual (WhatsApp)
│  ├─ templates/   tampilan HTML
│  ├─ static/      CSS, JS, Chart.js (tersimpan lokal, tanpa CDN)
│  ├─ seed.py      pengisian awal (dan pembaruan versi) dari data_awal dan artefak
│  └─ demo.py      riwayat simulasi untuk mode demo
├─ ml/             praproses.py (saringan data dan bahan target), xgb.py, kebijakan.py, lingkungan.py, qlearning.py,
│                  simulasi.py, rincian.py, master.py, pipeline.py
├─ data_awal/      file Excel dari majoo (bahan, resep, stok keluar harian); penjualan/ berisi ekspor transaksi
│                  sumber stok keluar; catatan_manual/ berisi laporan WhatsApp order dan barang masuk
├─ alat/           bangun_stok_keluar.py: transaksi penjualan x resep -> stok keluar harian per bahan;
│                  rapikan_catatan.py: catatan WhatsApp -> Excel terstruktur
├─ artefak/        model hasil pelatihan awal (XGBoost, Q-table, evaluasi)
├─ laporan/        laporan Excel untuk Bab 4
└─ tests/          uji otomatis
```

**Pelatihan ulang.** Buka Analisis Model → Pelatihan Ulang. Mode *lengkap* (grid search XGBoost, tuning α/γ, 5 seed)
memakan sekitar 4 menit di komputer pengujian (10 bahan target). Mode *cepat* memakai hiperparameter model aktif. Model baru langsung
aktif, dan model lama bisa diaktifkan kembali dari riwayat. Dari baris perintah, jalankan
`.venv\Scripts\python -m ml.pipeline --tuning`. Perintah ini menulis ulang folder `artefak` dan `laporan`.

**Basis data.** Data tersimpan di satu file SQLite, `predistok.db`. Untuk cadangan, salin file itu (beserta
`predistok.db-wal` bila ada) saat aplikasi ditutup. Pemakaian MySQL dimungkinkan lewat SQLAlchemy tetapi **belum diuji**.
Caranya: pasang `pymysql`, lalu atur variabel lingkungan
`DATABASE_URL=mysql+pymysql://user:sandi@localhost/predistok?charset=utf8mb4` sebelum menjalankan.

**Pengujian.** `.venv\Scripts\python -m pytest` menjalankan 37 uji. Cakupannya: saringan nilai 0 dan peringkat bahan target, rumus Persamaan 1–3, 17, 21, dan
25–28, lingkungan FIFO, batas kapasitas, jadwal ε, K1 aktual (pemutaran ulang barang masuk, taksiran stok awal,
rentang hari berlaporan), perapian catatan WhatsApp (jumlah, satuan, pecahan, pencocokan bahan, pesan yang diteruskan, kiriman ulang, daftar
belanja), alur harian lewat
HTTP (opname, rekomendasi, pesan, terima, hari belum tercatat, kafe tutup), alur Catatan Barang Masuk (tempel, unduh,
koreksi, impor, hapus), pembaruan basis data dari versi sebelumnya (data bawaan baru ditambahkan tanpa mengubah data
lama, model bawaan baru dengan data yang sama hanya menggantikan model bawaan lama), rincian harian simulasi (total
harian sama dengan total setiap run, neraca barang seimbang) dan halaman rincian per bahan, CSRF, hak akses, serta
impor/ekspor Excel.

**Keamanan.** Secara bawaan server hanya bisa dibuka dari komputer itu sendiri (127.0.0.1). Setiap halaman wajib login
dan setiap formulir memakai token CSRF. Kunci sesi dibuat acak saat pertama dijalankan dan disimpan di `.kunci_sesi`.
Jangan bagikan file itu.
