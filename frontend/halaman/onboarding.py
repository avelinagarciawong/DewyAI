import streamlit as st

from core import esc, form_kulit, simpan_profil
from halaman.layout_auth import kartu, link


def render():
    user = st.session_state.user
    judul = f"Halo, {esc(user['nama'].split()[0])} \U0001F44B" if user else "Let’s Get to know you"

    with kartu(judul, "Please fill your skin profile so we can give you more suitable <br>product recommendation"):
        data = form_kulit("form_onboarding", "Start Chat")
        if data:
            err = simpan_profil(data)
            if err:
                st.error(err)
            st.session_state.onboarding_selesai = True
            st.rerun()
        if not user:
            link("You're not logged in, so this profile won't be saved and you'll need to fill it in again "
                 "on your next visit.<br>Want us to remember your profile?", "Login", "login")