"""Stok keluar harian per bahan baku = transaksi penjualan majoo x resep produk (pra-pemrosesan data).

    python alat/bangun_stok_keluar.py --sampai 2026-11-10 \
        data_awal/penjualan/Uptodate_25_oktober.xlsx data_awal/penjualan/detil_penjualan_2026_11_03.xlsx \
        data_awal/penjualan/detil_penjualan_2026_11_11.xlsx

File transaksi = ekspor Detail Penjualan majoo (header tabel boleh di bawah judul laporan), boleh lebih dari satu.
Bila satu tanggal ada di beberapa file, transaksi tanggal itu diambil dari file yang disebut paling akhir.
Kolom Produk dipecah per koma (menu yang muncul dua kali = 2 porsi), dicocokkan dengan resep, lalu dikalikan
kuantitas bahan per porsi. Hari tanpa pemakaian diisi 0.

Hasil bawaan menggantikan data_awal/Stok_Keluar_Harian_Bahan_Baku.xlsx. File itu bisa diimpor di menu Stok Keluar
Harian (aplikasi yang sudah berjalan), lalu jalankan Pelatihan Ulang.
"""
import argparse
import re
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("transaksi", nargs="+", help="file ekspor Detail Penjualan majoo (urut dari yang paling lama)")
ap.add_argument("--resep", default=str(BASE / "data_awal" / "Ekspor_Resep_Produk_LF_13okt.xlsx"))
ap.add_argument("--mulai", default="2026-07-01", help="tanggal pertama (bawaan 2026-07-01)")
ap.add_argument("--sampai", required=True, help="tanggal terakhir yang dipakai, mis. 2026-11-02")
ap.add_argument("-o", "--keluaran", default=str(BASE / "data_awal" / "Stok_Keluar_Harian_Bahan_Baku.xlsx"))
A = ap.parse_args()
MULAI, SAMPAI = pd.Timestamp(A.mulai), pd.Timestamp(A.sampai)
RESEP, OUT = A.resep, A.keluaran

# ---------- Resep ----------
r = pd.read_excel(RESEP, sheet_name='Ekspor Resep', header=4)
bahan = pd.read_excel(RESEP, sheet_name='Daftar Bahan', header=3)
master = pd.read_excel(RESEP, sheet_name='Daftar Master Resep', header=3)

def num(x):
    if pd.isna(x):
        return None
    try:
        return float(str(x).replace(',', '.'))
    except ValueError:
        return None

r['Nama Produk*'] = r['Nama Produk*'].str.strip()
# "Teh Madu (P)" tercatat dua kali; blok kedua (dengan es batu) adalah versi Dingin
r.loc[[860, 861, 862], 'Nama Produk*'] = 'Teh Madu (D)'

sku_by_name = {n.lower(): s for s, n in zip(bahan['Kode SKU'], bahan['Nama Bahan'])}
sku_by_name.update({'teh lipton': 'BB26', 'the celup sosro': 'BB167', 'teh bubuk poci vanilla': 'BB168',
                    'telur ayam kampung': 'BB179', 'madu akasia (bar kitchen)': 'BB166',
                    'mineral botol 600 ml': 'BB175'})
info = {s: (n, u) for s, n, u in zip(bahan['Kode SKU'], bahan['Nama Bahan'], bahan['Satuan'])}
extra = {'es batu': ('ES-BATU', 'Es Batu', 'Gram'), 'air': ('AIR', 'Air', 'Gram'),
         'teh botol sosro': ('TEH-BOTOL', 'Teh Botol Sosro', 'Botol'),
         'fruitea botol': ('FRUITEA', 'Fruitea Botol', 'Botol')}

bom = []  # produk, sku, nama, satuan, qty, catatan
for _, x in r.iterrows():
    prod = x['Nama Produk*']
    if pd.notna(x['Kode Master Resep*']) and str(x['Kode Master Resep*']).strip():
        for _, m in master[master['Kode Master Resep*'] == x['Kode Master Resep*']].iterrows():
            n, u = info[m['SKU Bahan*']]
            bom.append([prod, m['SKU Bahan*'], n, u, num(m['Kuantitas*']), f"dari master resep {x['Kode Master Resep*']}"])
        continue
    q = num(x['Kuantitas*'])
    note = ''
    if q is None:
        q, note = 1.0, 'kuantitas kosong di resep, diasumsikan 1'
    sku = x['SKU Bahan*']
    nm = str(x['Nama Bahan*']).strip()
    if pd.isna(sku):
        if nm.lower() in sku_by_name:
            sku = sku_by_name[nm.lower()]
            note = (note + '; ' if note else '') + 'SKU kosong, dicocokkan lewat nama'
        else:
            sku, nm2, u = extra[nm.lower()]
            bom.append([prod, sku, nm2, u, q, (note + '; ' if note else '') + 'bahan tidak ada di Daftar Bahan'])
            continue
    n, u = info[sku]
    bom.append([prod, sku, n, u, q, note])
bom = pd.DataFrame(bom, columns=['Produk', 'SKU Bahan', 'Nama Bahan', 'Satuan', 'Qty per Porsi', 'Catatan'])
kat = r.groupby('Nama Produk*')['Nama Kategori'].first().to_dict()
kat['Teh Madu (D)'] = 'PENJUALAN TERAS KOTA'
recipes = {p.upper(): p for p in bom['Produk'].unique() if p != 'Mineral water'}  # 'MINERAL WATER' = 330ml kafe

# ---------- Pemetaan nama transaksi -> resep ----------
ALIAS = {
    'TEA': 'TEA hot/cold', 'NASI GORENG BLACK PAPPER': 'NASI GORENG BLACKPAPER',
    'KWITIAU SEAFOOD': 'KWETIAU SEAFOOD', 'KWETIAU SEAFOOD LAFABRICA': 'KWETIAU SEAFOOD',
    'MOCHACINO': 'MOCHACINO RISTRETTO', 'CHURROS': 'CHURROS MINI', 'PEYEK': 'PEYEK (Pouch Kecil)',
    'MATA SAPI': 'TELUR MATA SAPI', 'TEH BOTOL SOSRO': 'The Botol sosro', 'FRUIT TEA': 'Fruitea',
    'CHEESE CAKE': 'CHEESE CAKE ORIGINAL LAFABRICA', 'KEBAB BEEF': 'KEBAB BEEF LAFABRICA',
    'BASRENG': 'BASRENG LAFABRICA', 'NUTELLA TOAST': 'FRENCH TOAST NUTELLA',
    'INDOMIE GORENG/KUAH': 'INDOMIE GORENG LAFABRICA', 'COOKIES LAVANYA BITES': 'COOKIES LAVANYA LAFABRICA',
    'SANGER': 'SANGER ESPRESSO',
    'BUTTER CROISSANT': 'Butter Croissant 64gr',   # paket baru mulai 26 Okt: "Lafa Coffee + Butter Croissant"
}
COMBO_DRINK = {'TEA/COFFEE': 'TEA hot/cold', 'TEA': 'TEA hot/cold', 'COFFEE': 'AMERICANO'}

def one(name):
    """Nama satu menu -> nama resep, atau None."""
    u = re.sub(r'\s+', ' ', name.upper()).strip()
    u2 = re.sub(r' {2,}', ' ', u)
    for cand in (u, u2):
        if cand in recipes:
            return recipes[cand]
        if cand in ALIAS:
            return ALIAS[cand]
        if cand + ' LAFABRICA' in recipes:
            return recipes[cand + ' LAFABRICA']
    for k, v in recipes.items():
        if re.sub(r'\s+', ' ', k) == u2 or re.sub(r'\s+', ' ', k) == u2 + ' LAFABRICA':
            return v
    return None

def resolve(raw):
    """Item transaksi -> (list resep, sumber, keterangan)."""
    name = raw.strip()
    src = 'Lafabrica'
    if re.search(r'teras kota', name, re.I):
        src = 'Teras Kota'
        name = re.sub(r'(?i)^teras kota\s+|\s+teras kota$', '', name).strip()
    p = one(name)
    if p == 'MINERAL WATER' and src == 'Teras Kota':
        p = 'Mineral water'  # botol 600ml Teras Kota
    if p:
        if kat.get(p) == 'PENJUALAN TERAS KOTA':
            src = 'Teras Kota'
        return [p], src, '' if name.upper() == p.upper() else f'disamakan dengan "{p}"'
    m = re.match(r'(?i)^(bundling\s+)?(.+?)\s*\+\s*(.+)$', name)
    if m and '(' not in name and not name.upper().startswith('TOMYAM'):
        main, drink = m.group(2), m.group(3).strip().upper()
        parts, miss = [], []
        pm = one(main)
        (parts.append(pm) if pm else miss.append(main))
        pd_ = COMBO_DRINK.get(drink) or one(drink)
        (parts.append(pd_) if pd_ else miss.append(drink))
        ket = 'paket dipecah: ' + ' + '.join(parts)
        if miss:
            ket += ' | tanpa resep: ' + ', '.join(miss)
        return parts, src, ket
    return [], src, 'tidak ada resep'

# ---------- Transaksi ----------
def baca_transaksi(path):
    """Ekspor Detail Penjualan majoo. Header tabel = baris yang berisi 'No Transaksi'."""
    raw = pd.read_excel(path, engine='calamine', header=None)
    i = next(k for k, v in enumerate(raw[0]) if str(v).strip() == 'No Transaksi')
    d = raw.iloc[i + 1:].copy()
    d.columns = [str(c).strip() for c in raw.iloc[i]]
    d = d[d['No Transaksi'].notna() & d['Waktu Order'].notna()]
    for c in ('Sisa Tagihan (Rp.)', 'Total Penjualan (Rp)'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d['Waktu'] = pd.to_datetime(d['Waktu Order'].astype(str), format='%d-%m-%Y %H:%M:%S')
    d['Tanggal'] = d['Waktu'].dt.normalize()
    return d.reset_index(drop=True)


files = [(Path(p).name, baca_transaksi(p)) for p in A.transaksi]
sumber_tgl = {}                                   # tanggal -> file terakhir yang memuatnya
for nama, d in files:
    for tg in d['Tanggal'].unique():
        sumber_tgl[pd.Timestamp(tg)] = nama
info_file, tumpang = [], []
for k, (nama, d) in enumerate(files):
    dipakai = sorted(tg for tg, f in sumber_tgl.items() if f == nama and MULAI <= tg <= SAMPAI)
    info_file.append(f"{nama} (isi {d['Tanggal'].min():%d/%m/%Y} - {d['Tanggal'].max():%d/%m/%Y}; dipakai "
                     + (f"{dipakai[0]:%d/%m/%Y} - {dipakai[-1]:%d/%m/%Y})" if dipakai else "tidak ada tanggal)"))
    for nama2, d2 in files[k + 1:]:
        sama_tgl = sorted(set(d['Tanggal']) & set(d2['Tanggal']))
        if not sama_tgl:
            continue
        x = d[d['Tanggal'].isin(sama_tgl)].groupby('No Transaksi')['Produk'].agg(lambda v: sorted(map(str, v)))
        y = d2[d2['Tanggal'].isin(sama_tgl)].groupby('No Transaksi')['Produk'].agg(lambda v: sorted(map(str, v)))
        beda = sorted(set(x.index) ^ set(y.index)) + [n for n in set(x.index) & set(y.index) if x[n] != y[n]]
        # Hari terakhir file lama biasanya belum selesai saat diekspor: transaksi yang bertambah atau berubah pada
        # hari itu wajar. Perbedaan pada tanggal lain yang perlu dicek.
        tgl_trx = {**d.drop_duplicates('No Transaksi').set_index('No Transaksi')['Tanggal'].to_dict(),
                   **d2.drop_duplicates('No Transaksi').set_index('No Transaksi')['Tanggal'].to_dict()}
        akhir_lama = d['Tanggal'].max()
        beda_akhir = [n for n in beda if tgl_trx[n] == akhir_lama]
        beda_lain = [n for n in beda if tgl_trx[n] != akhir_lama]
        if not beda:
            ket = "nomor transaksi dan menu sama"
        else:
            bag = []
            if beda_akhir:
                bag.append(f"{akhir_lama:%d/%m} belum lengkap di {nama} (diekspor pukul {d['Waktu'].max():%H:%M}), "
                           f"{len(beda_akhir)} transaksi hari itu bertambah atau berubah")
            bag.append(f"PERLU DICEK, {len(beda_lain)} transaksi berbeda pada tanggal lain" if beda_lain
                       else "tanggal lain sama")
            ket = "; ".join(bag)
        tumpang.append(f"{sama_tgl[0]:%d/%m} - {sama_tgl[-1]:%d/%m} ada di {nama} dan {nama2} ({len(y)} transaksi): "
                       + ket + f"; dipakai {nama2}")
semua = pd.concat([d.assign(_file=nama) for nama, d in files], ignore_index=True)
semua = semua[[sumber_tgl[pd.Timestamp(tg)] == f for tg, f in zip(semua['Tanggal'], semua['_file'])]]
n_sebelum = int((semua['Tanggal'] < MULAI).sum())
n_sesudah = int((semua['Tanggal'] > SAMPAI).sum())
t = semua[(semua['Tanggal'] >= MULAI) & (semua['Tanggal'] <= SAMPAI)]
n_kosong = t['Produk'].isna().sum()
t = t[t['Produk'].notna()]
t = t.drop_duplicates(subset=['No Transaksi', 'Waktu Order', 'Produk', 'Total Penjualan (Rp)'])
n_ganda = int(t['No Transaksi'].duplicated().sum())
hari_trx = set(t['Tanggal'])
bolong = [tg for tg in pd.date_range(MULAI, SAMPAI) if tg not in hari_trx]

rows = []
for _, x in t.iterrows():
    s = x['Produk'].replace('Jus Sawi, Nanas, Jeruk', 'Jus Sawi§ Nanas§ Jeruk')
    for it in s.split(','):
        it = it.replace('§', ',').strip()
        if it:
            rows.append((x['Tanggal'], x['No Transaksi'], it))
items = pd.DataFrame(rows, columns=['Tanggal', 'No Transaksi', 'Item'])

cache = {n: resolve(n) for n in items['Item'].unique()}
mapping = pd.DataFrame([(n, ', '.join(v[0]) or '-', v[1], v[2]) for n, v in cache.items()],
                       columns=['Nama di Transaksi', 'Resep Dipakai', 'Sumber', 'Keterangan'])
cnt = items['Item'].value_counts()
mapping['Jumlah Terjual'] = mapping['Nama di Transaksi'].map(cnt)
mapping['Status'] = mapping['Resep Dipakai'].map(lambda v: 'Tidak cocok' if v == '-' else 'Cocok')
mapping.loc[mapping['Keterangan'].str.contains('tanpa resep'), 'Status'] = 'Sebagian'
mapping = mapping.sort_values(['Status', 'Jumlah Terjual'], ascending=[False, False])

sold = []
for _, x in items.iterrows():
    prods, src, _ = cache[x['Item']]
    for p in prods:
        sold.append((x['Tanggal'], p, src))
sold = pd.DataFrame(sold, columns=['Tanggal', 'Produk', 'Sumber'])
penj = sold.groupby(['Tanggal', 'Produk', 'Sumber']).size().reset_index(name='Qty Terjual')

use = penj.merge(bom, on='Produk')
use['Jumlah Keluar'] = use['Qty Terjual'] * use['Qty per Porsi']
dates = pd.date_range(MULAI, SAMPAI)
long_src = use.groupby(['Tanggal', 'SKU Bahan', 'Nama Bahan', 'Satuan', 'Sumber'])['Jumlah Keluar'].sum().reset_index()
total = use.groupby(['Tanggal', 'SKU Bahan', 'Nama Bahan', 'Satuan'])['Jumlah Keluar'].sum()

# long lengkap: setiap bahan x setiap hari (hari tanpa pemakaian = 0)
ing = bom[['SKU Bahan', 'Nama Bahan', 'Satuan']].drop_duplicates('SKU Bahan')
grid = pd.MultiIndex.from_product([dates, ing['SKU Bahan']], names=['Tanggal', 'SKU Bahan']).to_frame(index=False)
grid = grid.merge(ing, on='SKU Bahan')
tl = total.reset_index()
tk = long_src[long_src.Sumber == 'Teras Kota'].groupby(['Tanggal', 'SKU Bahan'])['Jumlah Keluar'].sum().rename('Dari Teras Kota')
long = grid.merge(tl, on=['Tanggal', 'SKU Bahan', 'Nama Bahan', 'Satuan'], how='left').merge(
    tk.reset_index(), on=['Tanggal', 'SKU Bahan'], how='left').fillna({'Jumlah Keluar': 0, 'Dari Teras Kota': 0})
hari = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']
long['Hari'] = long['Tanggal'].dt.dayofweek.map(lambda d: hari[d])
long = long[['Tanggal', 'Hari', 'SKU Bahan', 'Nama Bahan', 'Satuan', 'Jumlah Keluar', 'Dari Teras Kota']]
long = long.sort_values(['Tanggal', 'SKU Bahan']).reset_index(drop=True)

wide = long.assign(Kolom=long['Nama Bahan'] + ' (' + long['Satuan'] + ')').pivot_table(
    index='Tanggal', columns='Kolom', values='Jumlah Keluar', aggfunc='sum').reindex(dates).fillna(0)
order = long.groupby(long['Nama Bahan'] + ' (' + long['Satuan'] + ')')['Jumlah Keluar'].sum().sort_values(ascending=False).index
wide = wide[order]
wide.insert(0, 'Hari', [hari[d.dayofweek] for d in wide.index])
wide.index.name = 'Tanggal'

rekap = long.groupby(['SKU Bahan', 'Nama Bahan', 'Satuan']).agg(
    Total=('Jumlah Keluar', 'sum'), Rata_rata_per_Hari=('Jumlah Keluar', 'mean'),
    Hari_Ada_Pemakaian=('Jumlah Keluar', lambda s: int((s > 0).sum())), Maks_Harian=('Jumlah Keluar', 'max'),
    Dari_Teras_Kota=('Dari Teras Kota', 'sum')).reset_index().sort_values('Total', ascending=False)
rekap.columns = ['SKU Bahan', 'Nama Bahan', 'Satuan', 'Total Keluar', 'Rata-rata per Hari',
                 'Hari Ada Pemakaian', 'Maks Harian', 'Dari Teras Kota']

penj_out = penj.pivot_table(index=['Tanggal', 'Produk'], values='Qty Terjual', aggfunc='sum').reset_index()

n_items = len(items)
n_cocok = items['Item'].map(lambda i: bool(cache[i][0])).sum()
unmatched = mapping[mapping['Status'] != 'Cocok']
stats = dict(trx=t['No Transaksi'].nunique(), rows=len(t), items=n_items, cocok=int(n_cocok),
             tidak=int(n_items - n_cocok), hari=len(dates), bahan=len(ing), juni=n_sebelum, kosong=int(n_kosong),
             start=dates[0].date(), end=dates[-1].date())

catatan = [
    ['Sumber transaksi', '; '.join(info_file) + '. Kolom Produk dipecah per koma; menu yang muncul dua kali = 2 porsi'],
    *[['Tanggal di dua file', x] for x in tumpang],
    ['Sumber resep', f"{Path(RESEP).name} (isinya identik dengan Resep.xlsx)"],
    ['Periode', f"{stats['start']} s.d. {stats['end']} ({stats['hari']} hari, "
                + ('tidak ada tanggal yang bolong)' if not bolong else
                   'tanggal tanpa transaksi: ' + ', '.join(f'{d:%d/%m}' for d in bolong) + ')')],
    ['Tanggal yang dipakai', 'Tanggal dari kolom Waktu Order'],
    ['Transaksi', f"{stats['rows']} baris transaksi, {stats['items']} item terjual"],
    ['Item tercocok resep', f"{stats['cocok']} item ({stats['cocok']/stats['items']:.1%}); {stats['tidak']} item tanpa resep, lihat sheet Tidak Cocok"],
    ['Dibuang', f"{n_sebelum} transaksi sebelum {MULAI:%d/%m/%Y} (sebelum pencatatan mulai), {n_sesudah} transaksi sesudah "
                f"{SAMPAI:%d/%m/%Y} (hari belum selesai saat diekspor), dan {stats['kosong']} transaksi dengan Produk kosong"],
    ['No Transaksi ganda', f'{n_ganda} nomor transaksi muncul dua kali tetapi isinya berbeda (split bill), jadi keduanya dipakai'],
    ['Belum dibayar', 'Transaksi dengan sisa tagihan tetap dihitung karena pesanannya sudah dibuat'],
    ['Teras Kota', 'Item berlabel "Teras Kota" dan menu kategori PENJUALAN TERAS KOTA ikut dihitung (nilai Rp 0 di kasir). Porsinya dipisah di kolom "Dari Teras Kota". 7 s.d. 12 Okt tiap hari hanya ada 1 transaksi berisi 53-91 menu masing-masing 1 porsi, kemungkinan rekap, perlu dicek'],
    ['Master resep', 'LONG BLACK = master LC1, CAFE LATTE = master LC3, dipecah ke bahan dasarnya'],
    ['Angka desimal', 'Kuantitas seperti "0,10" dan "2,50" dibaca sebagai 0.1 dan 2.5'],
    ['Teh Madu (D)', 'Di file resep tertulis dua kali sebagai "Teh Madu (P)"; blok kedua (dengan es batu) dianggap Teh Madu (D)'],
    ['PEYEK (Pouch Besar)', 'Kuantitas kosong di resep, diasumsikan 1 Peyek Snack; transaksi "PEYEK" dianggap Pouch Kecil'],
    ['Paket "+ TEA/COFFEE"', 'Dipecah menjadi menu utama + TEA hot/cold; "+ COFFEE" dianggap AMERICANO'],
    ['Paket + Butter Croissant', 'Paket baru mulai 26 Okt ("Lafa Coffee + Butter Croissant", "Sanger Espresso + Butter Croissant") dipecah; croissant-nya = resep Butter Croissant 64gr'],
    ['Nama berbeda', 'Nama yang beda tipis disamakan (mis. "INDOMIE GORENG" = "INDOMIE GORENG LAFABRICA", "TEA" = "TEA hot/cold"). Daftar lengkap di sheet Pemetaan Nama'],
    ['PERLU DICEK: Jasmine Tea', 'Resep Americano varian (Squash, Lemon, Orange, Peach, Berry, Ice Mint, Lafa berry cano) mencatat Jasmine Tea 40-60 "Kantung" per porsi, kemungkinan maksudnya gram/ml seduhan. Angka dipakai apa adanya'],
    ['PERLU DICEK: Alpukat', 'AVOCADO SMOOTHIE mencatat Alpukat 1 Gram per porsi (Jus Alpukat 180 Gram), kemungkinan maksudnya 1 buah. Angka dipakai apa adanya'],
    ['Hari tanpa pemakaian', 'Diisi 0 sesuai rancangan pra-pemrosesan di proposal'],
    ['Stok opname', 'Tidak dipakai; stok keluar murni dari penjualan x resep'],
]


with pd.ExcelWriter(OUT, engine='openpyxl') as w:
    pd.DataFrame(catatan, columns=['Hal', 'Keterangan']).to_excel(w, sheet_name='Catatan', index=False)
    wide.reset_index().to_excel(w, sheet_name='Stok Keluar Harian', index=False)
    long.to_excel(w, sheet_name='Stok Keluar (Long)', index=False)
    rekap.to_excel(w, sheet_name='Rekap Bahan', index=False)
    penj_out.to_excel(w, sheet_name='Penjualan Menu Harian', index=False)
    mapping.to_excel(w, sheet_name='Pemetaan Nama', index=False)
    unmatched.to_excel(w, sheet_name='Tidak Cocok', index=False)
    bom.to_excel(w, sheet_name='Resep Dipakai', index=False)

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
wb = load_workbook(OUT)
for ws in wb.worksheets:
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF'); c.fill = PatternFill('solid', fgColor='4F6D7A')
        c.alignment = Alignment(wrap_text=True, vertical='center')
    for col in ws.columns:
        L = max(len(str(c.value)) if c.value is not None else 0 for c in list(col)[:300])
        ws.column_dimensions[col[0].column_letter].width = min(max(10, L + 2), 60)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if hasattr(c.value, 'year'):
                c.number_format = 'DD-MM-YYYY'
            elif isinstance(c.value, float):
                c.number_format = '#,##0.##'
    ws.freeze_panes = 'C2' if ws.title == 'Stok Keluar Harian' else 'A2'
    ws.auto_filter.ref = ws.dimensions
ws = wb['Stok Keluar Harian']
ws.row_dimensions[1].height = 45
for col in list(ws.columns)[2:]:
    ws.column_dimensions[col[0].column_letter].width = 14
wb['Catatan'].column_dimensions['B'].width = 120
for row in wb['Catatan'].iter_rows(min_row=2):
    row[1].alignment = Alignment(wrap_text=True, vertical='top')
    if str(row[0].value).startswith('PERLU'):
        row[0].font = Font(bold=True, color='C00000')
wb.save(OUT)
print(f"{stats['start']} s.d. {stats['end']}: {stats['hari']} hari, {stats['bahan']} bahan, {stats['rows']} transaksi, "
      f"{stats['cocok']}/{stats['items']} item tercocok resep")
for x in tumpang:
    print(' ', x)
print(f'Tersimpan: {OUT}')
