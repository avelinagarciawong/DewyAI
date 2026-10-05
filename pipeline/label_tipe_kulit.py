"""
label_tipe_kulit.py

Melabeli setiap produk di clean_produk_full.csv dengan tipe_kulit_cocok
(multi-label: bisa lebih dari satu dari 5 kategori: berminyak, kering,
kombinasi, sensitif, normal), berdasarkan bahan aktif yang terdeteksi di
teks produk (nama, deskripsi, komposisi, ingredient, zat aktif).

Landasan objektivitas: data/referensi_tipe_kulit.csv -- 68 bahan dengan
sitasi dermatologi <=5 tahun (lihat kolom sumber_sitasi & dasar_pemetaan).
(56 bahan awal + 12 bahan tambahan hasil review frekuensi kemunculan bahan
di deskripsi 999 produk, ditambahkan Agustus 2026.)

ATURAN VOTING (sudah disepakati sebelumnya):
- 1 bahan yang cocok = 1 suara untuk tiap tipe kulit di manfaat_tipe_kulit-nya.
- Satu tipe kulit resmi jadi label produk HANYA kalau didukung >= 2 bahan
  berbeda (mencegah 1 bahan minor "membajak" label produk).
- Bila hanya ADA 1 bahan yang terdeteksi di seluruh produk (bukan 1 suara per
  tipe, melainkan 1 bahan total), label yang dihasilkan ditandai
  status "sinyal_rendah" -- tetap disimpan tapi confidence rendah.
- Kalau 0 bahan terdeteksi sama sekali, produk ditandai status
  "perlu_llm_fallback" -- ini yang nanti diproses LLM baca deskripsi bebas,
  BUKAN dilabeli asal kosong. (sesuai metodologi hybrid di proposal:
  keyword matching -> LLM fallback -> verifikasi manual 150-300 sampel)
- kombinasi tidak berasal dari bahan manapun secara langsung. Produk yang
  lolos threshold untuk berminyak DAN kering sekaligus otomatis dapat
  tambahan label kombinasi (area berminyak + area kering di wajah yang sama).
- risiko_tipe_kulit (fragrance, alcohol, paraben, propylene glycol, SPF,
  retinol) TIDAK PERNAH dihitung sebagai suara mendukung -- itu bahan yang
  literaturnya bilang "hati-hati untuk kulit sensitif", bukan "cocok untuk
  kulit sensitif". Kalau produk mengandung bahan ini, dicatat terpisah di
  kolom catatan_risiko_sensitif sebagai info tambahan, bukan alasan exclude
  atau include otomatis.
"""
import re
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data")
THRESHOLD = 2
KATEGORI = ["berminyak", "kering", "sensitif", "normal"]  # kombinasi diturunkan belakangan
MASALAH_KATEGORI = ["jerawat", "kusam", "hiperpigmentasi", "penuaan", "kemerahan_iritasi", "dehidrasi"]


def load_referensi():
    ref = pd.read_csv(DATA_DIR / "referensi_tipe_kulit.csv")
    bahan_list = []
    def to_str(v):
        return "" if pd.isna(v) else str(v)

    for _, row in ref.iterrows():
        aliases = [a.strip() for a in to_str(row["alias_deteksi"]).split("|") if a.strip()]
        manfaat = [m.strip() for m in to_str(row["manfaat_tipe_kulit"]).split("|") if m.strip()]
        risiko = [r.strip() for r in to_str(row["risiko_tipe_kulit"]).split("|") if r.strip()]
        masalah = [m.strip() for m in to_str(row.get("masalah_kulit_terkait", "")).split("|") if m.strip()]
        patterns = [re.compile(rf"\b{re.escape(a)}\b") for a in aliases]
        bahan_list.append({
            "bahan": row["bahan"],
            "patterns": patterns,
            "manfaat": manfaat,
            "risiko": risiko,
            "masalah": masalah,
        })
    return bahan_list


def build_blob(row) -> str:
    parts = [
        row.get("nama_produk", ""),
        row.get("deskripsi", ""),
        row.get("raw_komposisi", ""),
        row.get("raw_ingredient_komposisi", ""),
        row.get("raw_zat_aktif", ""),
    ]
    blob = " ".join(str(p) for p in parts if pd.notna(p))
    return blob.lower()


def label_produk(blob: str, bahan_list):
    matched = []  # nama bahan yang terdeteksi
    votes = {k: 0 for k in KATEGORI}
    voters = {k: [] for k in KATEGORI}      # bahan mana yang menyumbang suara ke tiap kategori
    risk_hits = {}                          # bahan berisiko -> tipe kulit yang perlu hati-hati
    m_votes = {k: 0 for k in MASALAH_KATEGORI}
    m_voters = {k: [] for k in MASALAH_KATEGORI}

    for entry in bahan_list:
        if any(p.search(blob) for p in entry["patterns"]):
            matched.append(entry["bahan"])
            for tag in entry["manfaat"]:
                if tag in votes:
                    votes[tag] += 1
                    voters[tag].append(entry["bahan"])
            for tag in entry["risiko"]:
                risk_hits.setdefault(tag, []).append(entry["bahan"])
            for tag in entry["masalah"]:
                if tag in m_votes:
                    m_votes[tag] += 1
                    m_voters[tag].append(entry["bahan"])

    labels = [tag for tag in KATEGORI if votes[tag] >= THRESHOLD]
    if "berminyak" in labels and "kering" in labels:
        labels.append("kombinasi")

    m_labels = [tag for tag in MASALAH_KATEGORI if m_votes[tag] >= THRESHOLD]

    sinyal_lemah = {tag: voters[tag] for tag in KATEGORI if votes[tag] == 1}

    n_matched = len(matched)
    if n_matched == 0:
        status = "perlu_llm_fallback"
    elif n_matched == 1:
        status = "sinyal_rendah"
    elif labels:
        status = "berbasis_bahan"
    else:
        status = "sinyal_campur_rendah"  # beberapa bahan terdeteksi, tapi tak ada tipe yg capai threshold

    # status masalah kulit dihitung terpisah dari status tipe kulit -- bisa
    # saja tipe kulitnya kuat (berbasis_bahan) tapi masalah kulitnya lemah,
    # atau sebaliknya, karena bahan yang sama bisa nyumbang suara berbeda
    # bobot ke dua dimensi ini.
    if n_matched == 0:
        status_masalah = "perlu_llm_fallback"
    elif n_matched == 1:
        status_masalah = "sinyal_rendah"
    elif m_labels:
        status_masalah = "berbasis_bahan"
    else:
        status_masalah = "sinyal_campur_rendah"

    catatan_risiko = "; ".join(f"{tag}: {', '.join(bhn)}" for tag, bhn in risk_hits.items())
    detail_voting = "; ".join(f"{tag}={votes[tag]}" for tag in KATEGORI)
    detail_sinyal_lemah = "; ".join(f"{tag}<-{','.join(bhn)}" for tag, bhn in sinyal_lemah.items())
    detail_voting_masalah = "; ".join(f"{tag}={m_votes[tag]}" for tag in MASALAH_KATEGORI)

    return {
        "tipe_kulit_cocok": "; ".join(labels),
        "status_pelabelan": status,
        "jumlah_bahan_terdeteksi": n_matched,
        "bahan_terdeteksi": "; ".join(matched),
        "detail_voting": detail_voting,
        "sinyal_lemah_1_bahan": detail_sinyal_lemah,
        "catatan_risiko_sensitif": catatan_risiko,
        "masalah_kulit_cocok": "; ".join(m_labels),
        "status_masalah_kulit": status_masalah,
        "detail_voting_masalah": detail_voting_masalah,
    }


def main():
    bahan_list = load_referensi()
    produk = pd.read_csv(DATA_DIR / "clean_produk_full.csv")

    hasil = []
    for _, row in produk.iterrows():
        blob = build_blob(row)
        hasil.append(label_produk(blob, bahan_list))

    hasil_df = pd.DataFrame(hasil)
    out = pd.concat([produk.reset_index(drop=True), hasil_df], axis=1)

    out_path = DATA_DIR / "clean_produk_labelled_tipe_kulit.csv"
    out.to_csv(out_path, index=False)
    print(f"-> saved {out_path} ({len(out)} baris)\n")

    print("Distribusi status_pelabelan:")
    print(out["status_pelabelan"].value_counts(), "\n")

    print("Distribusi tipe_kulit_cocok (produk bisa masuk >1 baris kalau multi-label):")
    exploded = out["tipe_kulit_cocok"].str.split("; ").explode()
    exploded = exploded[exploded != ""]
    print(exploded.value_counts(), "\n")

    n_ada_risiko = (out["catatan_risiko_sensitif"] != "").sum()
    print(f"Produk dengan catatan risiko bahan sensitif (fragrance/alcohol/paraben/dll): {n_ada_risiko} / {len(out)}\n")

    print("Distribusi status_masalah_kulit:")
    print(out["status_masalah_kulit"].value_counts(), "\n")

    print("Distribusi masalah_kulit_cocok:")
    exploded_m = out["masalah_kulit_cocok"].str.split("; ").explode()
    exploded_m = exploded_m[exploded_m != ""]
    print(exploded_m.value_counts())


if __name__ == "__main__":
    main()