/* PrediStok: interaksi kecil tanpa pustaka tambahan (Chart.js hanya untuk grafik). */
(function () {
  "use strict";
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const simpan = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* abaikan */ } };
  const muat = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } };

  // dropdown
  document.addEventListener("click", (ev) => {
    const pemicu = ev.target.closest(".tarik > .pemicu");
    $$(".tarik.buka").forEach((t) => { if (!pemicu || t !== pemicu.parentElement) t.classList.remove("buka"); });
    if (pemicu) { pemicu.parentElement.classList.toggle("buka"); ev.preventDefault(); }
    if (!ev.target.closest(".tarik")) $$(".tarik.buka").forEach((t) => t.classList.remove("buka"));
  });
  $$(".tarik .daftar label").forEach((l) => l.addEventListener("click", (e) => e.stopPropagation()));

  // grup sidebar
  $$(".menu .grup > button").forEach((b) => {
    const g = b.parentElement, k = "menu:" + (g.dataset.grup || b.textContent.trim());
    const st = muat(k, null);
    if (st !== null && !g.classList.contains("induk-aktif")) g.classList.toggle("buka", st);
    b.addEventListener("click", () => { g.classList.toggle("buka"); simpan(k, g.classList.contains("buka")); });
  });
  const tm = $(".tombol-menu");
  if (tm) tm.addEventListener("click", () => document.body.classList.toggle("sisi-buka"));

  // tutup pesan kilat
  $$(".kilat .tutup").forEach((b) => b.addEventListener("click", () => b.parentElement.remove()));

  // konfirmasi
  document.addEventListener("submit", (ev) => {
    const f = ev.target;
    const pesan = (ev.submitter && ev.submitter.dataset.konfirmasi) || f.dataset.konfirmasi;
    if (pesan && !window.confirm(pesan)) ev.preventDefault();
    const tombol = f.querySelector("button[type=submit][data-memproses]");
    if (tombol && !ev.defaultPrevented) { tombol.disabled = true; tombol.textContent = tombol.dataset.memproses; }
  });

  // pilih otomatis
  $$("select[data-otomatis], input[data-otomatis]").forEach((s) => s.addEventListener("change", () => s.form.submit()));

  // kolom opsional tabel (Sertakan Kolom)
  $$("[data-kolom-tabel]").forEach((wadah) => {
    const id = wadah.dataset.kolomTabel, tabel = document.getElementById(id);
    if (!tabel) return;
    const kunci = "kolom:" + id;
    const bawaan = $$("input[type=checkbox]", wadah).filter((c) => c.defaultChecked).map((c) => c.value);
    let aktif = muat(kunci, bawaan);
    const terap = () => {
      $$("input[type=checkbox]", wadah).forEach((c) => { c.checked = aktif.includes(c.value); });
      $$("[data-kolom]", tabel).forEach((el) => el.classList.toggle("disembunyikan", !aktif.includes(el.dataset.kolom)));
    };
    $$("input[type=checkbox]", wadah).forEach((c) => c.addEventListener("change", () => {
      aktif = $$("input[type=checkbox]", wadah).filter((x) => x.checked).map((x) => x.value);
      simpan(kunci, aktif); terap();
    }));
    terap();
  });

  // pilih semua baris
  $$("input[data-pilih-semua]").forEach((semua) => {
    const f = semua.form || semua.closest("form") || document;
    const kotak = () => $$("input[name=pilih]", f).filter((c) => !c.disabled);
    const bar = $("[data-aksi-terpilih]", f.nodeType ? f : document);
    const segar = () => {
      const n = kotak().filter((c) => c.checked).length;
      if (bar) { bar.hidden = n === 0; const j = $("[data-jumlah-terpilih]", bar); if (j) j.textContent = n; }
      semua.checked = n > 0 && n === kotak().length;
      semua.indeterminate = n > 0 && n < kotak().length;
    };
    semua.addEventListener("change", () => { kotak().forEach((c) => { c.checked = semua.checked; }); segar(); });
    kotak().forEach((c) => c.addEventListener("change", segar));
    segar();
  });

  // modal
  document.addEventListener("click", (ev) => {
    const buka = ev.target.closest("[data-buka-modal]");
    if (buka) { const m = document.getElementById(buka.dataset.bukaModal); if (m) m.classList.add("buka"); ev.preventDefault(); }
    if (ev.target.closest(".tutup-modal") || ev.target.classList.contains("modal-latar")) {
      const m = ev.target.closest(".modal-latar"); if (m) m.classList.remove("buka");
    }
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") $$(".modal-latar.buka").forEach((m) => m.classList.remove("buka")); });

  // jumlah kemasan langsung
  const fmt = (x) => (Math.round(x * 100) / 100).toLocaleString("id-ID");
  const segarKemasan = (inp) => {
    const isi = parseFloat(inp.dataset.isiKemasan || "0"), out = document.getElementById(inp.dataset.keluaran);
    const v = parseFloat(String(inp.value).replace(/\./g, "").replace(",", "."));
    if (out) out.textContent = isi > 0 && !isNaN(v) ? "= " + fmt(v / isi) + " " + (inp.dataset.namaKemasan || "kemasan") : "";
  };
  document.addEventListener("input", (ev) => { if (ev.target.dataset && ev.target.dataset.isiKemasan) segarKemasan(ev.target); });
  $$("[data-isi-kemasan]").forEach(segarKemasan);

  // pilih bahan pada formulir pesanan: isi data kemasan
  document.addEventListener("change", (ev) => {
    const s = ev.target;
    if (!s.matches || !s.matches("select[data-bahan-pesan]")) return;
    const opt = s.selectedOptions[0], baris = s.closest("tr");
    const inp = baris && $("input[name=jumlah]", baris), sat = baris && $("[data-satuan]", baris);
    if (inp && opt) { inp.dataset.isiKemasan = opt.dataset.isi || ""; inp.dataset.namaKemasan = opt.dataset.kemasan || ""; segarKemasan(inp); }
    if (sat && opt) sat.textContent = opt.dataset.satuan || "";
  });
  const tambahBaris = $("[data-tambah-baris]");
  if (tambahBaris) tambahBaris.addEventListener("click", (ev) => {
    ev.preventDefault();
    const tb = document.getElementById(tambahBaris.dataset.tambahBaris), contoh = tb.querySelector("tr");
    const baru = contoh.cloneNode(true);
    $$("input", baru).forEach((i) => { i.value = ""; });
    $$("select", baru).forEach((s) => { s.selectedIndex = 0; });
    $$("[data-satuan], [id^=kem-]", baru).forEach((s) => { s.textContent = ""; });
    const out = $("output, .keluaran-kemasan", baru), inp = $("input[name=jumlah]", baru);
    if (out && inp) { const id = "kem-" + Math.random().toString(36).slice(2); out.id = id; inp.dataset.keluaran = id; }
    tb.appendChild(baru);
  });
  document.addEventListener("click", (ev) => {
    const h = ev.target.closest("[data-hapus-baris]");
    if (!h) return;
    const tb = h.closest("tbody");
    if (tb && tb.rows.length > 1) h.closest("tr").remove();
    ev.preventDefault();
  });

  // isi cepat stok terbuang dari usulan
  $$("[data-isi-terbuang]").forEach((b) => b.addEventListener("click", (ev) => {
    ev.preventDefault();
    const f = document.getElementById("form-terbuang");
    f.bahan_id.value = b.dataset.bahan; f.jumlah.value = b.dataset.jumlah; f.alasan.value = b.dataset.alasan || "Kedaluwarsa";
    f.scrollIntoView({ behavior: "smooth", block: "center" }); f.jumlah.focus();
  }));

  // saring baris tabel di sisi klien
  $$("input[data-saring-tabel]").forEach((inp) => inp.addEventListener("input", () => {
    const q = inp.value.trim().toLowerCase();
    $$("#" + inp.dataset.saringTabel + " tbody tr").forEach((tr) => { tr.hidden = q && !tr.textContent.toLowerCase().includes(q); });
  }));

  // status pelatihan
  const log = $("#log-pelatihan[data-url]");
  if (log) {
    const tanya = () => fetch(log.dataset.url, { credentials: "same-origin" }).then((r) => r.json()).then((d) => {
      log.textContent = d.log || "Menunggu log...";
      log.scrollTop = log.scrollHeight;
      if (d.status !== "berjalan") window.location.reload(); else setTimeout(tanya, 3000);
    }).catch(() => setTimeout(tanya, 5000));
    setTimeout(tanya, 1500);
  }

  // grafik
  window.PrediStok = {
    warna: { hijau: "#12c394", hijauTua: "#0b8566", biru: "#2f80ed", merah: "#e5393b", oranye: "#f59e0b", abu: "#8a949e",
      ungu: "#7c5cdb" },
    angka: (x) => (x === null || x === undefined ? "-" : Number(x).toLocaleString("id-ID", { maximumFractionDigits: 2 })),
    tanggal: (s) => { const d = new Date(s + "T00:00:00"); return d.toLocaleDateString("id-ID", { day: "2-digit", month: "short" }); },
    grafik: (id, config) => {
      const el = document.getElementById(id);
      if (!el || !window.Chart) return null;
      Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
      Chart.defaults.color = "#5f6b76";
      return new Chart(el, config);
    },
  };
})();
