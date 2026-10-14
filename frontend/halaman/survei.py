"""survei.py -- mode survei SUS (?survei=1): kartu misi di halaman chat yang tercentang
otomatis dari respons /chat, lalu halaman penilaian (10 pernyataan SUS, 5 pernyataan kualitas jawaban, saran).
Jawaban dikirim anonim ke POST /survei (tanpa token)."""
import streamlit as st

from core import css, esc, judul_halaman, maskot, panggil, pindah

PERNYATAAN_SUS = [
    "Saya berpikir akan menggunakan sistem ini lagi.",
    "Saya merasa sistem ini rumit untuk digunakan.",
    "Saya merasa sistem ini mudah digunakan.",
    "Saya membutuhkan bantuan dari orang lain atau teknisi dalam menggunakan sistem ini.",
    "Saya merasa fitur-fitur sistem ini berjalan dengan semestinya.",
    "Saya merasa ada banyak hal yang tidak konsisten (tidak serasi) pada sistem ini.",
    "Saya merasa orang lain akan memahami cara menggunakan sistem ini dengan cepat.",
    "Saya merasa sistem ini membingungkan.",
    "Saya merasa tidak ada hambatan dalam menggunakan sistem ini.",
    "Saya perlu membiasakan diri terlebih dahulu sebelum menggunakan sistem ini.",
]
# penilaian kualitas jawaban (human evaluation), di luar SUS: satu pernyataan per komponen sistem --
# CBF, NLU, LLM, RAG, dan keseluruhan. Skor SUS tetap hanya dari 10 pernyataan baku di atas.
PERNYATAAN_KUALITAS = [
    "Produk yang direkomendasikan Dew AI sesuai dengan kondisi kulit dan kebutuhan saya.",
    "Dew AI memahami maksud pesan yang saya tulis dengan bahasa sehari-hari.",
    "Alasan yang diberikan untuk setiap produk mudah saya pahami.",
    "Kutipan ulasan pembeli yang ditampilkan membantu saya menilai produk.",
    "Saya percaya informasi produk yang diberikan Dew AI akurat.",
]
PILIHAN_PERANGKAT = ["HP", "Laptop", "Keduanya"]
PILIHAN_FREKUENSI = ["Setiap hari", "Beberapa kali seminggu", "Jarang", "Tidak pernah"]

# kode misi -> (label, saran langkah). Kode sama dengan TUGAS_SURVEI di backend.
TUGAS = {
    "profil": ("Isi profil kulit", "Isi profil kulitmu di awal."),
    "rekomendasi": ("Minta rekomendasi", "Minta rekomendasi produk, misalnya sunscreen atau toner."),
    "ulasan": ("Tanya ulasan", "Tanyakan ulasan salah satu produk dari hasil rekomendasi."),
    "banding": ("Bandingkan produk", "Minta perbandingan dua produk dari hasil rekomendasi."),
    "ubah_profil": ("Ubah kondisi kulit", "Ceritakan kondisi kulit yang berbeda, lalu minta rekomendasi lagi."),
}

SURVEI_CSS = """
.st-key-misi_survei, .st-key-ajakan_survei { background:var(--white); border:1px solid var(--border);
  border-radius:18px; padding:1rem 1.1rem .9rem; margin-bottom:1rem; }
.misi-kepala { display:flex; justify-content:space-between; align-items:center; gap:.5rem;
  font-weight:600; color:var(--black); font-size:1rem; }
.misi-angka { font-family:"IBM Plex Mono"; font-size:.82rem; color:var(--lavender-ink);
  background:var(--lavender-soft); padding:.15rem .65rem; border-radius:999px; white-space:nowrap; }
.misi-bar { height:6px; background:var(--cream-deep); border-radius:999px; margin:.65rem 0 .75rem; overflow:hidden; }
.misi-bar > span { display:block; height:100%; background:var(--lavender-ink); border-radius:999px; }
.misi-daftar { display:flex; flex-wrap:wrap; gap:.4rem; }
.misi-chip { font-size:.82rem; padding:.3rem .7rem; border-radius:999px; background:var(--cream); color:var(--ink-soft); }
.misi-chip.selesai { background:var(--green-bg); color:var(--green-ink); }
.misi-saran { font-size:.88rem; color:var(--ink-soft); margin-top:.7rem; line-height:1.45; }
.misi-saran b { color:var(--black); font-weight:600; }
.ajakan-teks { font-weight:600; color:var(--black); margin-bottom:.55rem; }
/* kartu misi menempel di bawah bilah atas selama percakapan digulir, supaya progres tetap terlihat.
   Yang dibuat sticky pembungkusnya (stLayoutWrapper): induknya memuat seluruh percakapan, sedangkan
   kartunya sendiri hanya dibungkus wadah seukuran dirinya sehingga tidak bisa menempel. Latar krem di
   atas kartu menutupi pesan yang tergulir di belakangnya. */
[data-testid="stLayoutWrapper"]:has(> .st-key-misi_survei) { position:sticky; top:60px; z-index:50;
  background:var(--cream); padding-top:.5rem; }
.st-key-misi_survei { box-shadow:0 8px 18px -12px rgba(60,50,40,.35); }
/* dengan kartu misi di atasnya, sapaan awal chat tidak perlu setinggi 45% layar -- di HP
   keduanya harus muat tanpa halaman tergulir (bagian atas kartu tertutup bilah atas) */
.hero { min-height:0 !important; padding:1.4rem 0 .4rem; }
[class*="st-key-survei_"] button[kind="primary"] { min-height:2.6rem; }
[class*="st-key-survei_lewati"] button p { font-size:.85rem; color:var(--ink-soft); text-decoration:underline; }
/* HP: kartu yang menempel dibuat ringkas (chip misi satu baris yang bisa digeser) agar tidak memakan layar */
@media (max-width: 640px) {
  .st-key-misi_survei { padding:.6rem .8rem .45rem !important; gap:.3rem !important; }
  /* markdown Streamlit punya margin bawah -1rem (biasanya tertutup gap 1rem); dengan gap .3rem teks
     "Berikutnya" yang dua baris jadi menimpa tautan di bawahnya */
  .st-key-misi_survei [data-testid="stMarkdownContainer"] { margin-bottom:0 !important; }
  .misi-kepala { font-size:.92rem; }
  .misi-bar { margin:.4rem 0 .45rem; }
  .misi-daftar { flex-wrap:nowrap; overflow-x:auto; scrollbar-width:none; }
  .misi-daftar::-webkit-scrollbar { display:none; }
  .misi-chip { font-size:.72rem; padding:.2rem .55rem; white-space:nowrap; flex-shrink:0; }
  .misi-saran { font-size:.8rem; margin-top:.4rem; line-height:1.35; }
  [class*="st-key-survei_lewati"] button { min-height:0 !important; padding:0 !important; }
  [class*="st-key-survei_lewati"] button p { font-size:.75rem; }
}

/* halaman penilaian */
.survei-sub { color:var(--ink-soft); font-size:.98rem; line-height:1.55; margin:-.4rem 0 1.2rem; }
.survei-skala { background:var(--lavender-soft); color:var(--lavender-ink); border-radius:12px;
  padding:.65rem .9rem; font-size:.9rem; margin:.4rem 0 .9rem; }
[class*="st-key-sv_"] { background:var(--white); border-radius:14px; padding:.75rem 1rem .6rem;
  width:100% !important; box-sizing:border-box; }
[class*="st-key-sv_"] [data-testid="stWidgetLabel"] p { font-weight:500; color:var(--black); line-height:1.45; }
.survei-terima { background:var(--white); border-radius:20px; padding:2rem 1.4rem; text-align:center; }
.survei-terima img { margin:0 auto .8rem; }
.survei-terima-judul { font-family:"Playfair Display", serif; font-weight:700; font-size:1.5rem; color:var(--black); }
.survei-terima-sub { color:var(--ink-soft); margin-top:.4rem; line-height:1.5; }
"""


def _semua_selesai():
    return len(st.session_state.survei_tugas) == len(TUGAS)


def catat_respons(data):
    """Respons /chat -> misi yang selesai (dipanggil halaman chat setelah setiap jawaban bot)."""
    ss = st.session_state
    selesai = set(ss.survei_tugas)
    jenis = set((data.get("tipe") or "").split("+"))
    if "rekomendasi" in jenis and data.get("recommendation"):
        selesai.add("rekomendasi")
    if "ulasan" in jenis:
        selesai.add("ulasan")
    # tabel perbandingan >= 2 produk: dari "bandingkan nomor 1 sama 2" (perbandingan) maupun
    # "nomor 1 dan 2 bagusan mana?" (pilih_satu, tabel + satu pemenang)
    if len((data.get("perbandingan") or {}).get("produk") or []) >= 2:
        selesai.add("banding")
    profil = (data.get("konteks") or {}).get("profil") or {}
    ob = ss.onboarding or {}
    if profil and ((profil.get("tipe_kulit") or "") != (ob.get("tipe_kulit") or "")
                   or set(profil.get("masalah_kulit") or []) != set(ob.get("masalah_kulit") or [])):
        selesai.add("ubah_profil")
    baru = [k for k in TUGAS if k in selesai and k not in ss.survei_tugas]
    ss.survei_tugas = [k for k in TUGAS if k in selesai]
    if baru:
        sisa = len(TUGAS) - len(ss.survei_tugas)
        ss.survei_toast = (f"Misi selesai: {TUGAS[baru[-1]][0]}. " +
                           (f"Tinggal {sisa} lagi." if sisa else "Semua misi selesai, yuk beri penilaian!"))


def kartu_misi():
    """Kartu progres misi di atas halaman chat."""
    css(SURVEI_CSS)
    ss = st.session_state
    if ss.onboarding_selesai and "profil" not in ss.survei_tugas:
        ss.survei_tugas = [k for k in TUGAS if k in set(ss.survei_tugas) | {"profil"}]
    if ss.survei_toast:
        st.toast(ss.survei_toast, icon=":material/task_alt:")
        ss.survei_toast = None
    jumlah = len(ss.survei_tugas)
    chip = "".join(f'<span class="misi-chip{" selesai" if k in ss.survei_tugas else ""}">'
                   f'{"✓ " if k in ss.survei_tugas else ""}{esc(label)}</span>' for k, (label, _) in TUGAS.items())
    berikut = next((saran for k, (_, saran) in TUGAS.items() if k not in ss.survei_tugas), None)
    saran = (f'<div class="misi-saran"><b>Berikutnya:</b> {esc(berikut)}</div>' if berikut else
             '<div class="misi-saran">Semua misi selesai. Terima kasih sudah mencoba!</div>')
    with st.container(key="misi_survei"):
        st.markdown(f'<div class="misi-kepala"><span>Misi uji coba</span><span class="misi-angka">{jumlah}/{len(TUGAS)}'
                    f'</span></div><div class="misi-bar"><span style="width:{jumlah / len(TUGAS):.0%}"></span></div>'
                    f'<div class="misi-daftar">{chip}</div>{saran}', unsafe_allow_html=True)
        if _semua_selesai():
            if st.button("Beri penilaian", key="survei_nilai", type="primary", use_container_width=True):
                pindah("survei")
        elif st.button("Ada misi yang tidak berhasil? Isi penilaian sekarang", key="survei_lewati", type="tertiary"):
            pindah("survei")


def ajakan_penilaian():
    """Ajakan di bawah percakapan setelah semua misi selesai (kartu misi di atas mungkin sudah
    tergulir ke luar layar)."""
    if not _semua_selesai():
        return
    with st.container(key="ajakan_survei"):
        st.markdown('<div class="ajakan-teks">Semua misi selesai! Sekarang beri penilaianmu, ya.</div>',
                    unsafe_allow_html=True)
        if st.button("Beri penilaian", key="survei_nilai_bawah", type="primary", use_container_width=True):
            pindah("survei")


def render():
    css(SURVEI_CSS)
    ss = st.session_state
    judul_halaman("Penilaian Dew AI")
    if ss.survei_terkirim:
        st.markdown(f'<div class="survei-terima">{maskot(56)}<div class="survei-terima-judul">Terima kasih!</div>'
                    '<div class="survei-terima-sub">Penilaianmu sudah tersimpan. Kamu tetap bisa lanjut '
                    'ngobrol dengan Dew AI.</div></div>', unsafe_allow_html=True)
        if st.button("Kembali ke chat", key="survei_kembali", type="primary", use_container_width=True):
            pindah("chat")
        return

    st.markdown('<div class="survei-sub">Jawab sesuai pengalamanmu barusan memakai Dew AI. Jawaban anonim dan '
                'hanya dipakai untuk penelitian.</div>', unsafe_allow_html=True)
    if st.button("← Kembali ke chat", key="survei_ke_chat", type="tertiary"):
        pindah("chat")

    with st.form("form_survei", border=False):
        perangkat = st.radio("Perangkat yang kamu pakai untuk mencoba", PILIHAN_PERANGKAT, index=None,
                             horizontal=True, key="sv_perangkat")
        frekuensi = st.radio("Seberapa sering kamu memakai skincare?", PILIHAN_FREKUENSI, index=None, key="sv_frekuensi")
        st.markdown('<div class="survei-skala">Untuk pernyataan berikut, pilih <b>1 = Sangat tidak setuju</b> sampai '
                    '<b>5 = Sangat setuju</b>.</div>', unsafe_allow_html=True)
        # "**1.**" (bukan "1.") supaya tidak dibaca markdown sebagai daftar bernomor yang angkanya hilang
        jawaban = [st.radio(f"**{i}.** {teks}", [1, 2, 3, 4, 5], index=None, horizontal=True, key=f"sv_sus_{i}")
                   for i, teks in enumerate(PERNYATAAN_SUS, 1)]
        st.markdown('<div class="survei-skala">Bagian berikut tentang <b>kualitas jawaban</b> Dew AI, dengan skala yang '
                    'sama: <b>1 = Sangat tidak setuju</b> sampai <b>5 = Sangat setuju</b>.</div>', unsafe_allow_html=True)
        kualitas = [st.radio(f"**{i}.** {teks}", [1, 2, 3, 4, 5], index=None, horizontal=True,
                             key=f"sv_kualitas_{i - len(PERNYATAAN_SUS)}")
                    for i, teks in enumerate(PERNYATAAN_KUALITAS, len(PERNYATAAN_SUS) + 1)]
        suka = st.text_area("Apa yang paling kamu suka dari Dew AI? (opsional)", max_chars=1000, key="sv_suka")
        perbaiki = st.text_area("Apa yang perlu diperbaiki? (opsional)", max_chars=1000, key="sv_perbaiki")
        kirim = st.form_submit_button("Kirim penilaian", type="primary", use_container_width=True)

    if not kirim:
        return
    belum = ([] if perangkat else ["perangkat"]) + ([] if frekuensi else ["frekuensi memakai skincare"]) + \
        [f"pernyataan {i}" for i, j in enumerate(jawaban + kualitas, 1) if j is None]
    if belum:
        st.error("Masih ada yang belum dijawab: " + ", ".join(belum) + ".")
        return
    _, err, _ = panggil("POST", "/survei", pakai_auth=False, json={
        "perangkat": perangkat, "frekuensi": frekuensi, "jawaban": jawaban, "kualitas": kualitas,
        "tugas_selesai": ss.survei_tugas, "suka": suka, "perbaiki": perbaiki})
    if err:
        st.error(err)
        return
    ss.survei_terkirim = True
    st.rerun()
