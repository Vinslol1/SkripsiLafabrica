# PrediStok: Rekomendasi Pemesanan Bahan Baku Lafabrica Coffee

Aplikasi web lokal untuk penelitian skripsi Muhammad Kevin Gibran Lubis (231401065). Halaman **Daftar Bahan Baku** dan
**Daftar Stok** dibuat mengikuti tampilan majoo. Di atasnya ditambahkan alur pada proposal (Gambar 3):

1. prediksi pemakaian harian dengan XGBoost (target koreksi MA-7, `TARGET_MODE = "koreksi_ma"`),
2. ROP dinamis (Persamaan 21) yang ditulis ke **Stok Minimum** setiap bahan,
3. rekomendasi jumlah pesan dengan Q-Learning (Persamaan 27–31),
4. simulasi pembanding K1–K4 (Tabel 4) untuk Bab 4: **K1** data historis (barang yang benar-benar diterima cafe
   menurut catatan barang masuk WhatsApp, diputar ulang dan dilengkapi dengan augmentasi agar stok selalu cukup untuk
   penjualan, lihat bagian 4 nomor 8 dan subbagian *Data asli dan data augmentasi*), **K2** ROP statis + EOQ, **K3** ROP dinamis + order-up-to,
   dan **K4** ROP dinamis + Q-Learning.

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
stok terbuang, dan pembelian darurat adalah hasil simulasi kebijakan K4. Data demo tidak mengubah data utama. Untuk
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
| Setiap hari, selama cafe masih mencatat manual | Inventori → Kelola Stok → **Catatan Barang Masuk** | Tempel laporan WhatsApp "REPORT ORDER tanggal ..." dan "barang masuk hari ini tanggal ...". Beberapa pesan yang diteruskan sekaligus (dengan awalan `[tanggal, jam] nama:`) juga bisa ditempel apa adanya. Aplikasi merapikannya per baris, mencocokkan nama barang dengan data bahan, dan mengubah jumlahnya ke satuan dasar. Barang masuk dipakai Simulasi **K1**. Catatan ini tidak mengubah Daftar Stok. |

Rekomendasi tidak dihitung bila ada hari dalam 7 hari terakhir yang belum dicatat, karena fitur lag dan rata-rata
bergerak membutuhkan pemakaian 7 hari berturut-turut. Data bawaan berakhir **23 November 2026**, jadi stok keluar sejak
24 November perlu dicatat (atau ditandai tutup) sebelum rekomendasi hari ini bisa dihitung.

### Membaca rekomendasi

- Kolom **Sumber** berisi *Q-Learning* (aksi terbaik di Q-table) atau *Cadangan K3*. Cadangan K3 (aturan order-up-to)
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
| **Analisis Model** | Evaluasi Prediksi (praproses dan pemilihan 10 bahan target, XGBoost dibanding naive mingguan, MA-7, dan rata-rata historis), Simulasi K1–K4 (Tabel 4, asal biaya dan neraca nilai barang, rincian per bahan dengan sisa stok setiap hari, unduh laporan Excel), Pelatihan Ulang beserta riwayat model |
| **Pengaturan** | Biaya pesan dan biaya simpan, opsi pelatihan, pengguna, kata sandi |

**Hak akses.** *Admin* bisa melakukan semuanya. *Staf* bisa mencatat stok keluar, stok opname, dan stok terbuang,
menghitung rekomendasi, serta membuat dan menerima pesanan. Staf tidak bisa mengubah data bahan, pengaturan, model,
atau pengguna.

---

## 4. Metode (ringkas)

**Data.** Stok keluar harian 1 Juli – 23 November 2026 (146 hari, 172 bahan) dari
`Stok_Keluar_Harian_Bahan_Baku.xlsx`, hasil perkalian transaksi penjualan majoo dengan resep produk
(`alat/bangun_stok_keluar.py`, sumber di `data_awal/penjualan/`). Daftar bahan dari ekspor majoo (191 bahan, 179
dimonitor). Resep produk dipakai untuk memperkirakan harga (HPP) dan biaya kehabisan (margin menu). Pembagian waktu:
**latih** 1 Jul – 28 Sep, **validasi** 29 Sep – 26 Okt, **uji** 27 Okt – 23 Nov 2026 (28 hari terakhir).

**Praproses dan bahan target** (`ml/praproses.py`). Keduanya dihitung dari data sebelum periode uji (1 Jul – 26 Okt,
118 hari), supaya data uji tidak ikut menentukan bahan yang diteliti.

- **Saringan data.** Bahan dikeluarkan dari dataset bila *kosong* (tidak pernah terpakai, 4 bahan) atau *didominasi
  nilai 0* (105 bahan). Didominasi nilai 0 berarti jarak rata-rata antarhari pemakaian (ADI = jumlah hari ÷ jumlah hari
  terpakai) lebih dari 1,32, yaitu pemakaian 0 pada lebih dari 24,2% hari. Angka 1,32 adalah batas pola permintaan
  intermiten pada klasifikasi Syntetos, Boylan & Croston (2005). Yang lolos 63 dari 172 bahan.
- **Bahan target.** Dari 63 bahan itu diambil yang cepat rusak (masa simpan ≤ 30 hari sesuai batasan masalah) dan bukan
  kelompok Air & Minuman, tersisa 28 bahan. Bahan diurutkan menurut rata-rata dua peringkat: seberapa sering dipakai
  (proporsi hari terpakai) dan seberapa besar nilai pemakaiannya per hari (rata-rata pemakaian × harga satuan). Sepuluh
  teratas menjadi bahan target.

| # | Bahan target | Masa simpan | Hari terpakai | Rata-rata per hari | Nilai pemakaian per hari | Peringkat frekuensi / nilai |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Beans Arabica (BB01) | 30 hari | 118 / 118 | 765 g | Rp 253.179 | 1 / 1 |
| 2 | Beans House Blend (BB02) | 30 hari | 118 / 118 | 424 g | Rp 81.616 | 1 / 2 |
| 3 | Fresh Milk (BB08) | 7 hari | 118 / 118 | 2.722 g | Rp 64.867 | 1 / 3 |
| 4 | SKM (BB19) | 30 hari | 118 / 118 | 728 g | Rp 32.170 | 1 / 4 |
| 5 | Telur (ST001) | 14 hari | 118 / 118 | 19,1 pcs | Rp 31.347 | 1 / 5 |
| 6 | Gold Label (BB18) | 30 hari | 118 / 118 | 150 g | Rp 6.855 | 1 / 14 |
| 7 | Timun (BB46) | 5 hari | 118 / 118 | 532 g | Rp 5.932 | 1 / 15 |
| 8 | Powder Beans Wine (BB20) | 30 hari | 117 / 118 | 53 g | Rp 19.010 | 10 / 8 |
| 9 | Kentang (BB93) | 21 hari | 114 / 118 | 822 g | Rp 26.113 | 14 / 6 |
| 10 | Ayam Penyet (BB132) | 3 hari | 113 / 118 | 4,3 pcs | Rp 25.678 | 15 / 7 |

Urutan berikutnya adalah Daun Pre, Selada (harga keduanya masih asumsi kelompok), dan Ayam Slice. Beras dipakai setiap
hari dan nilainya besar, tetapi masa simpannya 180 hari sehingga bukan bahan cepat rusak. Daftar target dikunci di
`config.BAHAN_TARGET` supaya tidak bergeser ketika data bertambah. Tabel pemilihan tetap dihitung ulang pada setiap
pelatihan dan ditampilkan di halaman Evaluasi Prediksi serta lembar *Aturan Pemilihan* dan *Pemilihan Bahan* di
`evaluasi_xgboost.xlsx`.

Model hanya dilatih dan diuji pada 10 bahan target (`CAKUPAN_MODEL = "target"`). Pada pelatihan sebelumnya (uji
14 Okt – 10 Nov) akurasi pada 10 bahan itu tidak berkurang dibanding model yang dilatih pada lebih banyak bahan: nRMSE rata-rata XGBoost 0,405 bila dilatih pada 10 bahan, 0,405 pada 65 bahan yang lolos saringan, dan 0,403
pada 143 bahan yang punya riwayat (MA-7 0,423).

1. **XGBoost** (subbab 8.4–8.5, porting dari notebook). Satu model global untuk semua bahan.
   - Fitur: lag 1 dan 7, rata-rata dan simpangan baku bergerak 7 hari, hari, akhir pekan, identitas bahan.
   - Data dinormalisasi terhadap rata-rata data latih (Persamaan 7). Targetnya adalah koreksi terhadap MA-7.
   - Grid search 108 kombinasi dengan validasi silang *rolling origin* 4 lipatan mingguan. Hasil terbaik:
     `n_estimators` 100, `max_depth` 2, `learning_rate` 0,03, `subsample` 0,8, `colsample_bytree` 0,8.
   - σe diambil dari galat *out-of-sample* (Persamaan 22–23). Prediksi dibuat rekursif hingga 7 hari.
2. **ROP dinamis** (21): ROP = ŷ(t+1) + Z·σe·√L, dengan Z = 1,65 dan L = 1 hari. Nilainya ditulis ke Stok Minimum.
3. **Stok target** (25): OUT = ŷ(t+1) + ŷ(t+2) + Z·σe·√(L+1).
4. **K2** = ROP statis (1–2) + EOQ (3). **K1** = barang yang benar-benar diterima cafe (bagian 4
   nomor 8). **K3** = ROP dinamis + order-up-to (26). **K4** = ROP dinamis + Q-Learning.
5. **Q-Learning (K4).**
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
   - Bila kosong, kapasitas dihitung otomatis: maks(1,2 × OUT terbesar di data latih, ROP_K2 + Q_K2), dibulatkan ke
     atas ke kemasan, minimal 2 kemasan, dengan m antara 2 dan 20.
7. **Simulasi (Tabel 4).** 28 hari uji, dengan lingkungan yang sama untuk K2, K3, dan K4.
   - Keputusan diambil di akhir hari dan pesanan tiba di awal hari berikutnya.
   - Stok dipakai FIFO dan dibuang setelah melewati masa simpan. Kekurangan dihitung sebagai penjualan hilang.
   - Ada 5 tingkat stok awal (0; 0,5; 1; 2; 3 × rata-rata harian) dan 5 seed.
   - Metrik: TC (34), FR (35), WR (36), dan hari kehabisan. Perbandingan per bahan memakai uji Wilcoxon.
   - Setiap run mencatat rincian harian: stok sebelum, ROP, barang datang, terbuang, pemakaian, kekurangan, sisa stok
     akhir hari (setara hasil stok opname setelah pemakaian hari itu), dan biaya per komponen. Dari catatan ini terlihat
     asal setiap komponen biaya: simpan = c_h × jumlah sisa harian, kehabisan = c_s × kekurangan, terbuang = harga ×
     jumlah terbuang, pesan = c_o × jumlah pemesanan. Neraca setiap run: stok awal + barang datang = terpakai +
     terbuang + sisa stok akhir.
8. **K1 (data historis cafe).** Barang masuk dari catatan WhatsApp cafe diputar ulang apa adanya: jumlah yang
   tercatat masuk pada hari t tiba di awal hari t (tanpa pembulatan kemasan dan tanpa batas kapasitas), lalu dipakai
   pemakaian aktual hari itu di lingkungan yang sama dengan nomor 7.
   - **Augmentasi (melengkapi data historis, `config.K1_LENGKAPI = True`).** Karena K1 adalah kejadian nyata,
     penjualan yang tercatat di majoo pasti terlayani, jadi stok cafe pasti cukup. Bila pada hari t stok yang masih
     layak pakai (setelah bahan yang lewat masa simpan dibuang) ditambah barang masuk tercatat hari t kurang dari
     pemakaian aktual hari t, selisihnya dianggap **pembelian yang tidak tercatat** di laporan WhatsApp dan
     ditambahkan pada pagi hari t, tepat sebesar kekurangan itu:
     tambahan_t = maks(0, pemakaian_t − stok layak pakai_t − barang masuk tercatat_t).
     Ini tambahan terkecil yang membuat data konsisten, sehingga K1 **tidak pernah kehabisan stok** (fill rate 100%,
     biaya kehabisan 0) dan biaya K1 tidak dibesar-besarkan. Barang datang K1 = barang masuk tercatat + tambahan.
     Hari yang mendapat tambahan dihitung sebagai hari pemesanan (biaya pesan). Aturan yang sama berlaku pada
     kelima tingkat stok awal uji kepekaan. Dengan `K1_LENGKAPI = False`, K1 kembali memutar ulang catatan apa adanya.
   - **Periode** = hari berurutan yang punya laporan barang masuk dan juga punya data stok keluar, di dalam periode uji.
     Hari tanpa laporan menghentikan periode, karena barang masuk hari itu tidak diketahui.
   - **Bahan** = bahan yang dimodelkan dan punya barang masuk tercatat di periode itu. Bahan dengan barang masuk yang
     isi kemasannya belum diketahui (misalnya SKM per dus) dikecualikan.
   - **Stok awal.** Skenario utama memakai taksiran stok awal aktual, yaitu stok terkecil yang membuat barang masuk
     tercatat cukup untuk pemakaian aktual selama stok awal itu masih layak pakai: maks Σ(pemakaian − barang masuk)
     pada τ − 1 hari pertama (τ = masa simpan). Stok awal yang lebih besar akan terbuang sebelum terpakai, jadi
     kekurangan sesudahnya dilengkapi oleh augmentasi, bukan oleh stok awal. K2, K3, dan K4 mulai dari stok yang sama.
     Lima tingkat stok awal seperti nomor 7 dihitung sebagai uji kepekaan.
   - Perbandingan per bahan: K4, K3, dan K2 masing-masing dibanding K1, serta K4 dibanding K3 (Wilcoxon
     satu arah). Hasil dengan periode kurang dari 7 hari ditandai belum layak disimpulkan.

---

## 5. Hasil model aktif (pelatihan 26 November 2026, data stok keluar s.d. 23 November 2026)

**Prediksi (periode uji 27 Oktober – 23 November, 10 bahan target).** Galat dinormalisasi terhadap rata-rata pemakaian
data latih setiap bahan. Hiperparameter terpilih: 100 pohon, kedalaman 3, laju belajar 0,03.

| Metode | nMAE rata-rata | nRMSE rata-rata | nRMSE median | XGBoost lebih akurat |
|---|---:|---:|---:|---:|
| XGBoost (koreksi MA-7) | **0,290** | **0,362** | **0,308** | |
| Rata-rata bergerak 7 hari (MA-7) | 0,297 | 0,375 | 0,313 | 9 dari 10 bahan |
| Rata-rata historis | 0,372 | 0,445 | 0,458 | 8 dari 10 bahan |
| Naive mingguan | 0,367 | 0,456 | 0,324 | 10 dari 10 bahan |

nRMSE XGBoost per bahan: Beans Arabica 0,18; SKM 0,21; Timun 0,28; Fresh Milk 0,30; Beans House Blend 0,30; Telur 0,31;
Kentang 0,44; Gold Label 0,46; Powder Beans Wine 0,54; Ayam Penyet 0,60. MA-7 sedikit lebih akurat hanya pada Beans
House Blend. Keunggulan XGBoost atas MA-7 kecil (nRMSE rata-rata 3,6% lebih rendah), jadi yang bisa disimpulkan adalah
XGBoost tidak lebih buruk daripada pembanding terbaik dan lebih akurat pada sebagian besar bahan. Galat prediksi rekursif
1 sampai 7 hari ke depan naik sedikit, dari nMAE 0,289 ke 0,305.

**Hasil simulasi biaya K1–K4 (27 Oktober – 23 November 2026, 28 hari, 8 bahan target, pelatihan 26 November 2026).**
Ini tabel utama di halaman Simulasi dan lembar pertama `simulasi_K1_K2_K3_K4.xlsx`. Keempat kebijakan memakai hari, bahan,
dan stok awal yang sama (taksiran stok awal aktual). K1 memutar ulang barang masuk dari catatan WhatsApp **ditambah barang
masuk hasil augmentasi** (bagian 4 nomor 8), sehingga K1 tidak pernah kehabisan stok. Untuk 20–23 November cafe hanya
mengirim orderan, jadi barang masuk tanggal itu dianggap sama dengan orderan malam sebelumnya (pola ini cocok dengan laporan
11–19 November; berkasnya `Catatan_WA_20-23nov_2026_dari_orderan.txt`, item orderan tanpa jumlah tidak dimasukkan).
SKM tidak ikut karena isi 1 dus atau 1 kotak belum diketahui, dan Powder Beans Wine tidak punya catatan barang masuk.
Q-Learning: α = 0,1, γ = 0,95 (dipilih pada data validasi), 5.000 episode, 5 seed.

| | K1 data historis (dilengkapi) | K2 ROP statis + EOQ | K3 ROP dinamis + order-up-to | K4 ROP dinamis + Q-Learning |
|---|---:|---:|---:|---:|
| Biaya simpan | Rp 105.600 (5,3%) | Rp 63.553 (3,4%) | Rp 35.899 (6,5%) | Rp 50.397 (9,3%) |
| Biaya kehabisan | **Rp 0 (0%)** | Rp 902.240 (48,6%) | Rp 114.327 (20,7%) | Rp 37.156 (6,8%) |
| Biaya terbuang | Rp 1.703.956 (85,4%) | Rp 820.877 (44,3%) | Rp 251.076 (45,5%) | Rp 320.279 (58,8%) |
| Biaya pesan | Rp 186.000 (9,3%) | Rp 68.000 (3,7%) | Rp 150.000 (27,2%) | Rp 136.800 (25,1%) |
| **Total biaya 28 hari (TC)** | Rp 1.995.556 | Rp 1.854.670 | Rp 551.302 | **Rp 544.632** |
| Fill rate | **100%** | 98,0% | 99,2% | 99,7% |
| Rasio terbuang | 15,9% | 12,8% | **3,7%** | 7,0% |
| Hari kehabisan (bahan-hari) | **0** | 5,0 | 2,0 | 0,8 |
| Pemesanan / kedatangan | 93 | 34 | 75 | 68,4 |

Hasil uji per bahan (Wilcoxon satu arah, 8 bahan):

- K4 lebih murah daripada K1 pada 7 dari 8 bahan (p = 0,039, median rasio biaya 0,45).
- K3 lebih murah daripada K1 pada 7 dari 8 bahan (p = 0,039, median rasio 0,55).
- K2 dibanding K1 tidak berbeda nyata (6 dari 8 bahan, p = 0,27).
- K4 dibanding K3 tidak berbeda nyata (4 dari 8 bahan, p = 0,41), total K4 1,2% lebih rendah.

Pada uji kepekaan dengan lima tingkat stok awal (K1 juga dilengkapi pada setiap tingkat, fill rate K1 tetap 100%), K4 dan
K3 tetap nyata lebih murah daripada K1 (p = 0,039 untuk keduanya; total K1 Rp 2.052.042, K2 Rp 2.065.576, K3 Rp 565.069,
K4 Rp 573.413).

Cara membaca hasil K1:

- **Biaya K1 sekarang hampir seluruhnya biaya terbuang (85%)**, karena barang masuk beberapa bahan jauh di atas pemakaian
  menurut resep. Selama 28 hari: Timun 79 kg masuk dibanding 9,3 kg terpakai, Telur 1.200 butir dibanding 304, Kentang
  40 kg dibanding 12,7 kg, dan Gold Label 10,0 kg dibanding 5,1 kg. Kemungkinan penyebabnya pemakaian di luar resep
  (lalapan, makan karyawan), takaran resep yang kurang tepat, atau stok untuk lebih lama (bagian 6 nomor 4).
- **Augmentasi hanya mengubah 2 dari 8 bahan.** Fresh Milk mendapat tambahan 38,1 kg pada 17 hari (tercatat masuk 42 kg,
  pemakaian menurut resep 68,4 kg; tambahan lebih besar dari selisihnya karena sebagian susu 29 Oktober melewati masa
  simpan 7 hari sebelum terpakai). Ayam Penyet mendapat tambahan 5 pcs pada 2 hari. Enam bahan lainnya tidak berubah.
  Sebelum augmentasi, K1 kehabisan Fresh Milk 17 hari dan biaya kehabisannya Rp 6,6 juta (TC K1 Rp 9,1 juta); angka itu
  tidak masuk akal karena penjualan susu tetap berjalan.

#### Data asli dan data augmentasi

Untuk Bab 3 dan Bab 4, bedakan dengan jelas sumber setiap angka:

| Data | Status | Sumber / cara dibuat |
|---|---|---|
| Transaksi penjualan 1 Juli – 23 November 2026 | **asli** | ekspor Detail Penjualan majoo (`data_awal/penjualan/`, file terakhir `detil_penjualan_2026_11_24.xlsx` berisi 11–23 November) |
| Stok keluar (pemakaian) harian per bahan | turunan | transaksi × resep majoo (`alat/bangun_stok_keluar.py`), tidak diubah |
| Barang masuk 24 Oktober – 19 November | **asli** | laporan "barang masuk hari ini" WhatsApp cafe (`data_awal/catatan_manual/`) |
| Barang masuk 20–23 November | **diisi dari orderan** | orderan malam sebelumnya (`Catatan_WA_20-23nov_2026_dari_orderan.txt`) karena laporan barang masuk tidak ada |
| Barang masuk tambahan K1 (Fresh Milk 38,1 kg / 17 hari, Ayam Penyet 5 pcs / 2 hari) | **augmentasi** | dihitung simulasi: kekurangan stok layak pakai terhadap pemakaian aktual (bagian 4 nomor 8) |
| Taksiran stok awal 27 Oktober | **taksiran** | stok terkecil agar barang masuk tercatat cukup selama stok awal masih layak pakai |

Jumlah tambahan per bahan per hari ada di lembar *Periode Aktual Augmentasi* dan kolom *Barang masuk tambahan
(augmentasi K1)* pada lembar *Harian Periode Aktual* di `simulasi_K1_K2_K3_K4.xlsx`. Di aplikasi, angka yang sama tampil
di halaman Simulasi (kolom *Tambahan (augmentasi)*) dan di rincian per bahan saat K1 dipilih.

**Uji 28 hari K2–K4 pada 10 bahan target, 5 tingkat stok awal (Tabel 4).** K1 tidak ikut karena K1 hanya bisa memutar
ulang barang yang tercatat masuk, jadi tidak bisa dimulai dari stok awal buatan dan tidak ada untuk SKM dan Powder Beans
Wine.

| | K2 (ROP statis + EOQ) | K3 ROP dinamis + order-up-to | K4 ROP dinamis + Q-Learning |
|---|---:|---:|---:|
| Total biaya 28 hari (TC) | Rp 2.086.646 | **Rp 586.973** | Rp 595.301 |
| Fill rate (FR) | 97,9% | 99,3% | **99,7%** |
| Rasio terbuang (WR) | 10,5% | **3,0%** | 5,6% |
| Hari kehabisan (bahan-hari) | 6,8 | 2,6 | **1,0** |

Hasil uji per bahan (Wilcoxon satu arah):

- K4 lebih murah daripada K2 pada 7 dari 10 bahan (p = 0,024, median rasio biaya 0,84).
- K3 dibanding K2 tidak berbeda nyata: lebih murah pada 6 dari 10 bahan (p = 0,16, median rasio 0,96).
- K4 dibanding K3 **tidak berbeda nyata**: K4 lebih murah pada 5 dari 10 bahan (p = 0,54, median rasio 1,00), dan
  total biayanya 1,4% lebih tinggi daripada K3.

Jadi pada 10 bahan ini kedua kebijakan dengan ROP dinamis memangkas sekitar 72% biaya K2, tetapi Q-Learning belum
terbukti lebih murah daripada aturan order-up-to. Selisih K4 terhadap K3 terbesar pada Ayam Penyet (K4 Rp 106.422 lebih
murah). K4 lebih mahal pada Fresh Milk (Rp 104.194 dibanding Rp 44.778) dan Timun (Rp 86.295 dibanding Rp 29.751).
Biaya K2 terkumpul di empat bahan (Timun, Fresh Milk, Ayam Penyet, dan Telur, 93% TC), karena pesanan EOQ yang jarang
dan besar membuat bahan itu bergantian kehabisan dan terbuang.

**Asal biaya dan sisa stok, 10 bahan target 28 hari (rata-rata semua run).** Persen adalah bagian dari TC. Neraca nilai
barang memakai harga beli: stok awal + barang datang = terpakai + terbuang + sisa stok akhir.

| | K2 | K3 | K4 |
|---|---:|---:|---:|
| Biaya simpan | Rp 77.310 (3,7%) | Rp 41.320 (7,0%) | Rp 59.388 (10,0%) |
| Biaya kehabisan | Rp 1.123.737 (53,9%) | Rp 128.678 (21,9%) | Rp 63.994 (10,7%) |
| Biaya terbuang | Rp 807.599 (38,7%) | Rp 248.976 (42,4%) | Rp 320.959 (53,9%) |
| Biaya pesan | Rp 78.000 (3,7%) | Rp 168.000 (28,6%) | Rp 150.960 (25,4%) |
| Jumlah pemesanan | 39,0 | 84,0 | 75,5 |
| Nilai stok awal | Rp 713.365 | Rp 713.365 | Rp 713.365 |
| Nilai barang datang | Rp 15.557.744 | Rp 13.785.664 | Rp 14.629.828 |
| Nilai terpakai | Rp 12.571.814 | Rp 12.607.590 | Rp 12.637.444 |
| Nilai terbuang | Rp 807.599 | Rp 248.976 | Rp 320.959 |
| Nilai sisa stok akhir (malam 23 November) | Rp 2.891.696 | Rp 1.642.465 | Rp 2.384.790 |

Dibanding K3, K4 menekan biaya kehabisan (Rp 63.994 dibanding Rp 128.678) dan lebih jarang memesan, tetapi membuang lebih
banyak (Rp 320.959 dibanding Rp 248.976) dan menyimpan stok lebih banyak, sehingga totalnya hampir sama.
Semua angka biaya juga masih bergantung pada parameter sementara di bagian 6.

Laporan lengkap ada di folder `laporan/`. `evaluasi_xgboost.xlsx` memuat metrik per bahan dan per horizon, serta lembar *Aturan Pemilihan* dan *Pemilihan Bahan*
(statistik 172 bahan, alasan bahan dikeluarkan, dan peringkat bahan target).
`simulasi_K1_K2_K3_K4.xlsx` dibuka dengan lembar *Hasil Biaya K1-K4* (tabel utama di atas), lalu Tabel 4 uji K2–K4,
komponen biaya, per bahan, dan tuning, ditambah lembar rincian:
- *Cara Membaca Rincian*: arti setiap kolom dan rumus komponen biaya.
- *Rincian Biaya*: komponen biaya (Rp dan persen dari TC) dan neraca nilai barang per kebijakan dan kelompok bahan.
- *Rincian Per Bahan*: untuk setiap bahan dan kebijakan, parameter biaya, neraca barang, sisa stok akhir periode, dan
  dasar perhitungan setiap komponen (rata-rata semua run).
- *Harian Uji* dan *Sisa Stok Harian*: catatan harian satu run contoh (stok awal 1 × rata-rata pemakaian, K4 seed
  pertama) dan sisa stok akhir setiap hari, untuk semua bahan.
- *Rincian Periode Aktual* dan *Harian Periode Aktual*: hal yang sama untuk periode barang masuk aktual (K1–K4,
  taksiran stok awal aktual). Lembar *Periode Aktual ...* lainnya memuat ringkasan, perbandingan, dan semua run.

Keduanya juga bisa diunduh dari menu Analisis Model. Di halaman Simulasi, klik nama bahan untuk melihat rincian bahan
itu: asal biaya, neraca barang, grafik sisa stok, dan catatan harian setiap kebijakan untuk stok awal dan seed yang
dipilih.

---

## 6. Data yang masih kurang

Daftar ini diurutkan dari yang paling berpengaruh. Semua angka di bawah berasal dari data bawaan.

1. **Stok fisik awal (stok opname).** Data majoo hanya berisi stok keluar, sehingga posisi stok tidak diketahui. Tanpa
   satu kali stok opname, aplikasi baru menghitung ROP dan belum menghitung jumlah pesan.
2. **Stok keluar sejak 24 November 2026 dan laporan barang masuk setiap hari.** Data majoo sampai 23 November sudah
   dimasukkan. Laporan "barang masuk hari ini" 20–23 November tidak ada, jadi untuk sementara diisi dari orderan malam
   sebelumnya (bagian 5); bila laporan aslinya ada, ganti berkas `Catatan_WA_20-23nov_2026_dari_orderan.txt`. Mulai
   24 November, isi stok keluar setiap hari di menu Stok Keluar Harian, karena rekomendasi membutuhkan
   catatan 7 hari terakhir yang lengkap. Laporan barang masuk WhatsApp juga perlu ditempel setiap hari agar periode
   aktual K1 bertambah.
3. **Masa simpan Fresh Milk dan pembelian susu yang tidak tercatat.** Masa simpan Fresh Milk masih nilai umum 7 hari,
   padahal barang masuk yang tercatat selama 27 Oktober – 23 November hanya 42 kg, sedangkan pemakaian menurut resep 68 kg.
   Untuk sementara kekurangannya dilengkapi dengan augmentasi (38,1 kg, bagian 5). Tanyakan masa simpan susu yang dipakai
   (Greenfields), berapa yang datang dari orderan 18 November, dan apakah ada pembelian susu lain yang tidak ditulis di
   laporan. Bila datanya ada, masukkan ke catatan barang masuk agar bagian augmentasi berkurang.
4. **Pemakaian di luar resep.** Barang masuk Timun, Telur, Gold Label, dan Kentang 3 sampai 8 kali pemakaian menurut
   resep (bagian 5). Tanyakan ke cafe apakah ada pemakaian yang tidak tercatat di majoo, misalnya lalapan, bahan untuk
   makan karyawan, atau telur untuk menu yang resepnya belum memuat telur. Bila pemakaian sebenarnya lebih besar,
   prediksi dan rekomendasi untuk bahan itu ikut terlalu kecil.
5. **Konfirmasi catatan barang masuk untuk bahan target.** Unduh Excel di Catatan Barang Masuk, lalu cek lembar
   *Perlu Dicek* dengan staf cafe. Untuk 10 bahan target yang perlu dipastikan: isi 1 dus dan 1 kotak SKM (sekarang
   SKM tidak ikut K1), "Gold label 3 kotak" (dianggap 3 botol 907 g), "Ayam penyet 5 ekor" (majoo mencatat Pcs
   dengan 1 ekor = 1 pcs, sedangkan catatan 1 November menulis 5 ekor = 20 potong), 1 bag beans (dianggap 1.000 g), dan
   "kentang goreng 1000gr (2bks)" (dibaca 2 × 1.000 g; "kentang 2 bks (2000gr)" dibaca 2.000 g total). Untuk bahan lain: isi kemasan yang masih ditebak (misalnya 1
   bungkus kerupuk, 1 sisir pisang, 1 dus minyak makan yang ditulis "6 bks 13 liter"), dua pesan "barang masuk bar
   kitchen" 9 November yang sama-sama memuat Alpukat 3 kg (keduanya dihitung), dan barang yang belum terdaftar di data
   bahan (gabin, donat, cabe giling, terasi, lemon, beans Ciwidey, kue kering).
6. **Biaya pesan (c_o) dan biaya simpan (c_h).** Nilai Rp 2.000 per pesanan per bahan dan 0,1% harga per hari masih
   sementara. Biaya pesan kini 30–35% TC pada K3 dan K4, jadi nilainya sangat menentukan perbandingan K3 dan K4. Isi di
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
   terbuang K1 berasal dari bahan-bahan ini.
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
10 November 2026 (dari model sebelumnya, belum diperbarui ke data 23 November) untuk 10 bahan target, sedangkan bahan lain memakai stok minimum dari majoo. Bila majoo menerima impor dengan format yang sama, kolom ini bisa dipakai untuk memperbarui
stok minimum di majoo (belum dicoba).

---

## 7. Penyesuaian terhadap proposal (untuk dicatat di Bab 3/4)

1. ε turun secara eksponensial dari 1 ke 0,01 sampai 80% episode, lalu tetap 0,01. Tidak memakai *early stopping*.
   Sebagai gantinya, kurva pembelajaran (biaya per episode) ditampilkan di halaman Simulasi.
2. Batas kapasitas simpan ditambahkan pada pemilihan aksi dan pada ketiga kebijakan. Bila kapasitas belum diketahui,
   kapasitas dan m ditentukan otomatis (bagian 4 nomor 6). Tanpa batas ini, agen cenderung menimbun bahan yang biaya
   simpannya kecil.
3. Saat inferensi, aksi terbaik hanya dipilih di antara aksi yang pernah dicoba pada state itu. State yang tidak pernah
   ditemui memakai aturan K3.
4. Simpangan baku bergerak memakai pembagi w (ddof = 0) seperti notebook, sedangkan Persamaan 6 memakai w − 1.
5. Setiap episode pelatihan terdiri dari 4 minggu acak dari prediksi *out-of-sample*, dengan stok awal acak 0–3 ×
   rata-rata harian. Untuk simulasi, minggu yang dipakai hanya yang sebelum periode uji. Model yang dipakai aplikasi
   dilatih ulang dengan semua minggu.
6. Q pada K2 (EOQ) dibatasi pemakaian selama masa simpan, lalu dibulatkan ke atas ke kemasan.
7. Kekurangan stok dianggap penjualan hilang (*lost sales*), bukan *backorder*.
8. Dataset disaring lebih dulu (bahan kosong dan bahan yang didominasi nilai 0 dikeluarkan), lalu penelitian dibatasi
   pada 10 bahan target: bahan cepat rusak (masa simpan ≤ 30 hari, bukan Air & Minuman) yang paling sering dipakai dan
   paling besar nilai pemakaiannya (bagian 4). Sebelumnya "bahan utama" adalah semua bahan cepat rusak yang dipakai pada
   ≥ 50% hari data.
9. Penomoran kebijakan berbeda dari proposal. Karena cafe kini mencatat barang masuk secara manual, ditambahkan
   pembanding praktik cafe yang sebenarnya: barang yang benar-benar diterima diputar ulang (bagian 4 nomor 8). Agar
   tidak membingungkan, keempat kebijakan dinomori ulang: **K1** = data historis (barang masuk aktual), **K2** = ROP
   statis + EOQ (K1 pada proposal), **K3** = ROP dinamis + order-up-to (K2 pada proposal), **K4** = ROP dinamis +
   Q-Learning (K3 pada proposal). Model yang dilatih sebelum penomoran ini (kode lama K1A/K1/K2/K3) tetap tampil
   dengan nomor baru di aplikasi (ml/penamaan.py), tetapi laporan Excel model lama masih memakai nomor lama.
10. Model global XGBoost dan Q-table hanya dilatih untuk 10 bahan target, bukan semua bahan, sehingga rekomendasi
    aplikasi juga hanya untuk 10 bahan itu.
11. Data historis K1 dilengkapi (augmentasi). Catatan barang masuk WhatsApp tidak mencatat semua pembelian, sehingga
    pemutaran ulang apa adanya membuat K1 kehabisan stok padahal penjualannya benar-benar terjadi. Kekurangan itu kini
    dilengkapi sebagai pembelian tidak tercatat, tepat sebesar kekurangannya, dan taksiran stok awal dibatasi masa simpan
    (bagian 4 nomor 8). Jumlah tambahan dilaporkan terpisah dari data asli (bagian 5, *Data asli dan data augmentasi*).

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

**Pengujian.** `.venv\Scripts\python -m pytest` menjalankan 43 uji. Cakupannya: saringan nilai 0 dan peringkat bahan target, rumus Persamaan 1–3, 17, 21, dan
25–28, lingkungan FIFO, batas kapasitas, jadwal ε, K1 (pemutaran ulang barang masuk, augmentasi kekurangan stok, taksiran stok awal dibatasi masa simpan,
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
