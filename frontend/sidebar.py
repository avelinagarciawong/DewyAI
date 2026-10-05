"""sidebar.py -- navigasi untuk chat, profile, dan halaman admin.
Guest: Chat + (Recents kalau ada) + footer Log In.
User login: Chat, Profile, (Admin), Recents."""
from datetime import datetime, timezone

import streamlit as st
import streamlit.components.v1 as components

from core import css, maskot, panggil, pindah

S = 'section[data-testid="stSidebar"]'

SIDEBAR_CSS = f"""
{S} {{ background:var(--white); border-right:1px solid var(--border); }}

/* brand: "Dew AI" + maskot di kanannya, tombol tutup sidebar (ikon garis tiga) di ujung kanan baris yang sama */
.brand {{ display:flex; align-items:center; gap:.45rem; height:2.25rem; margin:1.6rem 0 1.1rem; }}
.brand-nama {{ font-family:"Playfair Display", serif; font-weight:700; font-size:1.375rem;
  line-height:1; color:var(--black); }}
{S} [data-testid="stSidebarHeader"] {{ height:0; min-height:0; padding:0; margin:0; position:relative; z-index:3; }}
/* top = tengah baris brand (1.6rem + 2.25rem/2) - setengah tinggi tombol (28px) */
{S} [data-testid="stSidebarCollapseButton"] {{
  position:absolute; top:calc(2.725rem - 14px); right:0; visibility:visible !important; opacity:1 !important;
  display:block !important;
}}
/* ikon bawaan (panah ganda) diganti garis tiga */
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"],
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"],
[data-testid="stSidebarCollapsedControl"] [data-testid="stIconMaterial"] {{
  font-size:0 !important; color:transparent !important; display:inline-block; width:1.125rem; height:.75rem;
  background:linear-gradient(var(--black), var(--black)) 0 0 / 100% 2px no-repeat,
             linear-gradient(var(--black), var(--black)) 0 50% / 100% 2px no-repeat,
             linear-gradient(var(--black), var(--black)) 0 100% / 100% 2px no-repeat;
}}

/* semua tombol secondary di sidebar: teks rata kiri tanpa kotak */
{S} button[kind="secondary"] {{
  background:transparent !important; border:none !important; box-shadow:none !important;
  color:var(--ink) !important; justify-content:flex-start !important; border-radius:14px !important;
}}
{S} button[kind="secondary"] div {{ justify-content:flex-start; }}
{S} button[kind="secondary"] p {{ text-align:left; white-space:normal; }}
{S} button[kind="secondary"]:hover {{ background:var(--cream) !important; }}

/* item navigasi */
{S} [class*="st-key-nav"] button[kind="secondary"] {{
  min-height:2.8rem; padding:.6rem 1rem !important; font-size:1rem; font-weight:500;
}}
{S} [class*="st-key-navaktif"] button[kind="secondary"] {{
  background:var(--lavender-soft) !important; color:var(--lavender-ink) !important; font-weight:600 !important;
}}
{S} [class*="st-key-navaktif"] button[kind="secondary"]:hover {{ background:var(--lavender-soft) !important; }}

/* judul seksi (Recents, Admin) */
.sidebar-seksi {{ font-weight:600; font-size:1.02rem; color:var(--black); margin:1.6rem 0 .3rem; }}
.sidebar-kosong {{ font-size:.88rem; color:var(--ink-muted); line-height:1.45; margin-top:.3rem; }}

/* item recents: judul, tanggal kecil abu-abu di belakangnya */
{S} [class*="st-key-recent"] button[kind="secondary"] {{ min-height:0; padding:.5rem 0 !important; font-size:.95rem; }}
{S} [class*="st-key-recent"] button p {{ line-height:1.45; }}
{S} [class*="st-key-recent"] button p span {{
  font-size:.78rem; color:var(--ink-muted) !important; white-space:nowrap; margin-left:.25rem;
}}
{S} [class*="st-key-recent"] button[kind="secondary"]:hover {{
  background:transparent !important; color:var(--lavender-ink) !important;
}}

/* footer guest menempel di dasar sidebar: isi sidebar dijadikan kolom flex setinggi sidebar
   (bukan hitungan 100vh, yang meleset oleh padding bawah bawaan Streamlit 6rem & toolbar
   browser HP), lalu footer didorong ke bawah dengan margin-top:auto -- kalau Recents panjang,
   footer tetap di paling bawah setelah isinya dan sidebar bisa di-scroll */
{S} [data-testid="stSidebarUserContent"]:has(.st-key-sidebar_foot) {{
  box-sizing:border-box; min-height:100%; display:flex; flex-direction:column; padding-bottom:1.75rem;
}}
{S} [data-testid="stSidebarUserContent"]:has(.st-key-sidebar_foot) > div {{
  flex:1 0 auto; display:flex; flex-direction:column;
}}
{S} [data-testid="stSidebarUserContent"]:has(.st-key-sidebar_foot) > div > [data-testid="stVerticalBlock"] {{ flex:1 0 auto; }}
{S} [data-testid="stVerticalBlock"] > div:has(.st-key-sidebar_foot),
{S} [data-testid="stVerticalBlock"] > .st-key-sidebar_foot {{ margin-top:auto; }}
.st-key-sidebar_foot {{ border-top:1px solid var(--border); padding-top:1.1rem; }}
.sidebar-foot-teks {{ font-size:.9rem; color:var(--ink-soft); line-height:1.45; margin-bottom:.4rem; }}
.st-key-sidebar_foot button[kind="primary"] {{ min-height:2.9rem; font-size:1rem !important; }}
.nav-eyebrow {{ font-family:"IBM Plex Mono"; font-size:.72rem; letter-spacing:.12em; text-transform:uppercase;
  color:var(--ink-muted); margin:1.4rem 0 .3rem 1rem; }}
"""




def _nav_item(icon, label, target):
    aktif = st.session_state.halaman == target
    key = f"navaktif_{target}" if aktif else f"nav_{target}"
    if st.sidebar.button(label, key=key, icon=icon, use_container_width=True, type="secondary"):
        if aktif and target == "chat":  # klik Chat saat sudah di chat = percakapan baru
            st.session_state.update(conversation_id=None, riwayat_pesan=[], konteks=None, tutup_sidebar_hp=True)
            st.rerun()
        pindah(target)


BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def _tanggal(waktu_utc):
    """'2026-09-26 03:15:00' (UTC dari SQLite) -> '26 Sep' di zona waktu lokal."""
    try:
        t = datetime.fromisoformat(waktu_utc).replace(tzinfo=timezone.utc).astimezone()
    except (TypeError, ValueError):
        return ""
    return f"{t.day} {BULAN[t.month - 1]}" + ("" if t.year == datetime.now().year else f" {t.year}")


def _pesan_dari_riwayat(m):
    """Pesan riwayat dari backend -> bentuk yang sama dengan pesan chat aktif
    (termasuk kartu produk & tabel perbandingan), jadi tampil utuh."""
    pesan = {"peran": "assistant" if m["sender"] == "bot" else "user", "isi": m["content"]}
    data = m.get("data") or {}
    pesan.update(produk=data.get("recommendation") or [], grup=data.get("grup"), perbandingan=data.get("perbandingan"))
    return pesan


def _daftar_recents():
    """List (key, label, conversation_id, pesan, konteks). User login dari backend
    (termasuk ingatan percakapannya, jadi bisa langsung dilanjutkan), guest dari
    sesi. None = gagal memuat."""
    if st.session_state.user:
        data, err, _ = panggil("GET", "/history")
        if err:
            return None
        return [
            (f"recent_{p['id']}", f"{p['title'] or '(tanpa judul)'} :gray[{_tanggal(p.get('updated_at') or p['created_at'])}]",
             p["id"], [_pesan_dari_riwayat(m) for m in p["messages"]], p.get("konteks"))
            for p in data["conversations"]
        ]
    lokal = st.session_state.percakapan_lokal
    return [(f"recent_lokal_{cid}", v["judul"], cid, list(v["pesan"]), v.get("konteks"))
            for cid, v in reversed(list(lokal.items()))]


def _recents():
    daftar = _daftar_recents()
    if daftar is None:
        return
    login = st.session_state.user is not None
    if not daftar and not login:
        return
    st.sidebar.markdown('<div class="sidebar-seksi">Recents</div>', unsafe_allow_html=True)
    if not daftar:  # user login yang belum pernah chat
        st.sidebar.markdown('<div class="sidebar-kosong">Belum ada percakapan tersimpan. Percakapan kamu akan muncul '
                            'di sini.</div>', unsafe_allow_html=True)
    for key, label, cid, pesan, konteks in daftar:
        if st.sidebar.button(label, key=key, use_container_width=True, type="secondary"):
            st.session_state.update(conversation_id=cid, riwayat_pesan=pesan, konteks=konteks)
            pindah("chat")


def _footer_guest():
    with st.sidebar.container(key="sidebar_foot"):
        st.markdown('<div class="sidebar-foot-teks">You’re chatting as a guest<br>Log in to keep your history</div>',
                    unsafe_allow_html=True)
        if st.button("Log In", key="sidebar_login", use_container_width=True, type="primary"):
            pindah("login")


# ---------- tampilan HP: di lebar <= 768px sidebar Streamlit menjadi panel melayang ----------
MOBILE_CSS = """
.topbar-hp { display:none; }
/* wadah elemennya dikeluarkan dari alur halaman, supaya tidak menambah jarak di layar lebar */
[data-testid="stElementContainer"]:has(.topbar-hp),
[data-testid="stElementContainer"]:has(iframe[height="0"]) { position:absolute; width:0; height:0; margin:0;
  overflow:hidden; }
@media (max-width: 768px) {
  /* bilah atas tetap: tombol garis tiga + logo, jadi tombolnya tidak lagi melayang di atas isi halaman */
  .topbar-hp { display:flex; align-items:center; gap:.4rem; position:fixed; top:0; left:0; right:0; height:60px;
    padding-left:58px; background:var(--cream); border-bottom:1px solid var(--border); z-index:999989; }
  [data-testid="stElementContainer"]:has(.topbar-hp) { overflow:visible; }
  .topbar-hp .brand-nama { font-size:1.2rem; }
  header[data-testid="stHeader"] { background:transparent !important; }
  /* isi halaman dimulai di bawah bilah atas, dengan tepi kiri-kanan yang sama di semua halaman */
  .stApp [data-testid="stMainBlockContainer"] { padding-top:5rem !important; padding-left:1rem !important;
    padding-right:1rem !important; }
  .halaman-judul { font-size:1.65rem !important; margin-bottom:1.1rem !important; }
  /* panel sidebar yang terbuka: baris atasnya kembaran bilah atas (tinggi, garis bawah, posisi tombol garis tiga
     & logo sama persis), jadi saat panel dibuka/ditutup tombol dan logo tidak melompat */
  section[data-testid="stSidebar"] .brand { height:60px; margin:0 -20px 1rem; padding:0 20px 0 58px;
    gap:.4rem; border-bottom:1px solid var(--border); box-sizing:border-box; }
  section[data-testid="stSidebar"] .brand .brand-nama { font-size:1.2rem; }
  section[data-testid="stSidebar"] .brand img { width:22px; }
  section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] { top:16px; left:-12px; right:auto; }
}
"""

# klik menu di HP: panel sidebar tetap terbuka & menutupi halaman tujuan -> ditutup otomatis
_SKRIP_TUTUP_SIDEBAR = """<script>
// pindah ke-__N__ (isi harus berbeda tiap kali: iframe yang isinya sama tidak dimuat ulang Streamlit)
(function () {
  const induk = window.parent;
  if (!induk || induk.innerWidth > 768) return;
  let coba = 0;
  const t = setInterval(function () {
    const panel = induk.document.querySelector('section[data-testid="stSidebar"]');
    const tombol = induk.document.querySelector('[data-testid="stSidebarCollapseButton"] button');
    if (panel && tombol && panel.getAttribute('aria-expanded') === 'true') { tombol.click(); clearInterval(t); }
    if (++coba > 30) clearInterval(t);
  }, 100);
})();
</script>"""


def _bilah_hp():
    """Bilah atas versi HP (logo di samping tombol garis tiga) + tutup sidebar setelah pindah halaman."""
    css(MOBILE_CSS)
    st.markdown(f'<div class="topbar-hp"><span class="brand-nama">Dew AI</span>{maskot(22)}</div>',
                unsafe_allow_html=True)
    if st.session_state.pop("tutup_sidebar_hp", False):
        st.session_state.tutup_sidebar_ke = st.session_state.get("tutup_sidebar_ke", 0) + 1
        components.html(_SKRIP_TUTUP_SIDEBAR.replace("__N__", str(st.session_state.tutup_sidebar_ke)), height=0)


def render():
    css(SIDEBAR_CSS)
    _bilah_hp()
    user = st.session_state.user

    st.sidebar.markdown(f'<div class="brand"><span class="brand-nama">Dew AI</span>{maskot(26)}</div>',
                        unsafe_allow_html=True)

    _nav_item(":material/chat_bubble:", "Chat", "chat")
    if user:
        _nav_item(":material/person:", "Profile", "profile")
    if user and user["role"] == "Admin":
        st.sidebar.markdown('<div class="nav-eyebrow">Admin</div>', unsafe_allow_html=True)
        _nav_item(":material/grid_view:", "Dashboard", "admin_dashboard")
        _nav_item(":material/shield:", "User Management", "admin_users")
        _nav_item(":material/deployed_code:", "Product Management", "admin_produk")

    _recents()

    if user is None:
        _footer_guest()