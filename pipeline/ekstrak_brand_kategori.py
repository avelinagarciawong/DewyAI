"""
ekstrak_brand_kategori.py

Mengekstrak brand & kategori produk dari nama_produk + deskripsi dengan HEURISTIK
keyword/frekuensi -- BUKAN sitasi atau ground truth, sehingga tidak 100% akurat
(lihat CATATAN #2 di build_products_final.py). Diperlukan karena data mentah
Shopee tidak memiliki kolom brand/kategori terstruktur.

METODOLOGI BRAND:
  1. Buang prefix dekoratif seller di depan nama produk (emoji, tanda kurung
     seperti "[BPOM]"/"[READY]", simbol "*", "❤", dll), yang sering salah
     terdeteksi sebagai brand bila tidak dibuang lebih dulu.
  2. Cocokkan ke DAFTAR_BRAND (brand yang sering muncul di 999 produk, diperiksa
     manual lewat frekuensi kata pertama) dengan regex word-boundary; kecocokan
     TERPANJANG didahulukan (agar "MS Glow" tidak terpotong menjadi "MS" dan
     "Hada Labo" tidak menjadi "Hada").
     Match ini dapat status 'yakin'.
  3. Bila tidak ada yang cocok di DAFTAR_BRAND, dipakai kata pertama
     (title case) SELAMA bukan kata generik non-brand (BLOCKLIST_BRAND --
     "cream", "serum", "toner", "masker", dll -- ini nama JENIS produk,
     bukan brand). Match fallback ini dapat status 'perlu_cek' (confidence
     rendah, perlu diperiksa sebelum dipakai untuk klaim apa pun).
  4. Bila kata pertama juga masuk blocklist / kosong -> brand = kosong,
     status 'tidak_terdeteksi'.

METODOLOGI KATEGORI:
  Keyword matching ke KATEGORI_KEYWORDS (di bawah), urutan dicek dari
  kategori paling spesifik lebih dulu (misalnya sunscreen sebelum moisturizer,
  karena produk sunscreen sering juga menyebut kata "cream"). Kategori pertama
  yang cocok dipakai.
  NAMA PRODUK DIPERIKSA LEBIH DULU; deskripsi hanya cadangan bila nama tidak
  menyebut kategori apa pun. Bila nama dan deskripsi diperiksa sekaligus, ~19%
  produk salah label karena deskripsi menyebut kategori LAIN (mis. "Cetaphil
  Gentle Skin Cleanser" menjadi sunscreen karena deskripsinya menyarankan
  memakai sunscreen setelahnya).
  Bila tidak ada kata kunci yang cocok, kategori dibiarkan KOSONG (bukan ditebak
  "lainnya"), konsisten dengan prinsip di label_tipe_kulit.py.
  Terakhir, koreksi manual di data/koreksi_kategori.csv (link, kategori)
  menimpa hasil heuristik -- hasil pengecekan manual tetap terpakai walau
  script ini dijalankan ulang.

Sumber : data/products_final.csv (butuh kolom nama_produk, deskripsi, link
         -- jalankan build_products_final.py minimal sekali agar file ini ada;
         brand/kategori-nya akan ditimpa build_products_final.py setelah
         skrip ini dijalankan)
Output : data/brand_kategori_produk.csv (kolom: link, brand,
         status_ekstraksi_brand, kategori)

CARA PAKAI (dari root repo):
    python pipeline/ekstrak_brand_kategori.py
    python pipeline/build_products_final.py   # dijalankan ulang agar brand/kategori terpakai
"""
import re
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data")
INPUT_FILE = DATA_DIR / "products_final.csv"
OUTPUT_FILE = DATA_DIR / "brand_kategori_produk.csv"
KOREKSI_FILE = DATA_DIR / "koreksi_kategori.csv"

# Brand yang beneran sering muncul di 999 produk (dicek manual lewat
# frekuensi kata pertama nama_produk) + brand skincare lokal/KBeauty umum
# lain yang lazim ada di Shopee Indonesia. Urutan TIDAK penting -- dicocokkan
# berdasar PANJANG nama brand (kata terbanyak dulu), bukan urutan list ini.
DAFTAR_BRAND = [
    "Hada Labo", "Ms Glow", "The Originote", "The Face", "The Body Shop",
    "Pyunkang Yul", "Some By Mi", "Skin1004", "Mineral Botanica",
    "Make Over", "La Tulipe", "Mustika Ratu", "Wardah", "Viva", "Hanasui",
    "Azarine", "Skintific", "Emina", "Garnier", "Bioaqua", "Erha",
    "Implora", "Whitelab", "Glad2glow", "Livi", "Theraskin", "Pond's",
    "Ponds", "Npure", "Scarlett", "Sariayu", "Facetology", "Breylee",
    "Somethinc", "Avoskin", "Cosrx", "Innisfree", "Numbuzin", "Purbasari",
    "Ovale", "Citra", "Marina", "Nivea", "Olay", "L'Oreal", "Loreal",
    "Vaseline", "Cetaphil", "Bioderma", "Kahf", "Aveeno", "Acnes", "Safi",
    "Zwitsal", "Herborist", "Emeron", "Shinzui", "Barenbliss", "Naavagreen",
    "Elformula", "Derma Express", "Refaquin", "Originote", "Elzet",
    "Radysa", "Feliz", "Madame Gie", "Vitacid", "Dermies",
]

# kata pertama yang SERING salah ke-deteksi jadi "brand" via fallback --
# ini semua nama JENIS produk / dekorasi, bukan brand.
BLOCKLIST_BRAND = {
    "cream", "serum", "toner", "masker", "sabun", "krim", "acne", "skin",
    "the", "sunscreen", "facial", "essence", "gel", "lotion", "mist",
    "mask", "peeling", "scrub", "moisturizer", "cleanser", "sheet",
    "ready", "new", "best", "seller", "promo", "paket", "free", "gift",
    "bpom", "original", "termurah", "murah", "grosir", "diskon", "hemat",
}

# urutan penting -- yang lebih spesifik dicek duluan.
KATEGORI_KEYWORDS = [
    ("sunscreen", ["sunscreen", "sunblock", "tabir surya", "spf", "uv shield", "uv protect"]),
    ("acne_patch", ["acne patch", "pimple patch", "hydrocolloid"]),
    ("masker", ["sheet mask", "masker wajah", "face mask", "peel off", "clay mask", "masker komedo"]),
    ("eksfoliator", ["eksfoliasi", "exfoliating", "peeling", "scrub", "aha bha", "exfoliator"]),
    ("facial_wash", ["facial wash", "face wash", "sabun cuci muka", "cleanser", "cleansing", "sabun wajah", "facial foam"]),
    ("toner", ["toner", "astringent", "facial tonic"]),
    ("serum", ["serum"]),
    ("essence", ["essence", "ampoule", "ampul"]),
    ("mist", ["face mist", "facial mist", "spray wajah"]),
    # eye cream sengaja masuk moisturizer: chatbot (models/nlu.py) tidak punya
    # kategori eye cream terpisah, "eye cream" dari user dipetakan ke moisturizer
    ("moisturizer", ["moisturizer", "pelembab", "day cream", "night cream", "cream", "lotion", "gel wajah", "krim wajah",
                     "eye cream", "krim mata", "under eye"]),
]


def strip_prefix_dekoratif(nama: str) -> str:
    """Buang emoji/tanda kurung/simbol dekoratif di depan nama produk yang
    suka dipasang seller (misal '❤ BELIA ❤ EMINA ...' atau '[BPOM] Wardah ...')."""
    s = nama
    # buang blok [...] atau (...) di awal, berulang (bisa lebih dari 1 blok)
    s = re.sub(r"^(\s*[\[\(][^\]\)]*[\]\)]\s*)+", "", s)
    # buang simbol non-alfanumerik di depan (emoji, *, -, dst)
    s = re.sub(r"^[^\w]+", "", s, flags=re.UNICODE)
    return s.strip()


def cari_brand(nama: str):
    bersih = strip_prefix_dekoratif(str(nama))

    kandidat = sorted(DAFTAR_BRAND, key=lambda b: -len(b))
    for brand in kandidat:
        if re.search(rf"\b{re.escape(brand)}\b", bersih, flags=re.IGNORECASE):
            return brand, "yakin"

    kata_pertama = bersih.split(" ")[0] if bersih else ""
    kata_pertama_bersih = re.sub(r"[^\w'-]", "", kata_pertama)
    if kata_pertama_bersih and kata_pertama_bersih.lower() not in BLOCKLIST_BRAND and len(kata_pertama_bersih) >= 3:
        return kata_pertama_bersih.title(), "perlu_cek"

    return None, "tidak_terdeteksi"


def cari_kategori(nama: str, deskripsi: str):
    for teks in (str(nama).lower(), f"{nama} {deskripsi}".lower()):  # nama dulu, deskripsi cadangan
        for kategori, keywords in KATEGORI_KEYWORDS:
            if any(kw in teks for kw in keywords):
                return kategori
    return None


def terapkan_koreksi(df):
    """Koreksi manual (link, kategori) menimpa hasil heuristik. kategori
    "(kosong)" = produk sengaja tidak diberi kategori -- dibaca tanpa
    konversi NaN, supaya pilihan itu tidak diam-diam terbuang lalu hasil
    heuristiknya yang terpakai."""
    if not KOREKSI_FILE.exists():
        return df, 0
    koreksi = pd.read_csv(KOREKSI_FILE, keep_default_na=False)
    koreksi = koreksi[koreksi["link"].str.strip() != ""]
    peta = {link: (None if kat.strip() in ("", "(kosong)") else kat.strip())
            for link, kat in zip(koreksi["link"], koreksi["kategori"])}
    kena = df["link"].isin(peta)
    df.loc[kena, "kategori"] = df.loc[kena, "link"].map(peta)
    return df, int(kena.sum())


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"{INPUT_FILE} tidak ditemukan. Jalankan build_products_final.py dulu "
                                 f"(brand/kategori-nya nanti di-overwrite lagi setelah file ini jalan).")

    df = pd.read_csv(INPUT_FILE)

    hasil = df["nama_produk"].apply(cari_brand)
    df["brand"] = hasil.apply(lambda x: x[0])
    df["status_ekstraksi_brand"] = hasil.apply(lambda x: x[1])
    df["kategori"] = df.apply(lambda r: cari_kategori(r["nama_produk"], r.get("deskripsi", "")), axis=1)
    df, n_koreksi = terapkan_koreksi(df)
    print(f"Koreksi manual dari {KOREKSI_FILE.name}: {n_koreksi} produk")

    out = df[["link", "brand", "status_ekstraksi_brand", "kategori"]]
    out.to_csv(OUTPUT_FILE, index=False)

    print(f"-> saved {OUTPUT_FILE} ({len(out)} produk)\n")
    print("Distribusi status_ekstraksi_brand:")
    print(out["status_ekstraksi_brand"].value_counts())
    print(f"\nTop 15 brand terdeteksi ('yakin'):")
    print(out[out["status_ekstraksi_brand"] == "yakin"]["brand"].value_counts().head(15))
    print(f"\nProduk tanpa kategori (nggak match kata kunci manapun): "
          f"{out['kategori'].isna().sum()} / {len(out)} ({out['kategori'].isna().mean()*100:.1f}%)")
    print("\nDistribusi kategori:")
    print(out["kategori"].value_counts())


if __name__ == "__main__":
    main()
