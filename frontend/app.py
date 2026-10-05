import streamlit as st
from core import ICON

st.set_page_config(page_title="Dew AI", page_icon=ICON, layout="wide")

import sidebar
from core import BACKEND_URL, backend_aman, state_awal
from styles import inject_base
from halaman import(admin_dashboard,admin_produk,admin_users,chat,login,onboarding,profile,register)

HALAMAN = {
    "chat": (chat.render, None),
    "profile": (profile.render, "user"),
    "admin_dashboard": (admin_dashboard.render, "admin"),
    "admin_users": (admin_users.render, "admin"),
    "admin_produk": (admin_produk.render, "admin"),
}

def main():
    state_awal()
    inject_base()
    ss = st.session_state
    if not backend_aman(BACKEND_URL):
        st.error(f"Koneksi ke backend ({BACKEND_URL}) harus lewat HTTPS supaya email, password, dan sesi login "
                 "tidak terkirim tanpa enkripsi. Ganti BACKEND_URL ke alamat https://.")
        st.stop()

    # link teks di kartu auth (?ke=login / ?ke=register)
    ke = st.query_params.get("ke")
    if ke in ("login", "register"):
        ss.halaman = ke
        st.query_params.clear()

    if ss.halaman == "login":
        return login.render()
    if ss.halaman == "register":
        return register.render()
    if not ss.onboarding_selesai:
        return onboarding.render()

    sidebar.render()
    fungsi, akses = HALAMAN.get(ss.halaman, HALAMAN["chat"])
    user = ss.user
    boleh = akses is None or (user and (akses == "user" or user["role"] == "Admin"))
    (fungsi if boleh else chat.render)()


main()