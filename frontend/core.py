import base64
import html
import os
from pathlib import Path
from urllib.parse import urlparse

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")


def backend_aman(url):
    """Email, password & token dikirim ke backend -- ke server luar WAJIB
    https; http polos hanya boleh ke komputer sendiri (pengembangan)."""
    bagian = urlparse(url)
    return bagian.scheme == "https" or (bagian.scheme == "http" and bagian.hostname in ("localhost", "127.0.0.1", "::1"))

ASSET_DIR = Path(__file__).parent / "assets"
DEWY = ASSET_DIR / "dewy_normal.png"
DEWY_THINKING = ASSET_DIR / "dewy_thinking.png"
BACKGROUND = ASSET_DIR / "background_gradient.png"
ICON = str(DEWY)

TIPE_KULIT = {"berminyak": "Berminyak", "kering": "Kering", "kombinasi": "Kombinasi",
              "sensitif": "Sensitif", "normal": "Normal"}
MASALAH_KULIT = {"jerawat": "Jerawat", "kusam": "Kusam", "hiperpigmentasi": "Hiperpigmentasi",
                 "penuaan": "Penuaan", "kemerahan_iritasi": "Kemerahan & Iritasi",
                 "dehidrasi": "Dehidrasi"}
# label bahasa Inggris untuk halaman admin & profile (nilai yang disimpan tetap kode di atas);
# label TIPE KULIT sengaja tetap bahasa Indonesia (keputusan user)
MASALAH_KULIT_EN = {"jerawat": "Acne", "kusam": "Dullness", "hiperpigmentasi": "Hyperpigmentation",
                    "penuaan": "Aging", "kemerahan_iritasi": "Redness & Irritation", "dehidrasi": "Dehydration"}
KATEGORI_EN = {"sunscreen": "Sunscreen", "facial_wash": "Facial wash", "moisturizer": "Moisturizer",
               "eksfoliator": "Exfoliator", "serum": "Serum", "toner": "Toner", "masker": "Mask",
               "acne_patch": "Acne patch", "essence": "Essence", "mist": "Face mist", "acne_gel": "Acne gel"}


@st.cache_data
def data_uri(path_str):
    b64 = base64.b64encode(Path(path_str).read_bytes()).decode()
    return f"data:image/png;base64,{b64}"


def maskot(size):
    return f'<img src="{data_uri(str(DEWY))}" width="{size}" alt="Dewy" style="display:block;height:auto;">'


def css(teks):
    st.markdown(f"<style>{teks}</style>", unsafe_allow_html=True)


# halaman berjudul (dashboard, user/product management, profile): isi langsung mulai
# di atas seperti halaman biasa, bukan turun jauh karena padding atas bawaan Streamlit
_HALAMAN_JUDUL_CSS = """
[data-testid="stMainBlockContainer"] { padding-top:3.2rem !important; }
.halaman-judul { margin-top:0 !important; }
"""


def judul_halaman(teks):
    css(_HALAMAN_JUDUL_CSS)
    st.markdown(f'<div class="halaman-judul">{teks}</div>', unsafe_allow_html=True)


def esc(teks):
    return html.escape(str(teks))


def state_awal():
    default = {
        "token": None, "user": None,
        "onboarding": {"tipe_kulit": "", "masalah_kulit": [], "budget": None, "tanpa_batas_budget": False},
        "onboarding_selesai": False,
        "conversation_id": None, "riwayat_pesan": [],
        "konteks": None,  # ingatan percakapan dari backend (profil yang diubah lewat chat, dst)
        "percakapan_lokal": {},  # riwayat guest, hanya di sesi ini
        "halaman": "chat",
        "pesan_login": None,  # alasan user diarahkan ke halaman login (mis. sesi berakhir)
    }
    for k, v in default.items():
        st.session_state.setdefault(k, v)


def pindah(halaman):
    st.session_state.halaman = halaman
    st.session_state.tutup_sidebar_hp = True  # di HP sidebar menutupi halaman -> tutup setelah pindah
    st.rerun()


_DATA_SESI = ("token", "user", "onboarding", "onboarding_selesai", "conversation_id", "riwayat_pesan", "konteks",
              "percakapan_lokal", "pesan_login")


def logout(pesan=None):
    """Bersihkan SEMUA data sesi di sisi aplikasi (token, profil kulit akun,
    percakapan) supaya tidak terlihat oleh orang berikutnya yang memakai
    browser ini, lalu ke halaman login. pesan: alasan kalau logout-nya bukan
    kemauan user (sesi berakhir, akun dinonaktifkan)."""
    for k in _DATA_SESI:
        st.session_state.pop(k, None)
    state_awal()
    st.session_state.update(halaman="login", pesan_login=pesan)


def keluar():
    """Tombol Logout: akhiri sesi di server dulu (token dicabut, tidak bisa
    dipakai lagi walau belum kedaluwarsa), baru bersihkan aplikasi."""
    if st.session_state.token:
        panggil("POST", "/logout", boleh_401_bisnis=True)
    logout()


def login_sukses(data):
    """Setelah login/daftar. Kalau sebelumnya chat sebagai TAMU (keputusan
    skenario 6.3): profil dari form tamu dipakai akun yang belum punya profil,
    dan percakapan tamu yang sedang terbuka disimpan ke riwayat akun lalu
    dilanjutkan. Profil akun yang sudah ada TIDAK ditimpa profil tamu."""
    ss = st.session_state
    tamu = ss.user is None
    profil_tamu = dict(ss.onboarding) if tamu and ss.onboarding_selesai else None
    chat_tamu = list(ss.riwayat_pesan) if tamu else []
    konteks_tamu = ss.konteks if chat_tamu else None

    user = data["user"]
    ss.update(token=data["access_token"], user=user, halaman="chat", konteks=None, conversation_id=None,
              riwayat_pesan=[], percakapan_lokal={}, pesan_login=None)
    masalah = [m for m in (user.get("masalah_kulit") or []) if m in MASALAH_KULIT]
    if user.get("tipe_kulit") and masalah:  # profil akun sudah lengkap -> lewati onboarding
        ss.onboarding = {
            "tipe_kulit": user["tipe_kulit"],
            "masalah_kulit": masalah,
            "budget": user.get("budget") or None,
            "tanpa_batas_budget": not user.get("budget"),
        }
        ss.onboarding_selesai = True
    elif profil_tamu and not panggil("PUT", "/profile", json=profil_tamu)[1]:
        ss.onboarding, ss.onboarding_selesai = profil_tamu, True
    else:
        ss.onboarding_selesai = False

    if chat_tamu:
        pesan = [{"sender": "user", "content": p["isi"]} if p["peran"] == "user" else
                 {"sender": "bot", "content": p["isi"], "data": {"recommendation": p.get("produk") or [],
                                                                 "grup": p.get("grup"),
                                                                 "perbandingan": p.get("perbandingan")}}
                 for p in chat_tamu]
        hasil, err, _ = panggil("POST", "/history/import", json={"messages": pesan, "konteks": konteks_tamu})
        if not err:
            ss.update(conversation_id=hasil["conversation_id"], riwayat_pesan=chat_tamu, konteks=konteks_tamu)


def ip_pengunjung():
    """IP asli pengunjung, diteruskan ke backend supaya rate limit register/login
    berlaku per pengunjung -- tanpa ini backend melihat SEMUA orang datang dari
    IP server frontend (satu jatah untuk semua).
    - Streamlit diakses langsung: alamat koneksinya.
    - Lewat reverse proxy di mesin yang sama (Caddy di server; st.context.ip_address
      None untuk koneksi localhost): entri TERAKHIR X-Forwarded-For, yaitu yang
      ditambahkan proxy itu sendiri -- entri buatan klien ada di depannya.
    - Pengembangan lokal / AppTest: None (backend memakai alamat koneksi biasa)."""
    try:
        ip = st.context.ip_address
        if ip:
            return ip
        # semua baris header digabung: .get() hanya memberi baris PERTAMA (bisa buatan klien)
        xff = ",".join(st.context.headers.get_all("X-Forwarded-For"))
    except Exception:  # di luar sesi browser
        return None
    return xff.rsplit(",", 1)[-1].strip() or None


def panggil(method, path, pakai_auth=True, boleh_401_bisnis=False, per_field=False, **kwargs):
    """401 = token invalid -> auto logout, kecuali boleh_401_bisnis=True
    (PUT /change-password balikin 401 kalau password lama salah).
    per_field=True: error validasi (400) dikembalikan sebagai dict
    {field: pesan} dari backend, supaya form bisa menandai tiap field."""
    token = st.session_state.token
    headers = {"Authorization": f"Bearer {token}"} if (pakai_auth and token) else {}
    # backend hanya memercayai header ini dari alamat di --forwarded-allow-ips
    # (default uvicorn: 127.0.0.1, yaitu frontend di mesin yang sama)
    if ip := ip_pengunjung():
        headers["X-Forwarded-For"] = ip
    try:
        resp = requests.request(method, f"{BACKEND_URL}{path}", headers=headers, timeout=90, **kwargs)
    except requests.exceptions.ConnectionError:
        st.error(f"Tidak bisa terhubung ke backend di {BACKEND_URL}. Pastikan `uvicorn backend.main:app` sudah jalan.")
        st.stop()
    if resp.status_code >= 400:
        try:
            isi = resp.json()
            pesan = isi.get("detail", resp.text)
            if per_field and isinstance(isi.get("errors"), dict):
                return None, isi["errors"], resp.status_code
        except ValueError:
            pesan = resp.text
        if resp.status_code == 401 and token and not boleh_401_bisnis:
            # sesi kedaluwarsa / akun dinonaktifkan di tengah pemakaian -> langsung
            # ke halaman login dengan penjelasan, bukan error/hang tanpa keterangan
            logout(pesan)
            st.rerun()
        return None, pesan, resp.status_code
    return (resp.json() if resp.text else {}), None, resp.status_code


def simpan_profil(data):
    # profil baru jadi titik awal percakapan berikutnya
    st.session_state.update(onboarding=data, konteks=None)
    if st.session_state.user:
        _, err, _ = panggil("PUT", "/profile", json=data)
        return err
    return None


def validasi_profil(data, en=False):
    """Aturan form onboarding: ketiga field wajib. return: list pesan error.
    en=True: pesan bahasa Inggris (halaman Profile)."""
    salah = []
    if data["tipe_kulit"] not in TIPE_KULIT:
        salah.append("Choose your skin type." if en else "Pilih tipe kulit kamu.")
    if not data["masalah_kulit"]:
        salah.append("Choose at least 1 skin concern." if en else "Pilih minimal 1 masalah kulit.")
    if not data["tanpa_batas_budget"]:
        if data["budget"] is None:
            salah.append("Enter a maximum budget (a number above 0), or tick \"No budget limit\"." if en else
                         "Isi budget maksimal (angka lebih dari 0), atau centang \"Tidak ada batas budget\".")
        elif data["budget"] <= 0:
            salah.append("Budget must be a number above 0." if en else "Budget harus angka lebih dari 0.")
    return salah


def form_kulit(key, label_submit, en=False):
    """Form profil kulit (onboarding & halaman Profile). en=True: teks bahasa
    Inggris (halaman Profile); nilai yang disimpan tetap kode baku."""
    ob = st.session_state.onboarding
    tipe_list = [""] + list(TIPE_KULIT)
    nama_tipe = TIPE_KULIT  # label tipe kulit tetap bahasa Indonesia (keputusan user)
    nama_masalah = MASALAH_KULIT_EN if en else MASALAH_KULIT
    label_tipe = {"": "Select your skin type" if en else "Masukkan tipe kulit anda", **nama_tipe}.get

    with st.form(key, border=False):
        with st.container(key=f"{key}_fld_tipe"):
            tipe = st.selectbox("Skin type" if en else "Tipe kulit", tipe_list,
                                index=tipe_list.index(ob["tipe_kulit"]) if ob["tipe_kulit"] in TIPE_KULIT else 0,
                                format_func=label_tipe)
        with st.container(key=f"{key}_fld_masalah"):
            masalah = st.multiselect("Main skin concerns" if en else "Masalah kulit utama", list(MASALAH_KULIT),
                                     default=[m for m in ob["masalah_kulit"] if m in MASALAH_KULIT],
                                     format_func=nama_masalah.get,
                                     placeholder="Select your skin concerns (you can pick more than one)" if en else
                                     "Masukkan masalah kulit anda (boleh lebih dari 1)")
        with st.container(key=f"{key}_fld_budget"):
            budget = st.number_input("Maximum budget (Rp)" if en else "Budget maksimal (Rp)", min_value=None,
                                     step=10_000, value=ob["budget"],
                                     placeholder="Enter your budget, e.g. 100000" if en else
                                     "Masukkan budget anda, mis. 100000")
            tanpa_batas = st.checkbox("No budget limit" if en else "Tidak ada batas budget",
                                      value=ob.get("tanpa_batas_budget", False))
        kirim = st.form_submit_button(label_submit, use_container_width=True, type="primary")
    if not kirim:
        return None
    data = {"tipe_kulit": tipe, "masalah_kulit": masalah,
            "budget": int(budget) if budget is not None else None, "tanpa_batas_budget": tanpa_batas}
    st.session_state.onboarding = data  # isian tetap ada walau ditolak, agar pengguna tinggal membetulkan
    salah = validasi_profil(data, en)
    if salah:
        st.error(("Your profile can't be saved yet:\n" if en else "Profil belum bisa disimpan:\n")
                 + "\n".join(f"- {s}" for s in salah))
        return None
    if tanpa_batas:
        data["budget"] = None
    return data


_SVG = ('<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{}</svg>')
IKON_USERS = _SVG.format('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
                         '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>')
IKON_SHIELD = _SVG.format('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>')
IKON_BOX = _SVG.format('<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4'
                       'a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.27 6.96 12 12.01l8.73-5.05"/>'
                       '<path d="M12 22.08V12"/>')
IKON_CHAT = _SVG.format('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>')

STAT_CSS = """
.stat-grid { display:grid; grid-template-columns:repeat(var(--kolom, 4), 1fr); gap:1rem; margin-bottom:1.8rem; }
@media (max-width:900px) { .stat-grid { grid-template-columns:repeat(2, 1fr); } }
/* HP: tetap 2 kolom tapi ringkas (bukan 4 kotak tinggi berderet); kotak ganjil terakhir selebar baris */
@media (max-width:640px) {
  .stat-grid { gap:.7rem; margin-bottom:1.3rem; }
  .stat-tile { padding:.85rem .9rem 1rem; border-radius:16px; }
  .stat-tile:last-child:nth-child(odd) { grid-column:1 / -1; }
  /* tinggi kepala kotak = 2 baris label, supaya angka sebaris walau label di sebelahnya hanya 1 baris */
  .stat-head { font-size:.85rem; gap:.5rem; line-height:1.25; min-height:2.5em; }
  .stat-ikon { width:1.6rem; height:1.6rem; flex-shrink:0; }
  .stat-num { font-size:1.7rem; margin-top:.55rem; }
  .stat-sub { font-size:.75rem; }
}
.stat-tile { background:var(--white); border:none; border-radius:20px; padding:1rem 1.1rem 1.2rem; }
.stat-head { display:flex; align-items:center; gap:.7rem; color:var(--ink-soft); font-size:1.05rem; }
.stat-ikon { width:1.9rem; height:1.9rem; border-radius:8px; display:flex; align-items:center; justify-content:center; }
.ikon-ungu { background:var(--lavender-soft); color:var(--lavender-ink); }
.ikon-hijau { background:var(--green-bg); color:var(--green-ink); }
.ikon-merah { background:var(--red-bg); color:var(--red-ink); }
.ikon-amber { background:var(--amber-bg); color:var(--amber-ink); }
.stat-num { font-size:2.2rem; font-weight:700; color:var(--black); margin-top:.7rem; line-height:1; }
.stat-sub { color:var(--ink-soft); font-size:.85rem; margin-top:.45rem; }
.kosong-tabel { color:var(--ink-soft); padding:1.4rem .2rem; }
"""


def angka(n):
    """1234 -> '1.234' (pemisah ribuan Indonesia)."""
    return f"{n:,}".replace(",", ".")


def stat_tiles(stats):
    """stats: [(label, angka, ikon, kelas_warna, keterangan_kecil_atau_None)]."""
    css(STAT_CSS)
    tiles = "".join(
        f'<div class="stat-tile"><div class="stat-head"><span class="stat-ikon {warna}">{ikon}</span>{esc(label)}</div>'
        f'<div class="stat-num">{angka(nilai)}</div>' + (f'<div class="stat-sub">{esc(sub)}</div>' if sub else "")
        + '</div>'
        for label, nilai, ikon, warna, sub in stats
    )
    st.markdown(f'<div class="stat-grid" style="--kolom:{len(stats)}">{tiles}</div>', unsafe_allow_html=True)


def ringkasan_admin():
    """Angka blok ringkasan (dihitung backend langsung dari database)."""
    data, err, _ = panggil("GET", "/admin/ringkasan")
    if err:
        st.error(err)
    return data


NAV_HALAMAN_CSS = """
.info-halaman { color:var(--ink-soft); font-size:.92rem; display:inline-block; margin-top:.45rem; }
.info-halaman b { color:var(--black); font-weight:600; }
/* nomor halaman sebagai pill di antara tombol « dan » */
.pill-halaman { display:flex; align-items:center; justify-content:center; height:2.5rem; padding:0 1rem;
  background:var(--white); border-radius:999px; font-size:.88rem; color:var(--ink-soft); white-space:nowrap; }
.pill-halaman b { color:var(--black); font-weight:700; margin:0 .15rem; }
/* tombol « » bulat, tanpa garis tepi */
[class*="st-key-hal_"] button {
  width:2.5rem; min-height:2.5rem; height:2.5rem; padding:0 !important; border:none !important;
  border-radius:50% !important; background:var(--white) !important; box-shadow:none !important;
}
[class*="st-key-hal_"] button:hover:not(:disabled) { background:var(--lavender-soft) !important; color:var(--lavender-ink) !important; }
/* halaman pertama/terakhir: tombol yang tidak bisa dipakai dibuat pudar */
[class*="st-key-hal_"] button:disabled { opacity:.35 !important; cursor:not-allowed !important; }
[class*="st-key-navhal_"] [data-testid="stHorizontalBlock"] { gap:.5rem; }
[class*="st-key-navhal_"] [data-testid="stMarkdown"], [class*="st-key-navhal_"] [data-testid="stMarkdownContainer"] {
  margin-bottom:0 !important;
}
/* HP: Streamlit menumpuk kolom jadi satu per baris -> keterangan di baris sendiri, « Page » di kanan */
@media (max-width:640px) {
  [class*="st-key-navhal_"] [data-testid="stHorizontalBlock"] { flex-wrap:wrap !important; justify-content:flex-end; }
  [class*="st-key-navhal_"] [data-testid="stColumn"] { width:auto !important; min-width:0 !important; flex:0 0 auto !important; }
  [class*="st-key-navhal_"] [data-testid="stColumn"]:first-child { flex:1 1 100% !important; }
}
"""


def navigasi_halaman(key, info, satuan):
    """'Showing 21–40 of 961 products' + « Page 2 / 49 ». satuan: kata benda
    jamak bahasa Inggris ('products', 'users'). key: kunci session_state
    nomor halaman tabel ini."""
    css(NAV_HALAMAN_CSS)
    total, hal, per, jumlah = info["total"], info["halaman"], info["per_halaman"], info["jumlah_halaman"]
    awal, akhir = ((hal - 1) * per + 1, min(hal * per, total)) if total else (0, 0)
    with st.container(key=f"navhal_{key}"):
        k1, k2, k3, k4 = st.columns([9, 0.55, 1.5, 0.55], vertical_alignment="center")
        k1.markdown(f'<span class="info-halaman">Showing <b>{angka(awal)}–{angka(akhir)}</b> of <b>{angka(total)}</b> '
                    f'{satuan}</span>', unsafe_allow_html=True)
        # on_click (bukan st.rerun) -- nomor halaman sudah berganti SEBELUM halaman digambar ulang
        k2.button("", key=f"{key}_sebelum", icon=":material/keyboard_double_arrow_left:", help="Previous page",
                  disabled=hal <= 1, on_click=st.session_state.__setitem__, args=(key, hal - 1))
        k3.markdown(f'<div class="pill-halaman">Page <b>{hal}</b> / {jumlah}</div>', unsafe_allow_html=True)
        k4.button("", key=f"{key}_berikut", icon=":material/keyboard_double_arrow_right:", help="Next page",
                  disabled=hal >= jumlah, on_click=st.session_state.__setitem__, args=(key, hal + 1))


def ambil_halaman(path, key, params, kunci_filter):
    """GET tabel admin per halaman. Nomor halaman kembali ke 1 kalau filter/
    pencarian berubah, dan disesuaikan kalau melebihi jumlah halaman (mis.
    setelah data berkurang). return: (data, err)."""
    ss = st.session_state
    if ss.get(f"{key}_filter") != kunci_filter:
        ss[f"{key}_filter"], ss[key] = kunci_filter, 1
    ss.setdefault(key, 1)
    data, err, _ = panggil("GET", path, params={**params, "halaman": ss[key]})
    if not err and data["halaman"] > data["jumlah_halaman"]:
        ss[key] = data["jumlah_halaman"]
        data, err, _ = panggil("GET", path, params={**params, "halaman": ss[key]})
    return data, err


def pill_role(u):
    kelas = "pill-admin" if u["role"] == "Admin" else "pill-user"
    return f'<span class="pill {kelas}">{u["role"]}</span>'


def pill_status(u):
    kelas, teks = ("pill-aktif", "Active") if u["is_active"] else ("pill-nonaktif", "Inactive")
    return f'<span class="pill {kelas}">{teks}</span>'
