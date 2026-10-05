"""admin_produk.py -- katalog produk chatbot: tabel (cari, filter, per halaman),
tambah, edit, dan nonaktifkan/aktifkan produk. Validasi yang menentukan ada di
backend (backend/produk.py); form ini hanya menampilkan pesannya per field.
Teks halaman admin berbahasa Inggris (keputusan user); nilai yang dikirim ke
backend tetap kode baku (kering, jerawat, facial_wash, ...)."""
import streamlit as st

from core import (KATEGORI_EN, MASALAH_KULIT_EN, TIPE_KULIT, ambil_halaman, angka, css, esc, judul_halaman,
                  navigasi_halaman, panggil)

PRODUK_CSS = """
.th { color:var(--ink-muted); font-size:.85rem; letter-spacing:.04em; white-space:nowrap; }
.st-key-tabel_head_produk { border-bottom:1px solid var(--border); padding-bottom:.6rem; margin-top:.6rem; }
[class*="st-key-bprod_"] { border-bottom:1px solid var(--border); padding:.6rem 0; }
/* markdown Streamlit punya margin bawah negatif (-1rem): baris "brand · PRD0984" jadi menimpa garis
   pemisah baris -- dinetralkan di dalam tabel */
.st-key-tabel_head_produk [data-testid="stMarkdown"], .st-key-tabel_head_produk [data-testid="stMarkdownContainer"],
[class*="st-key-bprod_"] [data-testid="stMarkdown"], [class*="st-key-bprod_"] [data-testid="stMarkdownContainer"] {
  margin-bottom:0 !important;
}
[class*="st-key-bprod_"] [data-testid="stMarkdownContainer"] p { margin-bottom:0 !important; }
.st-key-tabel_head_produk [data-testid="stMarkdownContainer"] p { margin-bottom:0 !important; }
/* nama listing Shopee bisa sangat panjang: maksimal 2 baris, nama lengkap di tooltip */
.td-nama { font-weight:600; color:var(--black); line-height:1.35; display:-webkit-box; -webkit-line-clamp:2;
  -webkit-box-orient:vertical; overflow:hidden; }
.td-brand { color:var(--ink-soft); font-size:.85rem; margin-top:.15rem; }
.td-kecil { color:var(--ink); font-size:.9rem; }
.td-kosong { color:var(--ink-muted); font-size:.9rem; }
.pill-outlier { background:var(--red-bg); color:var(--red-ink); }
.pill-info { background:var(--amber-bg); color:var(--amber-ink); }
.pill + .pill { margin-left:.3rem; }
/* tombol aksi: ikon saja, tanpa garis tepi */
[class*="st-key-edit_"] button, [class*="st-key-status_"] button {
  border:none !important; background:transparent !important; box-shadow:none !important;
  min-height:2.3rem; width:2.3rem; padding:0 !important; border-radius:50% !important;
}
[class*="st-key-edit_"] button:hover { background:var(--lavender-soft) !important; color:var(--lavender-ink) !important; }
[class*="st-key-status_"] button:hover { background:var(--cream-deep) !important; color:var(--black) !important; }
.st-key-tambah_produk button { font-weight:600 !important; white-space:nowrap; }
.form-sub { color:var(--ink-soft); font-size:.95rem; margin:-1rem 0 1.2rem; }
.grup-label { color:var(--ink-soft); font-size:.9rem; margin:.4rem 0 .1rem; }
.grup-catatan { color:var(--ink-muted); font-size:.82rem; margin:0 0 .5rem; }
.field-error { color:var(--red-ink); font-size:.84rem; line-height:1.35; margin:-.35rem 0 .5rem .15rem; }
.dialog-teks { color:var(--ink); line-height:1.55; margin-bottom:1rem; }
.dialog-teks b { color:var(--black); }

/* HP: tiap produk jadi kartu ringkas (sama seperti tabel user): nama di atas, lalu kategori, harga,
   tipe kulit sebaris dengan teks kecil, status + ikon aksi di kanan (judul kolom disembunyikan) */
@media (max-width:640px) {
  .st-key-tabel_head_produk { display:none !important; }
  [class*="st-key-bprod_"] [data-testid="stHorizontalBlock"] { flex-wrap:wrap !important; gap:.25rem .65rem !important;
    align-items:center; }
  [class*="st-key-bprod_"] [data-testid="stColumn"] { width:auto !important; min-width:0 !important; flex:0 0 auto !important; }
  [class*="st-key-bprod_"] [data-testid="stColumn"]:nth-child(1) { flex:1 1 100% !important; }
  [class*="st-key-bprod_"] [data-testid="stColumn"]:nth-child(2) p,
  [class*="st-key-bprod_"] [data-testid="stColumn"]:nth-child(3) p,
  [class*="st-key-bprod_"] [data-testid="stColumn"]:nth-child(4) p { font-size:.85rem; }
  /* baris 2: kategori · harga · tipe kulit; baris 3: status di kiri, ikon aksi di kanan -- dipisah oleh
     elemen semu selebar baris (order 3), supaya ikon tidak terlempar sendirian ke baris baru */
  [class*="st-key-bprod_"] [data-testid="stHorizontalBlock"]::after { content:""; order:3; flex-basis:100%; height:0; }
  [class*="st-key-bprod_"] [data-testid="stColumn"]:nth-child(-n+4) { order:2; }
  [class*="st-key-bprod_"] [data-testid="stColumn"]:nth-child(1) { order:1; }
  [class*="st-key-bprod_"] [data-testid="stColumn"]:nth-child(n+5) { order:4; }
  [class*="st-key-bprod_"] [data-testid="stColumn"]:nth-child(6) { margin-left:auto; }
}
"""

KOLOM = [3.2, 1.2, 1.1, 1.7, 1.0, 0.45, 0.55]  # kolom 6-7 = ikon edit & nonaktifkan/aktifkan
PER_HALAMAN = 20
STATUS = {"semua": "All statuses", "aktif": "Active", "nonaktif": "Inactive"}


def _opsi():
    ss = st.session_state
    if "opsi_produk" not in ss:
        data, err, _ = panggil("GET", "/admin/opsi-produk")
        if err:
            st.error(err)
            st.stop()
        ss.opsi_produk = data
    return ss.opsi_produk


def _label_kategori():
    """{kategori: label tampil} -- dict biasa (bukan fungsi yang membaca session_state),
    dipakai sebagai format_func dropdown."""
    return {k: KATEGORI_EN.get(k, v.capitalize()) for k, v in _opsi()["kategori"].items()}


def _rp(harga):
    return f"Rp{angka(int(round(harga)))}"


def _mode(mode=None):
    st.session_state.produk_mode = mode
    st.session_state.pop("produk_edit", None)


def _ubah_status(p, aktif):
    data, err, _ = panggil("PUT", f"/admin/products/{p['id']}/status", json={"is_active": aktif})
    st.session_state.produk_pesan = ("error", err) if err else \
        ("sukses", f"{data['message']} — {data['produk']['nama_produk']}")


def _batal_konfirmasi():
    st.session_state.pop("konfirmasi_nonaktif", None)


# pop-up tampil selama ada "konfirmasi_nonaktif" di session (diset tombol ⊘ di baris produk),
# jadi tombol di dalamnya tetap diproses walau halaman dijalankan ulang penuh
@st.dialog("Deactivate this product?", on_dismiss=_batal_konfirmasi)
def _konfirmasi_nonaktif(p):
    """Satu langkah verifikasi sebelum produk dinonaktifkan."""
    st.markdown(f'<div class="dialog-teks"><b>{esc(p["nama_produk"])}</b> ({esc(p["id"])}) will no longer be '
                'recommended by the chatbot. Its data stays in the database, and you can activate it again at any '
                'time.</div>', unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    if b1.button("Cancel", key="batal_nonaktif", use_container_width=True):
        _batal_konfirmasi()
        st.rerun()
    if b2.button("Deactivate", key="ya_nonaktif", type="primary", use_container_width=True):
        _batal_konfirmasi()
        _ubah_status(p, False)
        st.rerun()


# ---------------- tabel ----------------

def _baris(p, label_kat):
    with st.container(key=f"bprod_{p['id']}"):
        c = st.columns(KOLOM, vertical_alignment="center")
        tanda = ""
        if p["harga_outlier"]:
            tanda += ('<span class="pill pill-outlier" title="Price above Rp10,000,000 -- never recommended">'
                      'abnormal price</span>')
        if p["info_terbatas"]:
            tanda += ('<span class="pill pill-info" title="No product link, so original review quotes can\'t be '
                      'retrieved">limited info</span>')
        brand = f'<div class="td-brand">{esc(p["brand"])} · {esc(p["id"])}</div>' if p["brand"] else \
            f'<div class="td-brand">{esc(p["id"])}</div>'
        c[0].markdown(f'<div class="td-nama" title="{esc(p["nama_produk"])}">{esc(p["nama_produk"])}</div>{brand}'
                      + (f'<div style="margin-top:.3rem">{tanda}</div>' if tanda else ""), unsafe_allow_html=True)
        c[1].markdown(f'<span class="td-kecil">{esc(label_kat.get(p["kategori"], p["kategori"]))}</span>',
                      unsafe_allow_html=True)
        c[2].markdown(f'<span class="td-kecil">{_rp(p["harga"])}</span>' if p["harga"] is not None else
                      '<span class="td-kosong">no data</span>', unsafe_allow_html=True)
        tipe = ", ".join(TIPE_KULIT.get(t, t) for t in p["tipe_kulit_cocok"])
        c[3].markdown(f'<span class="td-kecil">{esc(tipe)}</span>' if tipe else
                      '<span class="td-kosong">no data yet</span>', unsafe_allow_html=True)
        c[4].markdown('<span class="pill pill-aktif">Active</span>' if p["is_active"] else
                      '<span class="pill pill-nonaktif">Inactive</span>', unsafe_allow_html=True)
        c[5].button("", key=f"edit_{p['id']}", icon=":material/edit:", help="Edit product",
                    on_click=_mode, args=(("edit", p["id"]),))
        if p["is_active"]:
            c[6].button("", key=f"status_{p['id']}", icon=":material/block:", help="Deactivate product",
                        on_click=st.session_state.__setitem__, args=("konfirmasi_nonaktif", p))
        elif c[6].button("", key=f"status_{p['id']}", icon=":material/check_circle:", help="Activate product"):
            _ubah_status(p, True)  # mengaktifkan kembali tidak berisiko -> tanpa konfirmasi
            st.rerun()


def _tabel():
    k1, k2 = st.columns([4, 1], vertical_alignment="center")
    with k1:
        judul_halaman("Product Management")
    k2.button("Add product", key="tambah_produk", type="primary", icon=":material/add:", use_container_width=True,
              on_click=_mode, args=("tambah",))
    pesan = st.session_state.pop("produk_pesan", None)
    if pesan:
        (st.error if pesan[0] == "error" else st.success)(pesan[1])
        for catatan in pesan[2:]:
            st.info(catatan)

    opsi, label_kat = _opsi(), _label_kategori()
    with st.container(key="kartu_produk"):
        f = st.columns([2.2, 1.4, 1.4, 1.1], vertical_alignment="bottom")
        q = f[0].text_input("Search products", placeholder="Search by product name or brand", key="cari_produk").strip()
        kategori = f[1].selectbox("Category", [""] + list(opsi["kategori"]), key="filter_kategori",
                                  format_func=lambda k: label_kat.get(k, k) if k else "All categories")
        tipe = f[2].selectbox("Skin type", [""] + opsi["tipe_kulit"], key="filter_tipe",
                              format_func=lambda t: TIPE_KULIT.get(t, t) if t else "All skin types")
        status = f[3].selectbox("Status", list(STATUS), key="filter_status", format_func=STATUS.get)

        params = {"q": q, "kategori": kategori, "tipe_kulit": tipe, "status": status, "per_halaman": PER_HALAMAN}
        data, err = ambil_halaman("/admin/products", "hal_produk", params, (q, kategori, tipe, status))
        if err:
            st.error(err)
            return

        with st.container(key="tabel_head_produk"):
            for kol, teks in zip(st.columns(KOLOM), ["Product name", "Category", "Price", "Suitable skin types",
                                                     "Status", "Actions", ""]):
                kol.markdown(f'<span class="th">{teks}</span>', unsafe_allow_html=True)
        if not data["produk"]:
            ada_filter = q or kategori or tipe or status != "semua"
            st.markdown('<div class="kosong-tabel">' + ("No products match these filters or this search. Try "
                        "loosening the filters." if ada_filter else "There are no products in the catalog yet.")
                        + '</div>', unsafe_allow_html=True)
        for p in data["produk"]:
            _baris(p, label_kat)
    navigasi_halaman("hal_produk", data, "products")
    if st.session_state.get("konfirmasi_nonaktif"):
        _konfirmasi_nonaktif(st.session_state.konfirmasi_nonaktif)


# ---------------- form tambah / edit ----------------

def _tampil_error(slot, err):
    """err: {field: pesan} dari backend, atau teks (409/404/dst)."""
    if isinstance(err, dict):
        umum = []
        for field, pesan in err.items():
            if field in slot:
                slot[field].markdown(f'<div class="field-error">{esc(pesan)}</div>', unsafe_allow_html=True)
            else:
                umum.append(f"{field}: {pesan}")
        if umum:
            st.error("; ".join(umum))
        st.error("The product was not saved — fix the fields marked in red.")
    else:
        st.error(err)


def _form(awal, kunci, label_simpan):
    """Form produk. awal: data produk (edit) atau {} (tambah). return: (isian, simpan, batal, slot)."""
    opsi, label_kat = _opsi(), _label_kategori()
    slot = {}
    with st.form(f"form_{kunci}", border=False):
        k1, k2 = st.columns(2, gap="medium")
        with k1:
            nama = st.text_input("Product name *", value=awal.get("nama_produk") or "", key=f"{kunci}_nama",
                                 placeholder="e.g. Acnes Sealing Jell")
            slot["nama_produk"] = st.empty()
            kat_list = [""] + list(opsi["kategori"])
            kategori = st.selectbox("Category *", kat_list, key=f"{kunci}_kategori",
                                    index=kat_list.index(awal["kategori"]) if awal.get("kategori") in kat_list else 0,
                                    format_func=lambda k: label_kat.get(k, k) if k else "Choose a category")
            slot["kategori"] = st.empty()
        with k2:
            brand = st.text_input("Brand", value=awal.get("brand") or "", key=f"{kunci}_brand",
                                  placeholder="e.g. Rohto (optional)")
            slot["brand"] = st.empty()
            harga = st.number_input("Price (Rp) *", value=int(awal["harga"]) if awal.get("harga") is not None else None,
                                    step=1000, key=f"{kunci}_harga", placeholder="e.g. 45000",
                                    help="Prices above Rp10,000,000 are still saved, but flagged as abnormal and "
                                         "never recommended.")
            slot["harga"] = st.empty()

        st.markdown('<div class="grup-label">Product characteristics</div><div class="grup-catatan">Fill in at '
                    'least one of suitable skin types, skin concerns, ingredients, or description — these are what '
                    'the recommendation engine matches on.</div>', unsafe_allow_html=True)
        slot["sinyal_rekomendasi"] = st.empty()
        st.markdown('<div class="grup-label">Suitable skin types</div>', unsafe_allow_html=True)
        kol = st.columns(len(opsi["tipe_kulit"]))
        tipe = [t for t, c in zip(opsi["tipe_kulit"], kol)
                if c.checkbox(TIPE_KULIT.get(t, t), value=t in (awal.get("tipe_kulit_cocok") or []),
                              key=f"{kunci}_tipe_{t}")]
        slot["tipe_kulit_cocok"] = st.empty()
        st.markdown('<div class="grup-label">Skin concerns addressed</div>', unsafe_allow_html=True)
        kol = st.columns(3)
        masalah = [m for i, m in enumerate(opsi["masalah_kulit"])
                   if kol[i % 3].checkbox(MASALAH_KULIT_EN.get(m, m), value=m in (awal.get("masalah_kulit_cocok") or []),
                                          key=f"{kunci}_masalah_{m}")]
        slot["masalah_kulit_cocok"] = st.empty()
        kandungan = st.text_area("Ingredients", value=awal.get("kandungan") or "", key=f"{kunci}_kandungan",
                                 height=80, placeholder="e.g. Niacinamide, Centella Asiatica",
                                 help="Separate with commas. Generic words such as 'dll', 'original', or 'premium' are "
                                      "removed automatically.")
        slot["kandungan"] = st.empty()
        deskripsi = st.text_area("Description", value=awal.get("deskripsi") or "", key=f"{kunci}_deskripsi",
                                 height=140, placeholder="e.g. suitable for acne-prone skin, helps calm redness")
        slot["deskripsi"] = st.empty()
        link = st.text_input("Product link", value=awal.get("link") or "", key=f"{kunci}_link",
                             placeholder="https://shopee.co.id/...",
                             help="Recommended. Without a link the chatbot can't retrieve original review quotes for "
                                  "this product (flagged 'limited info').")
        slot["link"] = st.empty()

        b1, b2, _ = st.columns([1.3, 1, 3])
        simpan = b1.form_submit_button(label_simpan, type="primary", use_container_width=True)
        batal = b2.form_submit_button("Cancel", use_container_width=True)
    isian = {"nama_produk": nama, "brand": brand, "kategori": kategori, "harga": harga, "tipe_kulit_cocok": tipe,
             "masalah_kulit_cocok": masalah, "kandungan": kandungan, "deskripsi": deskripsi, "link": link}
    return isian, simpan, batal, slot


def _catatan_simpan(p, kandungan_diketik):
    catatan = []
    if p["harga_outlier"]:
        catatan.append("Price above Rp10,000,000: the product is flagged 'abnormal price' and will not be "
                       "recommended.")
    if p["info_terbatas"]:
        catatan.append("No product link: flagged 'limited info' — the chatbot can't retrieve original review quotes "
                       "for this product.")
    if kandungan_diketik and kandungan_diketik.strip() and (p.get("kandungan") or "") != kandungan_diketik.strip():
        catatan.append(f"Generic words were removed from the ingredients. Saved as: {p.get('kandungan') or '(empty)'}")
    return catatan


def _tambah():
    judul_halaman("Add product")
    st.markdown('<div class="form-sub">A new product is used by the chatbot\'s recommendation engine as soon as it is '
                'saved.</div>', unsafe_allow_html=True)
    with st.container(key="kartu_form_produk"):
        isian, simpan, batal, slot = _form({}, "fp_tambah", "Save product")
    if batal:
        _mode(None)
        st.rerun()
    if simpan:
        data, err, _ = panggil("POST", "/admin/products", per_field=True, json=isian)
        if err:
            _tampil_error(slot, err)
            return
        p = data["produk"]
        st.session_state.produk_pesan = ("sukses", f"{data['message']} — {p['nama_produk']} ({p['id']})",
                                         *_catatan_simpan(p, isian["kandungan"]))
        # produk baru tampil paling atas di tabel tanpa filter
        for k in ("cari_produk", "filter_kategori", "filter_tipe", "filter_status"):
            st.session_state.pop(k, None)
        st.session_state.hal_produk = 1
        _mode(None)
        st.rerun()


def _beda(asli, isian):
    """Hanya field yang benar-benar diubah admin yang dikirim -- field lain
    tidak tersentuh sama sekali (skenario 5.1)."""
    ubah = {}
    for k in ("nama_produk", "brand", "kategori", "kandungan", "deskripsi", "link"):
        if (isian[k] or "").strip() != (asli.get(k) or "").strip():
            ubah[k] = isian[k]
    if isian["harga"] != (int(asli["harga"]) if asli.get("harga") is not None else None):
        ubah["harga"] = isian["harga"]
    for k in ("tipe_kulit_cocok", "masalah_kulit_cocok"):
        if set(isian[k]) != set(asli.get(k) or []):
            ubah[k] = isian[k]
    return ubah


def _muat_ulang_edit():
    st.session_state.pop("produk_edit", None)


def _edit(produk_id):
    ss = st.session_state
    # data SAAT FORM DIBUKA disimpan -- versinya dipakai untuk mendeteksi perubahan
    # oleh admin lain sementara form ini terbuka (skenario 5.5)
    if ss.get("produk_edit", {}).get("id") != produk_id:
        data, err, status = panggil("GET", f"/admin/products/{produk_id}")
        if err:
            judul_halaman("Edit product")
            st.error(err)
            st.button("Back to product list", key="kembali_daftar", on_click=_mode)
            return
        ss.produk_edit = data
    asli = ss.produk_edit
    judul_halaman("Edit product")
    st.markdown(f'<div class="form-sub">{esc(asli["id"])} · {"active" if asli["is_active"] else "inactive"} · '
                f'last updated {esc(asli.get("updated_at") or "-")}</div>', unsafe_allow_html=True)
    with st.container(key="kartu_form_produk"):
        isian, simpan, batal, slot = _form(asli, f"fp_edit_{asli['id']}_{asli['versi']}", "Save changes")
    if batal:
        _mode(None)
        st.rerun()
    if simpan:
        ubah = _beda(asli, isian)
        if not ubah:
            st.info("There are no changes to save.")
            return
        data, err, status = panggil("PUT", f"/admin/products/{asli['id']}", per_field=True,
                                    json={**ubah, "versi": asli["versi"]})
        if err:
            _tampil_error(slot, err)
            if status == 409:
                st.button("Reload product data", key="muat_ulang_edit", on_click=_muat_ulang_edit)
            elif status == 404:
                st.button("Back to product list", key="kembali_daftar", on_click=_mode)
            return
        p = data["produk"]
        st.session_state.produk_pesan = ("sukses", f"{data['message']} — {p['nama_produk']} ({p['id']})",
                                         *_catatan_simpan(p, isian["kandungan"] if "kandungan" in ubah else None))
        _mode(None)
        st.rerun()


def render():
    css(PRODUK_CSS)
    mode = st.session_state.get("produk_mode")
    if mode == "tambah":
        _tambah()
    elif isinstance(mode, tuple) and mode[0] == "edit":
        _edit(mode[1])
    else:
        _tabel()
