"""profile.py -- identitas, edit profil kulit, ganti password, logout."""
import streamlit as st

from core import css, esc, form_kulit, judul_halaman, keluar, panggil, simpan_profil

PROFILE_CSS = """
.identitas { display:flex; align-items:center; gap:1.1rem; }
/* markdown Streamlit punya margin bawah negatif (-1rem) -> isi kartu jadi turun; dinetralkan
   supaya avatar & nama pas di tengah secara vertikal */
.st-key-kartu_identitas [data-testid="stMarkdown"],
.st-key-kartu_identitas [data-testid="stMarkdownContainer"] { margin-bottom:0 !important; }
.avatar-inisial { width:3rem; height:3rem; border-radius:50%; background:var(--lavender-soft); color:var(--lavender-ink);
  display:flex; align-items:center; justify-content:center; font-weight:700; font-size:1.05rem; flex-shrink:0; }
.identitas-nama { font-weight:600; font-size:1.1rem; color:var(--black); }
.identitas-email { color:var(--ink-soft); font-size:.95rem; }

/* kedua kartu setinggi kolomnya, tombol form didorong ke dasar kartu -> Save
   Changes & Change Password selalu sejajar, berapa pun baris label masalah kulit */
[data-testid="stLayoutWrapper"]:has(> .st-key-kartu_kulit),
[data-testid="stLayoutWrapper"]:has(> .st-key-kartu_password),
.st-key-kartu_kulit, .st-key-kartu_password { flex:1 1 auto; }
.st-key-kartu_kulit :has(> [data-testid="stForm"]),
.st-key-kartu_password :has(> [data-testid="stForm"]),
.st-key-kartu_kulit [data-testid="stForm"], .st-key-kartu_password [data-testid="stForm"],
.st-key-kartu_kulit [data-testid="stForm"] > [data-testid="stVerticalBlock"],
.st-key-kartu_password [data-testid="stForm"] > [data-testid="stVerticalBlock"] {
  flex:1 1 auto; display:flex; flex-direction:column;
}
.st-key-kartu_kulit [data-testid="stElementContainer"]:has([data-testid="stFormSubmitButton"]),
.st-key-kartu_password [data-testid="stElementContainer"]:has([data-testid="stFormSubmitButton"]) { margin-top:auto; }

.field-error { color:var(--red-ink); font-size:.84rem; line-height:1.35; margin:-.35rem 0 .5rem .15rem; }

/* tombol logout putih, teks merah */
.st-key-logout button[kind="secondary"] {
  background:var(--white) !important; color:var(--red-ink) !important; border:none !important;
  min-height:3.2rem; font-size:1.05rem;
}
.st-key-logout button[kind="secondary"]:hover { background:var(--red-bg) !important; }
"""


def _validasi_password(lama, baru):
    """Syarat sama dengan backend (yang tetap memvalidasi ulang)."""
    err = {}
    if not lama:
        err["password_lama"] = "Current password is required."
    if not baru:
        err["password_baru"] = "New password is required."
    elif len(baru) < 8:
        err["password_baru"] = "Password must be at least 8 characters."
    elif len(baru.encode("utf-8")) > 72:
        err["password_baru"] = "Password can be at most 72 characters."
    elif baru == lama:
        err["password_baru"] = "New password can't be the same as your current password."
    return err


def render():
    css(PROFILE_CSS)
    user = st.session_state.user
    judul_halaman("Profile")

    inisial = "".join(w[0] for w in user["nama"].split()[:2]).upper()
    with st.container(key="kartu_identitas"):
        st.markdown(f'<div class="identitas"><div class="avatar-inisial">{esc(inisial)}</div><div>'
                    f'<div class="identitas-nama">{esc(user["nama"])}</div>'
                    f'<div class="identitas-email">{esc(user.get("email", ""))}</div></div></div>',
                    unsafe_allow_html=True)

    kol1, kol2 = st.columns(2, gap="medium")
    with kol1.container(key="kartu_kulit"):
        st.markdown('<div class="seksi-judul">Skin Profile</div>', unsafe_allow_html=True)
        data = form_kulit("form_profil_kulit", "Save Changes", en=True)
        if data:
            err = simpan_profil(data)
            st.error(err) if err else st.success("Profile saved.")

    with kol2.container(key="kartu_password"):
        st.markdown('<div class="seksi-judul">Change Password</div>', unsafe_allow_html=True)
        with st.form("form_ganti_password", border=False, clear_on_submit=False):
            slot = {}
            lama = st.text_input("Current password", type="password")
            slot["password_lama"] = st.empty()
            baru = st.text_input("New password", type="password", placeholder="Min 8 characters")
            slot["password_baru"] = st.empty()
            ganti = st.form_submit_button("Change Password", use_container_width=True, type="primary")
        if ganti:
            err = _validasi_password(lama, baru)
            if not err:
                data, pesan, status = panggil("PUT", "/change-password", boleh_401_bisnis=True, per_field=True,
                                              json={"password_lama": lama, "password_baru": baru})
                if isinstance(pesan, dict):
                    err = {f: m for f, m in pesan.items() if f in slot}
                elif status == 401:  # password lama salah (sesi yang tidak sah sudah ditangani panggil)
                    err = {"password_lama": pesan}
                elif pesan:
                    st.error(pesan)
                else:
                    # sesi ini tetap jalan dengan token baru; sesi di device lain dikeluarkan
                    st.session_state.token = data["access_token"]
                    st.success(data["message"])
            for field, teks in err.items():
                slot[field].markdown(f'<div class="field-error">{esc(teks)}</div>', unsafe_allow_html=True)

    if st.button("Log out", key="logout", use_container_width=True, type="secondary"):
        keluar()
        st.rerun()