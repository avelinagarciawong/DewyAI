"""admin_survei.py -- hasil kuesioner SUS dari mode survei: ringkasan skor, penyelesaian misi,
rata-rata tiap pernyataan, ringkasan penilaian kualitas jawaban, daftar jawaban, dan unduhan CSV
(format sama dengan yang dibaca models/evaluasi_sus.py)."""
import pandas as pd
import streamlit as st

from core import IKON_BOX, IKON_CHAT, IKON_SHIELD, IKON_USERS, css, esc, judul_halaman, panggil, stat_tiles
from halaman.survei import PERNYATAAN_KUALITAS, PERNYATAAN_SUS, TUGAS

LABEL_TUGAS_EN = {"profil": "Fill in skin profile", "rekomendasi": "Ask for recommendations",
                  "ulasan": "Ask about reviews", "banding": "Compare two products",
                  "ubah_profil": "Change skin condition via chat"}
# aspek tiap pernyataan kualitas jawaban (urutan sama dengan PERNYATAAN_KUALITAS) dan komponen yang dinilainya
ASPEK_KUALITAS_EN = [("Recommendation relevance", "CBF"), ("Message understanding", "NLU"),
                     ("Clarity of reasons", "LLM"), ("Usefulness of reviews", "RAG"), ("Trust in information", "overall")]

ADMIN_SURVEI_CSS = """
.survei-link { background:var(--white); border-radius:16px; padding:.9rem 1.1rem; margin-bottom:1.4rem;
  color:var(--ink-soft); font-size:.92rem; line-height:1.5; }
.survei-link code { background:var(--lavender-soft); color:var(--lavender-ink); padding:.1rem .45rem; border-radius:6px;
  word-break:break-all; }
.misi-baris { display:grid; grid-template-columns:minmax(0, 1fr) 3.2rem; gap:.25rem .8rem; align-items:center;
  margin-bottom:.7rem; font-size:.94rem; color:var(--ink); }
.misi-baris .persen { text-align:right; font-weight:600; color:var(--black); }
.misi-baris .bar { grid-column:1 / -1; height:7px; background:var(--cream-deep); border-radius:999px; overflow:hidden; }
.misi-baris .bar span { display:block; height:100%; background:var(--lavender-ink); border-radius:999px; }
.st-key-kartu_misi_admin, .st-key-kartu_pernyataan, .st-key-kartu_kualitas { background:var(--white); border-radius:20px;
  padding:1.1rem 1.2rem; }
.kualitas { display:grid; grid-template-columns:minmax(0, 1fr) 3.6rem 5.4rem; gap:.2rem .8rem; padding:.55rem 0;
  border-bottom:1px solid var(--border); font-size:.9rem; color:var(--ink); align-items:center; }
.kualitas:last-child { border-bottom:none; }
.kualitas .aspek { font-weight:600; color:var(--black); }
.kualitas .teks { color:var(--ink-muted); font-size:.82rem; line-height:1.4; }
.kualitas .nilai { text-align:right; font-weight:600; color:var(--black); }
.kualitas .setuju { text-align:right; color:var(--green-ink); font-size:.85rem; }
.kualitas.kepala { font-size:.78rem; color:var(--ink-muted); padding-top:0; }
.kualitas.kepala span { text-align:right; }
.pernyataan { display:grid; grid-template-columns:1.6rem minmax(0, 1fr) 2.6rem; gap:.6rem; padding:.45rem 0;
  border-bottom:1px solid var(--border); font-size:.9rem; color:var(--ink); }
.pernyataan:last-child { border-bottom:none; }
.pernyataan .no { color:var(--ink-muted); font-family:"IBM Plex Mono"; }
.pernyataan .nilai { text-align:right; font-weight:600; color:var(--black); }
.pernyataan .arah { color:var(--ink-muted); font-size:.78rem; }
"""


def _tautan_survei():
    h = st.context.headers
    host = h.get("host") or "localhost:8501"
    lokal = host.startswith(("localhost", "127.0.0.1"))
    proto = h.get("x-forwarded-proto") or ("http" if lokal else "https")
    return f"{proto}://{host}/?survei=1"


def _csv(respon):
    baris = []
    for r in respon:
        b = {"Timestamp": r["created_at"], "Perangkat": r["perangkat"], "Frekuensi skincare": r["frekuensi"]}
        b.update({f"SUS {i} - {teks}": r["jawaban"][i - 1] for i, teks in enumerate(PERNYATAAN_SUS, 1)})
        b.update({f"Kualitas {i} - {teks}": (r["kualitas"][i - 1] if r.get("kualitas") else "")
                  for i, teks in enumerate(PERNYATAAN_KUALITAS, 1)})
        b.update({"Tugas selesai": "; ".join(r["tugas_selesai"]), "Suka": r["suka"] or "",
                  "Perbaiki": r["perbaiki"] or "", "Skor SUS": r["skor"]})
        baris.append(b)
    return pd.DataFrame(baris).to_csv(index=False).encode("utf-8")


def render():
    css(ADMIN_SURVEI_CSS)
    judul_halaman("Survey Results")
    data, err, _ = panggil("GET", "/admin/survei")
    if err:
        st.error(err)
        return
    st.markdown(f'<div class="survei-link">Share this link with respondents. They try the chatbot with a mission '
                f'checklist, then fill in the SUS questionnaire:<br><code>{esc(_tautan_survei())}</code></div>',
                unsafe_allow_html=True)

    r, respon = data["ringkasan"], data["respon"]
    if not r["n"]:
        st.markdown('<div class="kosong-tabel">No survey responses yet.</div>', unsafe_allow_html=True)
        return

    stat_tiles([
        ("Responses", r["n"], IKON_USERS, "ikon-ungu", f"{sum(x['perangkat'] != 'Laptop' for x in respon)} on mobile"),
        ("Average SUS", round(r["rata"], 1), IKON_CHAT, "ikon-hijau",
         f"SD {r['sd']:.1f} · 95% CI {r['ik_bawah']:.1f}–{r['ik_atas']:.1f}"),
        ("Grade", r["grade"], IKON_SHIELD, "ikon-amber", f"{r['acceptability'].capitalize()} (Bangor et al.)"),
        ("Median", round(r["median"], 1), IKON_BOX, "ikon-merah", f"min {r['min']:.1f} · max {r['maks']:.1f}"),
    ])

    kiri, kanan = st.columns([1, 1.25], gap="large")
    with kiri:
        st.markdown('<div class="seksi-judul">Mission completion</div>', unsafe_allow_html=True)
        with st.container(key="kartu_misi_admin"):
            st.markdown("".join(
                f'<div class="misi-baris"><span>{esc(LABEL_TUGAS_EN[k])}</span>'
                f'<span class="persen">{data["penyelesaian_tugas"][k]:.0%}</span>'
                f'<span class="bar"><span style="width:{data["penyelesaian_tugas"][k]:.0%}"></span></span></div>'
                for k in TUGAS), unsafe_allow_html=True)
    with kanan:
        st.markdown('<div class="seksi-judul">Average per statement (1–5)</div>', unsafe_allow_html=True)
        with st.container(key="kartu_pernyataan"):
            st.markdown("".join(
                f'<div class="pernyataan"><span class="no">{i}</span><span>{esc(teks)}<br><span class="arah">'
                f'{"positive" if i % 2 else "negative"} statement</span></span>'
                f'<span class="nilai">{data["rata_pernyataan"][i - 1]:.2f}</span></div>'
                for i, teks in enumerate(PERNYATAAN_SUS, 1)), unsafe_allow_html=True)

    kualitas = data.get("kualitas") or []
    if kualitas and kualitas[0]["n"]:
        st.markdown(f'<div class="seksi-judul">Answer quality (1–5, separate from the SUS score; '
                    f'{kualitas[0]["n"]} responses)</div>', unsafe_allow_html=True)
        with st.container(key="kartu_kualitas"):
            st.markdown('<div class="kualitas kepala"><span style="text-align:left">Aspect</span><span>Average</span>'
                        '<span>Agree (4–5)</span></div>' + "".join(
                            f'<div class="kualitas"><span><span class="aspek">{esc(aspek)}</span> '
                            f'<span class="teks">({esc(komponen)})</span><br>'
                            f'<span class="teks">{esc(teks)}</span></span>'
                            f'<span class="nilai">{k["rata"]:.2f}</span>'
                            f'<span class="setuju">{k["setuju"]:.0%}</span></div>'
                            for (aspek, komponen), teks, k in zip(ASPEK_KUALITAS_EN, PERNYATAAN_KUALITAS, kualitas)),
                        unsafe_allow_html=True)

    st.markdown('<div class="seksi-judul">Responses</div>', unsafe_allow_html=True)
    tabel = pd.DataFrame([{
        "Time": x["created_at"], "Device": x["perangkat"], "Skincare use": x["frekuensi"], "SUS score": x["skor"],
        "Answer quality": round(sum(x["kualitas"]) / len(x["kualitas"]), 2) if x.get("kualitas") else None,
        "Missions done": f"{len(x['tugas_selesai'])}/{len(TUGAS)}", "Liked": x["suka"] or "",
        "To improve": x["perbaiki"] or ""} for x in respon])
    st.dataframe(tabel, hide_index=True, use_container_width=True)
    st.download_button("Download CSV", _csv(respon), file_name="sus_responden.csv", mime="text/csv",
                       key="unduh_survei", type="secondary")
