"""Tabel basis data PrediStok.

Satuan semua jumlah stok adalah satuan dasar bahan (satuan pada resep majoo, mis. Gram atau Pcs).
"""
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

TEKS_PANJANG = Text().with_variant(Text(length=2 ** 24), "mysql")
BLOB = LargeBinary().with_variant(LargeBinary(length=2 ** 24), "mysql")


class Pengguna(Base):
    __tablename__ = "pengguna"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    nama: Mapped[str] = mapped_column(String(100))
    hash_sandi: Mapped[str] = mapped_column(String(200))
    peran: Mapped[str] = mapped_column(String(20), default="admin")      # admin / staf
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    sandi_bawaan: Mapped[bool] = mapped_column(Boolean, default=False)
    dibuat: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Bahan(Base):
    __tablename__ = "bahan"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    nama: Mapped[str] = mapped_column(String(150))
    kategori: Mapped[str] = mapped_column(String(60), default="Lainnya")
    satuan: Mapped[str] = mapped_column(String(30), default="Gram")
    monitor: Mapped[bool] = mapped_column(Boolean, default=True)           # Monitor Persediaan (Y/T) majoo
    stok_minimum: Mapped[float] = mapped_column(Float, default=0.0)        # diisi ROP dinamis terbaru
    stok_minimum_diubah: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    kemasan_nama: Mapped[str] = mapped_column(String(30), default="Kemasan")
    kemasan_isi: Mapped[float] = mapped_column(Float, default=1.0)         # k
    harga_satuan: Mapped[float] = mapped_column(Float, default=0.0)        # harga beli per satuan dasar (c_w)
    masa_simpan: Mapped[int] = mapped_column(Integer, default=30)          # tau (hari)
    lead_time: Mapped[int] = mapped_column(Integer, default=1)
    maks_kelipatan: Mapped[int | None] = mapped_column(Integer, nullable=True)   # m dari kapasitas simpan
    biaya_kehabisan: Mapped[float] = mapped_column(Float, default=0.0)     # c_s per satuan
    sumber_harga: Mapped[str] = mapped_column(String(30), default="diisi kafe")
    sumber_kemasan: Mapped[str] = mapped_column(String(30), default="diisi kafe")
    sumber_biaya_kehabisan: Mapped[str] = mapped_column(String(30), default="diisi kafe")
    asumsi: Mapped[str] = mapped_column(String(200), default="")          # kolom yang masih berupa nilai sementara
    catatan: Mapped[str] = mapped_column(Text, default="")
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)
    dibuat: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    diubah: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    satuan_lain: Mapped[list["SatuanBahan"]] = relationship(back_populates="bahan", cascade="all, delete-orphan",
                                                            order_by="SatuanBahan.no")

    @property
    def daftar_asumsi(self):
        return [a for a in (self.asumsi or "").split(",") if a]


class SatuanBahan(Base):
    """Struktur Satuan #1..#5 pada majoo agar impor/ekspor bolak-balik tidak kehilangan data."""
    __tablename__ = "satuan_bahan"
    id: Mapped[int] = mapped_column(primary_key=True)
    bahan_id: Mapped[int] = mapped_column(ForeignKey("bahan.id", ondelete="CASCADE"), index=True)
    no: Mapped[int] = mapped_column(Integer)
    satuan: Mapped[str] = mapped_column(String(30))
    sku: Mapped[str] = mapped_column(String(30))
    konversi: Mapped[float] = mapped_column(Float, default=1.0)
    harga_beli: Mapped[float] = mapped_column(Float, default=0.0)
    dasar: Mapped[bool] = mapped_column(Boolean, default=False)
    bahan: Mapped[Bahan] = relationship(back_populates="satuan_lain")


class PencatatanHarian(Base):
    """Hari yang stok keluarnya sudah dicatat (atau kafe tutup). Dipakai untuk cek kelengkapan 7 hari."""
    __tablename__ = "pencatatan_harian"
    tanggal: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="tercatat")    # tercatat / tutup
    sumber: Mapped[str] = mapped_column(String(50), default="manual")
    diubah: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class StokKeluar(Base):
    __tablename__ = "stok_keluar"
    __table_args__ = (UniqueConstraint("bahan_id", "tanggal"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    bahan_id: Mapped[int] = mapped_column(ForeignKey("bahan.id", ondelete="CASCADE"), index=True)
    tanggal: Mapped[date] = mapped_column(Date, index=True)
    jumlah: Mapped[float] = mapped_column(Float, default=0.0)


class MutasiStok(Base):
    """Stok masuk (kedatangan), stok opname (stok fisik), dan stok terbuang."""
    __tablename__ = "mutasi_stok"
    id: Mapped[int] = mapped_column(primary_key=True)
    bahan_id: Mapped[int] = mapped_column(ForeignKey("bahan.id", ondelete="CASCADE"), index=True)
    tanggal: Mapped[date] = mapped_column(Date, index=True)
    jenis: Mapped[str] = mapped_column(String(20))                         # masuk / opname / terbuang
    jumlah: Mapped[float] = mapped_column(Float)                           # opname: stok fisik hasil hitung
    pesanan_item_id: Mapped[int | None] = mapped_column(ForeignKey("pesanan_item.id", ondelete="SET NULL"),
                                                        nullable=True)
    keterangan: Mapped[str] = mapped_column(String(200), default="")
    dibuat_oleh: Mapped[str] = mapped_column(String(50), default="")
    dibuat: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    bahan: Mapped[Bahan] = relationship()


class CatatanBarang(Base):
    """Baris catatan manual cafe (laporan WhatsApp order dan barang masuk) yang sudah dirapikan.

    Barang masuk dipakai simulasi K1 aktual; tabel ini terpisah dari mutasi stok sehingga tidak mengubah
    Daftar Stok. Jumlah dalam satuan dasar bahan (jumlah_dasar) kosong bila isi kemasannya belum diketahui.
    """
    __tablename__ = "catatan_barang"
    id: Mapped[int] = mapped_column(primary_key=True)
    jenis: Mapped[str] = mapped_column(String(10), index=True)               # masuk / order
    tanggal: Mapped[date] = mapped_column(Date, index=True)
    tanggal_tertulis: Mapped[date | None] = mapped_column(Date, nullable=True)
    bagian: Mapped[str] = mapped_column(String(30), default="")
    teks: Mapped[str] = mapped_column(String(300), default="")
    nama: Mapped[str] = mapped_column(String(150), default="")
    jumlah: Mapped[float | None] = mapped_column(Float, nullable=True)
    satuan: Mapped[str] = mapped_column(String(30), default="")
    isi_satuan: Mapped[str] = mapped_column(String(30), default="")
    bahan_id: Mapped[int | None] = mapped_column(ForeignKey("bahan.id", ondelete="SET NULL"), nullable=True,
                                                 index=True)
    jumlah_dasar: Mapped[float | None] = mapped_column(Float, nullable=True)
    konversi: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="")
    asumsi: Mapped[str] = mapped_column(String(300), default="")
    keterangan: Mapped[str] = mapped_column(String(150), default="")
    sumber: Mapped[str] = mapped_column(String(120), default="")
    dibuat_oleh: Mapped[str] = mapped_column(String(50), default="")
    dibuat: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    bahan: Mapped[Bahan | None] = relationship()


class Pesanan(Base):
    __tablename__ = "pesanan"
    id: Mapped[int] = mapped_column(primary_key=True)
    nomor: Mapped[str] = mapped_column(String(30), unique=True)
    tanggal_pesan: Mapped[date] = mapped_column(Date, index=True)
    tanggal_perkiraan: Mapped[date] = mapped_column(Date)
    tanggal_terima: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="dipesan")     # dipesan / diterima / dibatalkan
    pemasok: Mapped[str] = mapped_column(String(100), default="")
    catatan: Mapped[str] = mapped_column(Text, default="")
    dibuat_oleh: Mapped[str] = mapped_column(String(50), default="")
    dibuat: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    items: Mapped[list["PesananItem"]] = relationship(back_populates="pesanan", cascade="all, delete-orphan")

    def terlambat(self, hari_ini: date) -> bool:
        return self.status == "dipesan" and hari_ini > self.tanggal_perkiraan

    @property
    def nilai(self) -> float:
        return sum((it.jumlah_diterima if it.jumlah_diterima is not None else it.jumlah) * (it.harga_satuan or 0)
                   for it in self.items)


class PesananItem(Base):
    __tablename__ = "pesanan_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    pesanan_id: Mapped[int] = mapped_column(ForeignKey("pesanan.id", ondelete="CASCADE"), index=True)
    bahan_id: Mapped[int] = mapped_column(ForeignKey("bahan.id", ondelete="CASCADE"), index=True)
    jumlah: Mapped[float] = mapped_column(Float)
    jumlah_diterima: Mapped[float | None] = mapped_column(Float, nullable=True)
    harga_satuan: Mapped[float] = mapped_column(Float, default=0.0)
    rekomendasi_id: Mapped[int | None] = mapped_column(ForeignKey("rekomendasi.id", ondelete="SET NULL"),
                                                       nullable=True)
    pesanan: Mapped[Pesanan] = relationship(back_populates="items")
    bahan: Mapped[Bahan] = relationship()


class ModelRun(Base):
    """Satu kali pelatihan XGBoost + Q-Learning beserta evaluasinya."""
    __tablename__ = "model_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    mulai: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    selesai: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="berjalan")    # berjalan / selesai / gagal
    jenis: Mapped[str] = mapped_column(String(20), default="lengkap")
    data_mulai: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_sampai: Mapped[date | None] = mapped_column(Date, nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=False)
    folder: Mapped[str] = mapped_column(String(300), default="")
    log: Mapped[str] = mapped_column(TEKS_PANJANG, default="")
    ringkasan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dibuat_oleh: Mapped[str] = mapped_column(String(50), default="")


class QTabel(Base):
    """Q-table satu bahan (Persamaan 17) beserta batas interval state dan ruang aksinya."""
    __tablename__ = "q_tabel"
    __table_args__ = (UniqueConstraint("model_run_id", "sku"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    model_run_id: Mapped[int] = mapped_column(ForeignKey("model_run.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(30))
    k: Mapped[float] = mapped_column(Float)
    m: Mapped[int] = mapped_column(Integer)
    kap: Mapped[float | None] = mapped_column(Float, nullable=True)      # kapasitas simpan (satuan dasar)
    kap_manual: Mapped[bool] = mapped_column(Boolean, default=False)      # diisi di data master atau otomatis
    d_bar: Mapped[float] = mapped_column(Float, default=0.0)
    sigma_e: Mapped[float] = mapped_column(Float, default=0.0)
    edges: Mapped[dict] = mapped_column(JSON)
    q: Mapped[bytes] = mapped_column(BLOB)          # float32 [n_state, m + 1]
    n: Mapped[bytes] = mapped_column(BLOB)          # int32 jumlah kunjungan [n_state, m + 1]


class Rekomendasi(Base):
    """Riwayat rekomendasi harian (Gambar 3) untuk evaluasi dan pelatihan ulang."""
    __tablename__ = "rekomendasi"
    __table_args__ = (UniqueConstraint("tanggal", "bahan_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tanggal: Mapped[date] = mapped_column(Date, index=True)               # keputusan akhir hari t
    bahan_id: Mapped[int] = mapped_column(ForeignKey("bahan.id", ondelete="CASCADE"), index=True)
    model_run_id: Mapped[int | None] = mapped_column(ForeignKey("model_run.id", ondelete="SET NULL"), nullable=True)
    stok: Mapped[float] = mapped_column(Float)
    dalam_perjalanan: Mapped[float] = mapped_column(Float, default=0.0)
    posisi: Mapped[float] = mapped_column(Float)                           # IP (Persamaan 24)
    prediksi: Mapped[list] = mapped_column(JSON)                           # y_hat t+1 .. t+7
    rop: Mapped[float] = mapped_column(Float)                              # Persamaan 21
    target: Mapped[float] = mapped_column(Float)                           # OUT, Persamaan 25
    sigma_e: Mapped[float] = mapped_column(Float, default=0.0)
    hampir_kedaluwarsa: Mapped[float] = mapped_column(Float, default=0.0)  # E_t
    kedaluwarsa: Mapped[float] = mapped_column(Float, default=0.0)         # stok yang sudah lewat masa simpan
    kritis: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sumber: Mapped[str] = mapped_column(String(30))                        # q_learning / cadangan_k2
    jumlah: Mapped[float] = mapped_column(Float)
    jumlah_k2: Mapped[float] = mapped_column(Float, default=0.0)          # pembanding order-up-to
    dibuat: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    bahan: Mapped[Bahan] = relationship()


class Pengaturan(Base):
    __tablename__ = "pengaturan"
    kunci: Mapped[str] = mapped_column(String(50), primary_key=True)
    nilai: Mapped[str] = mapped_column(Text)
