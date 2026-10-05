import re

import streamlit as st

from core import esc, login_sukses, panggil
from halaman.layout_auth import kartu, link

# validasi di form hanya untuk kenyamanan pengguna -- backend tetap memvalidasi
# ulang semuanya (request langsung ke API tidak lewat form ini)
POLA_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN, PASSWORD_MAKS_BYTE = 8, 72


def _validasi(nama, email, password, konfirmasi):
    """return: {field: pesan} -- per field, bukan 1 pesan umum."""
    err = {}
    if not nama.strip():
        err["nama"] = "Nama wajib diisi."
    if not email.strip():
        err["email"] = "Email wajib diisi."
    elif not POLA_EMAIL.match(email.strip()):
        err["email"] = "Format email tidak valid (contoh: nama@gmail.com)."
    if not password:
        err["password"] = "Password wajib diisi."
    elif len(password) < PASSWORD_MIN:
        err["password"] = f"Password minimal {PASSWORD_MIN} karakter."
    elif len(password.encode("utf-8")) > PASSWORD_MAKS_BYTE:
        err["password"] = f"Password maksimal {PASSWORD_MAKS_BYTE} karakter."
    if password and konfirmasi != password:
        err["konfirmasi"] = "Konfirmasi password tidak sama dengan password."
    return err


def render():
    with kartu("Create your account", "Sign up to save your chat history and product recommendations"):
        with st.form("form_register", border=False):
            slot = {}
            nama = st.text_input("Nama", placeholder="Masukkan nama anda")
            slot["nama"] = st.empty()
            email = st.text_input("Email", placeholder="Masukkan email anda")
            slot["email"] = st.empty()
            password = st.text_input("Password", type="password", placeholder="Minimal 8 karakter")
            slot["password"] = st.empty()
            konfirmasi = st.text_input("Konfirmasi Password", type="password", placeholder="Ulangi password anda")
            slot["konfirmasi"] = st.empty()
            kirim = st.form_submit_button("Register", use_container_width=True, type="primary")

        if kirim:
            # err: {field: pesan dalam HTML yang sudah di-escape}
            err = {f: esc(m) for f, m in _validasi(nama, email, password, konfirmasi).items()}
            if not err:
                _, pesan, status = panggil("POST", "/register", pakai_auth=False, per_field=True,
                                           json={"nama": nama, "email": email, "password": password})
                if status == 409:
                    err["email"] = f'{esc(pesan)} <a href="?ke=login" target="_self">Login di sini</a>'
                elif isinstance(pesan, dict):
                    err = {f: esc(m) for f, m in pesan.items() if f in slot} \
                        or {"nama": esc("; ".join(pesan.values()))}
                elif pesan:
                    st.error(pesan)  # mis. terlalu banyak percobaan (429) -- bukan salah satu field
                    err = None
            for field, teks in (err or {}).items():
                slot[field].markdown(f'<div class="field-error">{teks}</div>', unsafe_allow_html=True)
            if err == {}:
                data, pesan, _ = panggil("POST", "/login", pakai_auth=False,
                                         json={"email": email, "password": password})
                if pesan:
                    st.session_state.halaman = "login"
                else:
                    login_sukses(data)
                st.rerun()

        link("Already have an account?", "Login", "login")
