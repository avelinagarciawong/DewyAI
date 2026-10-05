"""chat.py -- halaman chat utama."""
import uuid

import streamlit as st

from core import DEWY_THINKING, ICON, css, esc, maskot, panggil

CHAT_CSS = """
/* area input di bawah */
[data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] { background:var(--cream); }
div[data-testid="stChatInput"] {
  background:var(--white); border:1px solid var(--border) !important; border-radius:999px;
  padding:.3rem .35rem .3rem .9rem; box-shadow:0 6px 24px -16px rgba(60,50,40,.25) !important;
  outline:none !important;
}
div[data-testid="stChatInput"]:focus-within {
  border-color:var(--black) !important; box-shadow:0 6px 24px -16px rgba(60,50,40,.25) !important; outline:none !important;
}
div[data-testid="stChatInput"] > div,
div[data-testid="stChatInput"] [data-baseweb="textarea"],
div[data-testid="stChatInput"] [data-baseweb="base-input"] {
  background:transparent !important; border:none !important; outline:none !important; box-shadow:none !important;
}
div[data-testid="stChatInput"] textarea {
  font-size:.95rem; color:var(--ink); background:transparent !important; outline:none !important; box-shadow:none !important;
}
div[data-testid="stChatInput"] textarea::placeholder { color:var(--ink-muted); }
[data-testid="stChatInputSubmitButton"] {
  background:var(--black) !important; border-radius:50% !important; width:2.2rem; height:2.2rem;
}
[data-testid="stChatInputSubmitButton"] svg { fill:var(--white); color:var(--white); width:1rem; height:1rem; }
[data-testid="stChatInputSubmitButton"]:disabled { display:none !important; }

/* sapaan saat chat kosong */
.hero { min-height:45vh; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; }
.hero-title { font-family:"Playfair Display", serif; font-size:1.5rem; font-weight:700; color:var(--black); margin-top:.7rem; }
.hero-sub { color:var(--ink-soft); margin-top:.4rem; font-size:.92rem; }

/* bubble */
div[data-testid="stChatMessage"] { background:transparent !important; gap:1rem; }
div[data-testid="stChatMessageAvatarUser"] { display:none; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) { justify-content:flex-end; }
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] {
  flex:0 1 auto; max-width:60%; background:var(--cream-deep); border-radius:22px; padding:.85rem 1.2rem;
  color:var(--black) !important;
  /* Streamlit memberi konten pesan margin:0 auto -> bubble user jadi di tengah; dipaksa rata kanan,
     sejajar tepi kanan kolom input */
  margin:0 0 0 auto !important;
}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] p {
  color:var(--black) !important;
}
div[data-testid="stChatMessage"] div[data-testid="stChatMessageContent"] p { color:var(--ink); }
div[data-testid="stChatMessage"] img[alt$="avatar"] {
  width:2.8rem !important; height:2.8rem !important; background:var(--white); border-radius:50%;
  padding:.4rem; object-fit:contain;
}
.loading-teks { font-style:italic; color:var(--ink); padding-top:.6rem; }

/* kartu produk -- mulai sejajar tepi kiri avatar (bukan menjorok mengikuti teks), seperti desain */
.produk-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(210px, 250px)); gap:1rem; margin:1rem 0 .4rem; }
div[data-testid="stChatMessage"] .produk-grid,
div[data-testid="stChatMessage"] .grup-judul { margin-left:calc(-2.8rem - 1rem); }
.produk-card { background:var(--white); border:1px solid var(--border); border-radius:18px; padding:.75rem; }
.produk-nama { font-weight:600; font-size:1.02rem; color:var(--black); margin:0 0 .2rem; }
.produk-meta { font-family:"IBM Plex Mono"; font-size:.78rem; color:var(--ink-soft); }
.produk-meta b { color:var(--black); }
.produk-atas { display:flex; align-items:center; flex-wrap:wrap; gap:.3rem .4rem; margin-bottom:.45rem; }
.produk-atas span { white-space:nowrap; }
.produk-nomor { display:inline-flex; align-items:center; justify-content:center; width:1.55rem; height:1.55rem;
  border-radius:50%; background:var(--black); color:var(--white); font-size:.75rem; font-weight:700; flex-shrink:0; }
.produk-kategori { display:inline-block; background:var(--lavender-soft); color:var(--lavender-ink); border-radius:999px;
  padding:.1rem .55rem; font-size:.72rem; font-weight:600; }
/* riwayat lama: produk yang sekarang dinonaktifkan admin */
.produk-card.tidak-tersedia { background:var(--cream); border-style:dashed; }
.produk-card.tidak-tersedia .produk-nama { color:var(--ink-soft); }
.produk-tidak-tersedia { display:inline-block; background:var(--red-bg); color:var(--red-ink); border-radius:999px;
  padding:.1rem .55rem; font-size:.72rem; font-weight:600; }

/* tabel perbandingan */
.banding-wrap { overflow-x:auto; margin:.8rem 0 .4rem; }
.banding { border-collapse:separate; border-spacing:0; background:var(--white); border:1px solid var(--border);
  border-radius:14px; overflow:hidden; font-size:.85rem; min-width:420px; }
.banding th, .banding td { padding:.6rem .8rem; text-align:left; vertical-align:top; border-bottom:1px solid var(--border);
  color:var(--ink); min-width:150px; }
.banding thead th { background:var(--lavender-bg); color:var(--black); font-weight:600; }
.banding th.atribut { background:var(--cream); color:var(--ink-soft); font-weight:500; min-width:110px; }
.banding td.terbaik { color:var(--black); font-weight:700; }
.banding td.terbaik::after { content:" ✓"; color:var(--green-ink); }
.banding tr:last-child th, .banding tr:last-child td { border-bottom:none; }
.produk-alasan { font-size:.85rem; color:var(--ink-soft); line-height:1.45; margin-top:.3rem; }
.produk-luar-budget { display:inline-block; background:var(--amber-bg); color:var(--amber-ink); border-radius:999px;
  padding:.1rem .55rem; font-size:.72rem; font-weight:600; }
.produk-catatan { font-size:.78rem; font-style:italic; color:var(--ink-muted); line-height:1.4; margin-top:.45rem;
  border-top:1px dashed var(--border); padding-top:.4rem; }
.grup-judul { font-weight:600; font-size:1rem; color:var(--black); margin:1rem 0 -.2rem; }

/* HP: kartu produk selebar layar (tetap sejajar tepi kiri avatar), bubble user boleh lebih lebar */
@media (max-width: 640px) {
  .produk-grid { grid-template-columns:1fr; }
  div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] {
    max-width:85%;
  }
  div[data-testid="stChatMessage"] { gap:.7rem; }
}
"""

# badge guest ditempel tepat di atas kolom input
GUEST_CSS = """
[data-testid="stBottomBlockContainer"]::before {
  content:"Chatting as a guest — your history won't be saved"; display:block; width:fit-content;
  margin:0 auto .8rem; padding:.35rem 1rem; border:1px solid var(--border); border-radius:999px;
  font-family:"IBM Plex Mono"; font-size:.75rem; color:var(--ink-muted); letter-spacing:.02em;
}
/* HP: versi pendek supaya tetap satu baris */
@media (max-width: 640px) {
  [data-testid="stBottomBlockContainer"]::before {
    content:"Guest mode — history won't be saved"; font-size:.7rem; white-space:nowrap; margin-bottom:.6rem;
  }
}
"""


def _rupiah(n):
    return f"Rp {n:,.0f}".replace(",", ".")


def _produk_grid(daftar):
    if not daftar:
        return
    kartu = []
    for p in daftar:
        meta = [esc(p["brand"])] if p.get("brand") else []
        if p.get("harga") is not None:
            meta.append(f'<b>{_rupiah(p["harga"])}</b>')
        else:
            meta.append("harga di data tidak wajar" if p.get("harga_tidak_wajar") else "harga tidak ada di data")
        if p.get("rating") is not None:
            meta.append(f'★ {p["rating"]:.1f}')
        if not p.get("jml_ulasan"):
            meta.append("belum ada ulasan")
        nomor = f'<span class="produk-nomor">{p["nomor"]}</span>' if p.get("nomor") else ""
        label = f'<span class="produk-kategori">{esc(p["kategori_label"])}</span>' if p.get("kategori_label") else ""
        luar = '<span class="produk-luar-budget">Di luar budget</span>' if p.get("di_luar_budget") else ""
        catatan = "".join(f'<div class="produk-catatan">{esc(c)}</div>' for c in p.get("catatan") or [])
        # riwayat lama: kartu tetap tampil sebagai catatan, tapi produknya sudah dinonaktifkan admin
        tidak = p.get("tidak_tersedia")
        if tidak:
            luar += '<span class="produk-tidak-tersedia">Sudah tidak tersedia</span>'
            catatan += ('<div class="produk-catatan">Produk ini sudah tidak tersedia di katalog, jadi tidak '
                        'direkomendasikan lagi.</div>')
        kartu.append(
            f'<div class="produk-card{" tidak-tersedia" if tidak else ""}"><div class="produk-atas">{nomor}{label}{luar}</div>'
            f'<div class="produk-nama">{esc(p["produk"])}</div>'
            f'<div class="produk-meta">{" &middot; ".join(meta)}</div>'
            f'<div class="produk-alasan">{esc(p["alasan"])}</div>{catatan}</div>'
        )
    st.markdown(f'<div class="produk-grid">{"".join(kartu)}</div>', unsafe_allow_html=True)


def _tabel_banding(tabel):
    kepala = "".join(f"<th>{esc(n)}</th>" for n in tabel["produk"])
    baris = []
    for b in tabel["baris"]:
        sel = "".join(f'<td class="{"terbaik" if i == b["terbaik"] else ""}">{esc(v)}</td>'
                      for i, v in enumerate(b["nilai"]))
        baris.append(f'<tr><th class="atribut">{esc(b["atribut"])}</th>{sel}</tr>')
    st.markdown(f'<div class="banding-wrap"><table class="banding"><thead><tr><th class="atribut"></th>{kepala}'
                f'</tr></thead><tbody>{"".join(baris)}</tbody></table></div>', unsafe_allow_html=True)


def _tampil_pesan(pesan):
    if pesan["peran"] == "assistant":
        with st.chat_message("assistant", avatar=ICON):
            if pesan.get("perbandingan"):
                _tabel_banding(pesan["perbandingan"])
            st.write(pesan["isi"])
            if pesan.get("grup"):
                for g in pesan["grup"]:
                    st.markdown(f'<div class="grup-judul">{esc(g["judul"])}</div>', unsafe_allow_html=True)
                    _produk_grid(g["produk"])
            else:
                _produk_grid(pesan.get("produk", []))
    else:
        with st.chat_message("user"):
            st.write(pesan["isi"])


def _simpan_lokal_guest(teks):
    ss = st.session_state
    cid = ss.conversation_id
    if cid is None:
        cid = ss.conversation_id = str(uuid.uuid4())
        ss.percakapan_lokal[cid] = {"judul": teks[:42] + ("..." if len(teks) > 42 else ""), "pesan": []}
    ss.percakapan_lokal[cid]["pesan"] = list(ss.riwayat_pesan)
    ss.percakapan_lokal[cid]["konteks"] = ss.konteks


def render():
    css(CHAT_CSS)
    ss = st.session_state
    if not ss.user:
        css(GUEST_CSS)

    # dibaca duluan supaya pesan baru langsung ikut tampil (hero tidak muncul lagi)
    teks = st.chat_input("Tanya apa aja soal skincare kamu...")
    if teks:
        ss.riwayat_pesan.append({"peran": "user", "isi": teks})

    if not ss.riwayat_pesan:
        st.markdown(f'<div class="hero">{maskot(42)}<div class="hero-title">Ada yang bisa dibantu?</div>'
                    '<div class="hero-sub">Ceritain kondisi kulit atau keluhan kamu, nanti dicariin rekomendasi produknya.</div></div>',
                    unsafe_allow_html=True)

    for pesan in ss.riwayat_pesan:
        _tampil_pesan(pesan)

    if not teks:
        return

    with st.chat_message("assistant", avatar=str(DEWY_THINKING)):
        st.markdown('<div class="loading-teks">Mencari &amp; menyusun rekomendasi...</div>', unsafe_allow_html=True)
        body = {"message": teks, "onboarding": ss.onboarding, "konteks": ss.konteks}
        if ss.user and ss.conversation_id:
            body["conversation_id"] = ss.conversation_id
        data, err, _ = panggil("POST", "/chat", json=body)

    if err:
        ss.riwayat_pesan.pop()
        st.error(err)
        return

    ss.konteks = data.get("konteks")
    if ss.user and data.get("conversation_id"):
        ss.conversation_id = data["conversation_id"]
    ss.riwayat_pesan.append({"peran": "assistant", "isi": data["explanation"], "produk": data["recommendation"],
                             "grup": data.get("grup"), "perbandingan": data.get("perbandingan")})
    if not ss.user:
        _simpan_lokal_guest(teks)
    st.rerun()