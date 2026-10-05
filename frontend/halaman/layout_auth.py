import streamlit as st

from core import BACKGROUND, css, data_uri, maskot

AUTH_CSS = """
/* sembunyikan toolbar Streamlit di halaman auth */
header[data-testid="stHeader"] { display:none; }

/* background halaman */
div[data-testid="stAppViewContainer"] { background:__BG__; }
.block-container, [data-testid="stMainBlockContainer"] { padding-top:0 !important; padding-bottom:3rem; }

/* kartu */
.st-key-auth_card {
  background:var(--white); border-radius:24px; width:100%; max-width:680px; align-self:center;
  margin:10vh auto 4vh; padding:36px;
  box-shadow:0 12px 40px -24px rgba(60,50,120,.18);
}

/* mobile: kartu nempel ke tepi layar & padding lebih rapat */
@media (max-width:640px) {
  .st-key-auth_card { max-width:92vw; margin:6vh auto 3vh; padding:1.4rem 1.3rem 1.2rem; border-radius:20px; }
  .auth-title { font-size:1.7rem !important; }
  /* pemisah baris untuk layar lebar membuat subjudul terpecah 3 baris di HP */
  .auth-sub br { display:none; }
  .auth-sub { font-size:.98rem; }
}

/* maskot + judul + subjudul */
.auth-head { display:flex; flex-direction:column; align-items:center; text-align:center; }
.auth-title { font-family:"Playfair Display", serif; font-size:2.25rem; font-weight:700; color:var(--black);
  margin:1.1rem 0 .4rem; line-height:1.15; }
.auth-sub { color:var(--ink-soft); font-size:1.05rem; line-height:1.5; margin-bottom:24px; }

/* pesan error tepat di bawah field yang bermasalah */
.field-error { color:var(--red-ink); font-size:.84rem; line-height:1.35; margin:-.35rem 0 .5rem .15rem; }
.field-error a { color:var(--red-ink) !important; font-weight:600; text-decoration:underline; }

/* teks + link di bawah tombol */
.auth-switch { color:var(--ink-soft); font-size:.85rem; text-align:center; margin-top:.2rem; }
.auth-switch a { color:var(--pure-black) !important; font-weight:600; text-decoration:underline; }

/* label */
.st-key-auth_card [data-testid="stWidgetLabel"] p { color:var(--ink-soft); font-size:.85rem; font-weight:500; }

/* dropdown & input */
.st-key-auth_card [data-baseweb="select"] > div,
.st-key-auth_card [data-baseweb="input"] {
  background:var(--white) !important; border:1px solid var(--border) !important; border-radius:10px !important;
  min-height:47px; box-shadow:none !important; outline:none !important;
}
.st-key-auth_card [data-baseweb="input"] > div,
.st-key-auth_card [data-baseweb="input"] input { outline:none !important; box-shadow:none !important; }
.st-key-auth_card [data-baseweb="input"] > div { background:transparent !important; }
/* wrapper khusus number_input (Budget) -- beda dari [data-baseweb="input"], punya border merah sendiri bawaan Streamlit */
.st-key-auth_card [data-testid="stNumberInputContainer"] {
  border:1px solid transparent !important; border-radius:10px !important;
  height:auto !important; overflow:visible !important;  /* tinggi bawaan 40px memotong garis atas/bawah kotak 47px */
}
.st-key-auth_card [data-testid="stNumberInputContainer"]:focus-within { border-color:var(--black) !important; }
.st-key-auth_card [data-baseweb="select"] > div:focus-within,
.st-key-auth_card [data-baseweb="input"]:focus-within { border-color:var(--black) !important; box-shadow:none !important; outline:none !important; }
.st-key-auth_card [data-baseweb="select"] div,
.st-key-auth_card input { color:var(--ink) !important; font-size:1rem !important; }
.st-key-auth_card [data-baseweb="select"] div[value="Masukkan tipe kulit anda"],
.st-key-auth_card [data-baseweb="select"] div[value="Masukkan masalah kulit anda"] { color:var(--ink-muted) !important; }
.st-key-auth_card [data-baseweb="select"] div[value] {
  display:flex !important; align-items:center; justify-content:flex-start; height:100%; width:100%; text-align:left;
}
.st-key-auth_card [data-baseweb="select"] svg { fill:var(--black); }
.st-key-auth_card [data-baseweb="select"] > div { padding-left:.4rem; }
.st-key-auth_card input { padding-left:1.1rem !important; }
.st-key-auth_card [data-baseweb="select"] input { padding-left:0 !important; }

/* multi-pilih masalah kulit: placeholder abu-abu, pilihan jadi label lavender */
.st-key-auth_card [data-testid="stMultiSelect"] [data-baseweb="select"] div:not(:has(*)) {
  color:var(--ink-muted) !important; padding-left:4px !important;
}
.st-key-auth_card [data-testid="stMultiSelect"] [data-baseweb="select"] > div > div:first-child { padding-left:2px !important; }
.st-key-auth_card [data-baseweb="tag"] {
  background:var(--lavender-soft) !important; border-radius:999px !important; margin:.2rem .3rem .2rem 0 !important;
}
.st-key-auth_card [data-baseweb="tag"] span { color:var(--lavender-ink) !important; font-size:.9rem !important; }
.st-key-auth_card [data-baseweb="tag"] svg { fill:var(--lavender-ink) !important; }

/* checkbox "Tidak ada batas budget" */
.st-key-auth_card [data-baseweb="checkbox"] > span {
  background-color:var(--white) !important; border:1.5px solid var(--ink-muted) !important; border-radius:5px !important;
}
.st-key-auth_card [data-baseweb="checkbox"]:has(input:checked) > span {
  background-color:var(--black) !important; border-color:var(--black) !important;
}
.st-key-auth_card [data-testid="stCheckbox"] p { color:var(--ink-soft); font-size:.9rem; }
.st-key-auth_card input::placeholder { color:var(--ink-muted) !important; }
.st-key-auth_card button[data-testid^="stNumberInputStep"] { display:none; }
.st-key-auth_card [data-testid="InputInstructions"] { display:none; }

/* browser autofill (email/password tersimpan) bikin background jadi abu-abu/kuning bawaan
   browser -- dipaksa balik putih pakai trik box-shadow inset, background-color biasa tidak mempan */
.st-key-auth_card input:-webkit-autofill,
.st-key-auth_card input:-webkit-autofill:hover,
.st-key-auth_card input:-webkit-autofill:focus {
  -webkit-box-shadow:0 0 0 1000px var(--white) inset !important;
  -webkit-text-fill-color:var(--ink) !important;
  caret-color:var(--ink);
}

/* tombol show/hide password */
.st-key-auth_card button[aria-label*="password" i] { color:var(--ink) !important; }
.st-key-auth_card button[aria-label*="password" i] svg { fill:var(--ink) !important; }

/* tombol submit */
.st-key-auth_card button[kind="primaryFormSubmit"],
.st-key-auth_card button[kind="primary"] { min-height:55px; font-size:1rem !important; margin-top:.8rem; }
"""


def kartu(judul, sub=None):
    """Pakai dengan `with kartu(...):` -- widget di dalamnya masuk ke kartu putih."""
    bg = f'url("{data_uri(str(BACKGROUND))}") center / cover no-repeat fixed'
    css(AUTH_CSS.replace("__BG__", bg))
    wadah = st.container(key="auth_card")
    sub_html = f'<div class="auth-sub">{sub}</div>' if sub else ""
    wadah.markdown(f'<div class="auth-head">{maskot(48)}<div class="auth-title">{judul}</div>{sub_html}</div>',
                   unsafe_allow_html=True)
    return wadah


def link(teks, label, target):
    """Teks + link bergaris bawah (?ke=login), dibaca di app.py."""
    st.markdown(f'<div class="auth-switch">{teks} <a href="?ke={target}" target="_self">{label}</a></div>',
                unsafe_allow_html=True)