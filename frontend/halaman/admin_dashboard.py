"""admin_dashboard.py -- ringkasan akun & katalog + shortcut kelola produk.
Angkanya dari sumber yang sama dengan blok ringkasan di User Management
(GET /admin/ringkasan), jadi kedua layar tidak pernah menunjukkan angka beda."""
import streamlit as st

from core import (IKON_BOX, IKON_CHAT, IKON_SHIELD, IKON_USERS, angka, css, esc, judul_halaman, panggil, pill_role,
                  pill_status, pindah, ringkasan_admin, stat_tiles)

DASHBOARD_CSS = """
.tabel-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; }
.tabel { width:100%; min-width:420px; border-collapse:collapse; }
.tabel th, .tabel td { border:none; background:transparent; text-align:left; }
.tabel th { font-weight:500; color:var(--ink-muted); font-size:.85rem; letter-spacing:.04em;
  padding:.2rem .4rem .9rem; border-bottom:1px solid var(--border); }
.tabel td { padding:1.1rem .4rem; border-bottom:1px solid var(--border); font-size:.98rem; }
.tabel tr:last-child td { border-bottom:none; }
.tabel .nama { font-weight:600; color:var(--black); }
.tabel .email { color:var(--ink-soft); }
/* HP: tiap baris jadi kartu ringkas (sama seperti User Management), judul kolom disembunyikan */
@media (max-width:640px) {
  .tabel { min-width:0; border:none !important; }
  .tabel thead { display:none; }
  .tabel tr { display:flex; flex-wrap:wrap; align-items:center; gap:.3rem .5rem; padding:.85rem .1rem;
    border:none !important; border-bottom:1px solid var(--border) !important; }
  .tabel tr:first-child { padding-top:.2rem; }
  .tabel tr:last-child { border-bottom:none !important; }
  .tabel td { padding:0; border:none !important; }
  .tabel td.nama, .tabel td.email { flex:1 1 100%; }
  .tabel td.email { font-size:.88rem; }
}

.dataset-judul { font-weight:600; font-size:1.05rem; color:var(--black); margin-top:.8rem; }
.dataset-desc { color:var(--ink-soft); font-size:.95rem; margin:.4rem 0 .6rem; }
.st-key-buka_produk button[kind="secondary"] { font-weight:600 !important; padding:.5rem 1.3rem !important; }
"""


def _tabel_users(users):
    baris = "".join(
        f'<tr><td class="nama">{esc(u["nama"])}</td><td class="email">{esc(u["email"])}</td>'
        f'<td>{pill_role(u)}</td><td>{pill_status(u)}</td></tr>'
        for u in users
    )
    st.markdown('<div class="tabel-wrap"><table class="tabel"><thead>'
                '<tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th></tr></thead>'
                f'<tbody>{baris}</tbody></table></div>', unsafe_allow_html=True)


def render():
    css(DASHBOARD_CSS)
    judul_halaman("Dashboard")

    r = ringkasan_admin()
    if not r:
        return
    stat_tiles([
        ("Total accounts", r["total_user"], IKON_USERS, "ikon-ungu", f"{angka(r['user_aktif'])} active"),
        ("Admins", r["total_admin"], IKON_SHIELD, "ikon-merah", None),
        ("Active products", r["produk_aktif"], IKON_BOX, "ikon-hijau", f"of {angka(r['total_produk'])} products"),
        ("Total conversations", r["total_percakapan"], IKON_CHAT, "ikon-amber", None),
    ])

    data, err, _ = panggil("GET", "/admin/users", params={"per_halaman": 5})
    if err:
        st.error(err)
        return

    kol1, kol2 = st.columns([1.4, 1], gap="large")
    with kol1:
        st.markdown('<div class="seksi-judul">Users</div>', unsafe_allow_html=True)
        with st.container(key="kartu_users_ringkas"):
            _tabel_users(data["users"])

    with kol2:
        st.markdown('<div class="seksi-judul">Dataset</div>', unsafe_allow_html=True)
        with st.container(key="kartu_dataset"):
            st.markdown(f'<span class="pill pill-aktif">{angka(r["produk_aktif"])} active products</span>'
                        '<div class="dataset-judul">Product Management</div>'
                        '<div class="dataset-desc">Add, edit, or deactivate the products recommended by the '
                        'chatbot.</div>', unsafe_allow_html=True)
            if st.button("Manage products", key="buka_produk", type="secondary"):
                pindah("admin_produk")
