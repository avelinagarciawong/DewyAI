import streamlit as st

_FONT = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700'
         '&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">')

"""styles.py -- CSS global untuk semua halaman."""
import streamlit as st

_FONT = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700'
         '&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">')

BASE_CSS = """
:root {
  /* Grays/Black -- dari Figma */
  --white:#FFFFFF;
  --ink-soft:#8A8172;     /* subjudul, label */
  --ink-muted:#B6AF9E;    /* placeholder, teks sekunder */
  --ink:#2A2620;          /* teks biasa */
  --border:#E9E2D3;
  --pure-black:#000000;   /* link */
  --black:#1C1A17;        /* judul, tombol utama */
  --pink:#FF8FBE;

  /* halaman lain (chat, sidebar, admin) */
  --cream:#FEF8F0; --cream-deep:#F9EED9;
  --lavender-bg:#ECEAFB; --lavender-soft:#E9E8F9; --lavender-ink:#332B99;
  --green-bg:#DEFBE6; --green-ink:#1A8A4C;
  --red-bg:#FBEAEA; --red-ink:#B23A3A;
  --amber-bg:#FCEBC9; --amber-ink:#93650B;
}
html, body, [class^="css"], [class*=" css"] {
  font-family:"Public Sans", -apple-system, "Segoe UI", sans-serif; color:var(--ink);
}
#MainMenu, footer { visibility:hidden; }
/* elemen yang isinya cuma <style>/<link> (CSS yang disuntik lewat st.markdown) tetap memakan jarak antar-elemen
   -> disembunyikan; CSS-nya tetap berlaku */
[data-testid="stElementContainer"]:has(style), [data-testid="stElementContainer"]:has(link) { display:none; }
header[data-testid="stHeader"] { background:transparent; }
.stApp { background-color:var(--cream); }
h1, h2, h3 { font-family:"Playfair Display", serif; color:var(--black); }
code { font-family:"IBM Plex Mono", monospace; }

/* tombol */
button[kind="primary"], button[kind="primaryFormSubmit"] {
  background:var(--black) !important; color:var(--white) !important; border:1px solid var(--black) !important;
  border-radius:999px !important; font-weight:600 !important;
}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover { opacity:.88; }
button[kind="secondary"], button[kind="secondaryFormSubmit"] {
  background:var(--white) !important; color:var(--ink) !important; border:1px solid var(--border) !important;
  border-radius:999px !important;
}

/* judul halaman & judul seksi */
.halaman-judul { font-family:"Public Sans", sans-serif; font-size:2rem; font-weight:500; color:var(--black); margin:1rem 0 1.6rem; }
.seksi-judul { font-size:1.35rem; font-weight:500; color:var(--black); margin:0 0 1rem; }

/* kartu (container dengan key diawali "kartu") */
/* tanpa garis tepi: kartu putih sudah cukup terbedakan dari latar krem (permintaan user) */
[class*="st-key-kartu"] { background:var(--white); border:none; border-radius:20px; padding:1.4rem 1.5rem; }

/* field form di dalam kartu (profile, product management) */
[class*="st-key-kartu"] [data-testid="stWidgetLabel"] p { color:var(--ink-soft); font-size:.9rem; }
[class*="st-key-kartu"] [data-baseweb="select"] > div,
[class*="st-key-kartu"] [data-baseweb="input"] {
  background:var(--white) !important; border:1px solid var(--border) !important; border-radius:12px !important;
  min-height:47px; box-shadow:none !important; outline:none !important;
}
[class*="st-key-kartu"] [data-baseweb="input"] > div,
[class*="st-key-kartu"] [data-baseweb="input"] input { outline:none !important; box-shadow:none !important; }
[class*="st-key-kartu"] [data-baseweb="input"] > div { background:transparent !important; }
/* wrapper khusus number_input (Budget) -- beda dari [data-baseweb="input"], punya border merah sendiri bawaan Streamlit */
[class*="st-key-kartu"] [data-testid="stNumberInputContainer"] {
  border:1px solid transparent !important; border-radius:12px !important;
  height:auto !important; overflow:visible !important;
}
[class*="st-key-kartu"] [data-testid="stNumberInputContainer"]:focus-within { border-color:var(--black) !important; }
[class*="st-key-kartu"] [data-baseweb="select"] > div:focus-within,
[class*="st-key-kartu"] [data-baseweb="input"]:focus-within { border-color:var(--black) !important; box-shadow:none !important; outline:none !important; }
[class*="st-key-kartu"] input, [class*="st-key-kartu"] [data-baseweb="select"] div { color:var(--ink) !important; }
[class*="st-key-kartu"] [data-baseweb="select"] div[value="Masukkan tipe kulit anda"],
[class*="st-key-kartu"] [data-baseweb="select"] div[value="Masukkan masalah kulit anda"],
[class*="st-key-kartu"] [data-baseweb="select"] div[value="Select your skin type"] { color:var(--ink-muted) !important; }
[class*="st-key-kartu"] [data-baseweb="select"] div[value] {
  display:flex !important; align-items:center; justify-content:flex-start; height:100%; width:100%; text-align:left;
}
[class*="st-key-kartu"] input::placeholder { color:var(--ink-muted) !important; }
[class*="st-key-kartu"] [data-baseweb="select"] input { padding-left:0 !important; }
[class*="st-key-kartu"] [data-testid="stMultiSelect"] [data-baseweb="select"] div:not(:has(*)) {
  color:var(--ink-muted) !important; padding-left:4px !important;
}
[class*="st-key-kartu"] [data-testid="stMultiSelect"] [data-baseweb="select"] > div > div:first-child { padding-left:2px !important; }
[class*="st-key-kartu"] [data-baseweb="tag"] {
  background:var(--lavender-soft) !important; border-radius:999px !important; margin:.2rem .3rem .2rem 0 !important;
}
[class*="st-key-kartu"] [data-baseweb="tag"] span { color:var(--lavender-ink) !important; }
[class*="st-key-kartu"] [data-baseweb="tag"] svg { fill:var(--lavender-ink) !important; }
[class*="st-key-kartu"] [data-baseweb="checkbox"] > span {
  background-color:var(--white) !important; border:1.5px solid var(--ink-muted) !important; border-radius:5px !important;
}
[class*="st-key-kartu"] [data-baseweb="checkbox"]:has(input:checked) > span {
  background-color:var(--black) !important; border-color:var(--black) !important;
}
[class*="st-key-kartu"] button[data-testid^="stNumberInputStep"], [data-testid="InputInstructions"] { display:none; }
[class*="st-key-kartu"] button[kind="primaryFormSubmit"] { min-height:3.3rem; }

/* pill role & status */
.pill { display:inline-block; padding:.18rem .65rem; border-radius:999px; font-size:.78rem; font-weight:600; }
.pill-user { background:var(--lavender-soft); color:var(--lavender-ink); }
.pill-admin { background:var(--amber-bg); color:var(--amber-ink); }
.pill-aktif { background:var(--green-bg); color:var(--green-ink); }
.pill-nonaktif, .pill-belum-aktif { background:var(--red-bg); color:var(--red-ink); }
.pill-belum-aktif { font-family:"IBM Plex Mono"; font-size:.68rem; letter-spacing:.06em; text-transform:uppercase; }

/* dropdown pilihan selectbox (dirender lewat portal, di luar kartu/kunci manapun) */
ul[data-testid="stSelectboxVirtualDropdown"] { background:var(--lavender-bg) !important; }
ul[data-testid="stSelectboxVirtualDropdown"] li[role="option"] { color:var(--ink) !important; }
ul[data-testid="stSelectboxVirtualDropdown"] li[role="option"]:hover,
ul[data-testid="stSelectboxVirtualDropdown"] li[aria-selected="true"] { background:var(--lavender-soft) !important; }
"""


def inject_base():
    st.markdown(_FONT, unsafe_allow_html=True)
    st.markdown(f"<style>{BASE_CSS}</style>", unsafe_allow_html=True)