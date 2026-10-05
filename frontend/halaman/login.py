import streamlit as st

from core import esc, login_sukses, panggil
from halaman.layout_auth import kartu, link


def render():
    with kartu("Welcome back", "Login to keep your chat history and product recommendations"):
        if st.session_state.pesan_login:  # mis. sesi berakhir di tengah chat
            st.warning(st.session_state.pesan_login)
        with st.form("form_login", border=False):
            slot = {}
            email = st.text_input("Email", placeholder="Masukkan email anda")
            slot["email"] = st.empty()
            password = st.text_input("Password", type="password", placeholder="Masukkan password anda")
            slot["password"] = st.empty()
            kirim = st.form_submit_button("Login", use_container_width=True, type="primary")

        if kirim:
            # field kosong ditolak di sini, sebelum dikirim ke backend
            err = {}
            if not email.strip():
                err["email"] = "Email wajib diisi."
            if not password:
                err["password"] = "Password wajib diisi."
            if not err:
                data, pesan, _ = panggil("POST", "/login", pakai_auth=False, per_field=True,
                                         json={"email": email, "password": password})
                if isinstance(pesan, dict):
                    err = {f: m for f, m in pesan.items() if f in slot}
                elif pesan:
                    st.error(pesan)
                else:
                    login_sukses(data)
                    st.rerun()
            for field, teks in err.items():
                slot[field].markdown(f'<div class="field-error">{esc(teks)}</div>', unsafe_allow_html=True)

        link("Don't have an account?", "Register", "register")
