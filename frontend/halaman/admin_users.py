"""admin_users.py -- blok ringkasan + tabel akun (cari, per halaman) + tombol aktif/nonaktif."""
import streamlit as st

from core import (IKON_BOX, IKON_CHAT, IKON_USERS, ambil_halaman, angka, css, esc, judul_halaman, navigasi_halaman,
                  panggil, pill_role, pill_status, ringkasan_admin, stat_tiles)

USERS_CSS = """
.th { color:var(--ink-muted); font-size:.85rem; letter-spacing:.04em; }
.st-key-tabel_head { border-bottom:1px solid var(--border); padding-bottom:.6rem; }
[class*="st-key-baris_"] { border-bottom:1px solid var(--border); padding:.5rem 0; }
.td-nama { font-weight:600; color:var(--black); }
.td-email { color:var(--ink-soft); }
/* tombol aksi tanpa garis tepi: pill berwarna lembut */
[class*="st-key-toggle_"] button[kind="secondary"] { font-weight:600 !important; padding:.45rem 1.3rem !important;
  border:none !important; background:var(--cream) !important; }
[class*="st-key-toggle_"] button[kind="secondary"]:hover:not(:disabled) { background:var(--cream-deep) !important; }
/* markdown Streamlit punya margin bawah negatif (-1rem) -> isi baris menimpa garis pemisah; dinetralkan */
.st-key-tabel_head [data-testid="stMarkdown"], .st-key-tabel_head [data-testid="stMarkdownContainer"],
[class*="st-key-baris_"] [data-testid="stMarkdown"], [class*="st-key-baris_"] [data-testid="stMarkdownContainer"] {
  margin-bottom:0 !important;
}
[class*="st-key-baris_"] [data-testid="stMarkdownContainer"] p { margin-bottom:0 !important; }
.st-key-tabel_head [data-testid="stMarkdownContainer"] p { margin-bottom:0 !important; }
[class*="st-key-toggle_"] button:disabled { opacity:.4 !important; cursor:not-allowed !important; }
/* markdown otomatis menjadikan alamat email link -- di tabel ini cukup teks biasa */
.td-email a { color:inherit !important; text-decoration:none !important; pointer-events:none; }

/* HP: tabel lebar terpotong di layar sempit -> tiap baris jadi kartu ringkas: nama, email di bawahnya,
   lalu label peran & status sebaris dengan tombol aksi di kanan (judul kolom disembunyikan) */
@media (max-width:640px) {
  .st-key-tabel_head { display:none !important; }
  [class*="st-key-baris_"] [data-testid="stHorizontalBlock"] { flex-wrap:wrap !important; gap:.3rem .5rem !important;
    align-items:center; }
  [class*="st-key-baris_"] [data-testid="stColumn"] { width:auto !important; min-width:0 !important; flex:0 0 auto !important; }
  [class*="st-key-baris_"] [data-testid="stColumn"]:nth-child(1),
  [class*="st-key-baris_"] [data-testid="stColumn"]:nth-child(2) { flex:1 1 100% !important; }
  [class*="st-key-baris_"] [data-testid="stColumn"]:nth-child(2) p { font-size:.88rem; }
  [class*="st-key-baris_"] [data-testid="stColumn"]:nth-child(5) { margin-left:auto; }
}
"""

KOLOM = [2, 2.6, 1.1, 1.1, 1.3]
PER_HALAMAN = 20


def blok_ringkasan():
    """Blok ringkasan di ATAS tabel (bukan layar terpisah) -- angka dihitung
    backend langsung dari database setiap kali halaman dibuka."""
    r = ringkasan_admin()
    if not r:
        return
    stat_tiles([
        ("Total users", r["total_user"], IKON_USERS, "ikon-ungu", f"{angka(r['user_aktif'])} active"),
        ("Active products", r["produk_aktif"], IKON_BOX, "ikon-hijau", f"of {angka(r['total_produk'])} products"),
        ("Total conversations", r["total_percakapan"], IKON_CHAT, "ikon-amber", "saved in users' chat history"),
    ])


def render():
    css(USERS_CSS)
    judul_halaman("User Management")
    blok_ringkasan()

    with st.container(key="kartu_users"):
        q = st.text_input("Search users", placeholder="Search by name or email", key="cari_user",
                          label_visibility="collapsed").strip()
        data, err = ambil_halaman("/admin/users", "hal_users", {"q": q, "per_halaman": PER_HALAMAN}, q)
        if err:
            st.error(err)
            return
        with st.container(key="tabel_head"):
            for kol, teks in zip(st.columns(KOLOM), ["Name", "Email", "Role", "Status", "Action"]):
                kol.markdown(f'<span class="th">{teks}</span>', unsafe_allow_html=True)

        if not data["users"]:
            st.markdown(f'<div class="kosong-tabel">No users match "{esc(q)}".</div>'
                        if q else '<div class="kosong-tabel">No users have registered yet.</div>', unsafe_allow_html=True)

        for u in data["users"]:
            with st.container(key=f"baris_{u['id']}"):
                c = st.columns(KOLOM, vertical_alignment="center")
                c[0].markdown(f'<span class="td-nama">{esc(u["nama"])}</span>', unsafe_allow_html=True)
                c[1].markdown(f'<span class="td-email">{esc(u["email"])}</span>', unsafe_allow_html=True)
                c[2].markdown(pill_role(u), unsafe_allow_html=True)
                c[3].markdown(pill_status(u), unsafe_allow_html=True)
                label = "Deactivate" if u["is_active"] else "Activate"
                diri_sendiri = u["id"] == st.session_state.user["id"]
                if c[4].button(label, key=f"toggle_{u['id']}", type="secondary", disabled=diri_sendiri,
                               help="You can't deactivate your own account" if diri_sendiri else None):
                    _, err2, _ = panggil("PUT", f"/admin/users/{u['id']}", json={"is_active": not u["is_active"]})
                    st.error(err2) if err2 else st.rerun()

    navigasi_halaman("hal_users", data, "users")
