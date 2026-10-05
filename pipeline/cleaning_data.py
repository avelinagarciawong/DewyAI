import re
import pandas as pd
from pathlib import Path

INPUT_DIR = Path("data")
OUTPUT_DIR = Path("data")

#HELPER

def strip_leading_number(text: str) -> str:
    if not isinstance(text,str):
        return text
    return re.sub(r"^\d+\.\s*", "", text).strip()

def parse_harga(harga: str):
    """'Rp42.000' -> 42000 (int). Return None kalau kosong/invalid."""
    if not isinstance(harga, str):
        return None
    digits = re.sub(r"[^\d]", "", harga)
    return int(digits) if digits else None


def parse_terjual(terjual: str):
    """'500+ terjual' / '1,2rb terjual' -> angka estimasi (int)."""
    if not isinstance(terjual, str):
        return None
    t = terjual.lower().replace(",", ".")
    match = re.search(r"([\d.]+)\s*(rb|jt)?", t)
    if not match:
        return None
    num = float(match.group(1))
    unit = match.group(2)
    if unit == "rb":
        num *= 1_000
    elif unit == "jt":
        num *= 1_000_000
    return int(num)


# ---------------------------------------------------------------
# 1. CLEAN PRODUK
# ---------------------------------------------------------------

HARGA_OUTLIER_THRESHOLD = 10_000_000  # Rp 10 juta

def clean_produk(path_in: Path) -> pd.DataFrame:
    df = pd.read_csv(path_in)

    df["nama_produk"] = df["nama_produk"].apply(strip_leading_number)
    df["harga_bersih"] = df["harga"].apply(parse_harga)
    df["terjual_bersih"] = df["terjual"].apply(parse_terjual)

    # dedup berdasarkan link (link paling unik dibanding nama produk)
    before = len(df)
    df = df.drop_duplicates(subset="link").reset_index(drop=True)
    print(f"[produk] drop duplicate link: {before - len(df)} baris")

    # flag baris yang datanya ga lengkap (harga/rating/terjual kosong)
    df["data_lengkap"] = df[["harga_bersih", "rating", "terjual_bersih"]].notna().all(axis=1)
    n_incomplete = (~df["data_lengkap"]).sum()
    print(f"[produk] {n_incomplete} baris tanpa harga/rating/terjual (masih disimpan, ditandai data_lengkap=False)")

    # tandai harga yang jelas bukan harga produk sebenarnya -- pola umum di Shopee:
    # listing "(FREE GIFT/DO NOT ORDER)" diberi harga sangat tinggi (ditemukan 1 produk
    # Rp 1 miliar) agar tidak terbeli karena salah klik. Ditandai, bukan dibuang,
    # konsisten dengan flag data_lengkap di atas. Ambang Rp 10 juta dipilih karena
    # harga wajar tertinggi kedua hanya Rp 1,53 juta (ada jarak besar sebelum Rp 1 miliar).
    df["harga_outlier"] = df["harga_bersih"] > HARGA_OUTLIER_THRESHOLD
    n_outlier = df["harga_outlier"].sum()
    print(f"[produk] {n_outlier} baris harga_bersih > Rp{HARGA_OUTLIER_THRESHOLD:,} (ditandai harga_outlier=True, kemungkinan listing 'DO NOT ORDER')")

    return df


# ---------------------------------------------------------------
# 1b. CLEAN DESKRIPSI PRODUK (BARU)
# ---------------------------------------------------------------
# Kolom 'atribut' di deskripsi_produk.csv formatnya:
#   "Jenis Kulit:Semua Jenis Kulit | Komposisi:AHA BHA PHA | Zat Aktif:Niacinamide | ..."
# Field-field ini yang paling berguna untuk labelling tipe kulit nanti,
# jadi kita tarik keluar jadi kolom sendiri-sendiri, sisanya tetap disimpan utuh di 'atribut'.

ATRIBUT_FIELDS = [
    "Jenis Kulit",
    "Zat Aktif",
    "Komposisi",
    "Ingredient (Komposisi)",
    "Manfaat Perawatan Kulit",
]

def extract_atribut_field(atribut: str, field_name: str):
    if not isinstance(atribut, str):
        return None
    for part in atribut.split("|"):
        if ":" in part:
            k, _, v = part.partition(":")
            if k.strip().lower() == field_name.lower():
                v = v.strip()
                return v if v else None
    return None


def clean_deskripsi(path_in: Path) -> pd.DataFrame:
    df = pd.read_csv(path_in)

    df["nama_produk"] = df["nama_produk"].apply(strip_leading_number)

    for field in ATRIBUT_FIELDS:
        col_name = "raw_" + re.sub(r"[^a-z0-9]+", "_", field.lower()).strip("_")
        df[col_name] = df["atribut"].apply(lambda a, f=field: extract_atribut_field(a, f))

    before = len(df)
    df = df.drop_duplicates(subset="link").reset_index(drop=True)
    print(f"[deskripsi] drop duplicate link: {before - len(df)} baris")

    n_no_deskripsi = df["deskripsi"].isna().sum()
    n_status_bermasalah = (df["status"] != "ok").sum()
    print(f"[deskripsi] {n_no_deskripsi} baris tanpa teks deskripsi")
    print(f"[deskripsi] {n_status_bermasalah} baris dengan status != 'ok' (kosong/gagal scrape)")

    for field in ATRIBUT_FIELDS:
        col_name = "raw_" + re.sub(r"[^a-z0-9]+", "_", field.lower()).strip("_")
        n_terisi = df[col_name].notna().sum()
        print(f"[deskripsi] field '{field}' terisi di {n_terisi}/{len(df)} produk")

    return df


def merge_produk_deskripsi(produk: pd.DataFrame, deskripsi: pd.DataFrame) -> pd.DataFrame:
    """Gabungkan info dasar produk (harga/rating/terjual) dengan deskripsi+atribut
    (kandungan bahan, klaim jenis kulit). Ini yang jadi tabel produk 'lengkap',
    dasar untuk tahap labelling tipe kulit berikutnya."""
    deskripsi_cols = ["link", "deskripsi", "atribut", "status"] + [
        "raw_" + re.sub(r"[^a-z0-9]+", "_", f.lower()).strip("_") for f in ATRIBUT_FIELDS
    ]
    merged = produk.merge(
        deskripsi[deskripsi_cols],
        on="link",
        how="left",
        suffixes=("", "_deskripsi"),
    )
    n_unmatch = merged["deskripsi"].isna().sum()
    print(f"[merge produk+deskripsi] produk tanpa deskripsi yang cocok: {n_unmatch} / {len(merged)}")
    return merged


# 2. CLEAN ULASAN

def split_label_teks(teks: str):
    """
    Shopee format: 'Performa:bagus Tekstur:Kental  Udah 2 kali beli...'
    Blok label (kalau ada) dipisahkan dari teks bebas oleh SPASI GANDA.
    Return (label_atribut, teks_bebas)
    """
    if not isinstance(teks, str):
        return "", ""

    if ":" not in teks:
        return "", re.sub(r"\s+", " ", teks).strip()

    if "  " in teks:
        label_part, _, free_part = teks.partition("  ")
        label_part = re.sub(r"\s+", " ", label_part).strip()
        free_part = re.sub(r"\s+", " ", free_part).strip()
        return label_part, free_part

    return "", re.sub(r"\s+", " ", teks).strip()


def clean_ulasan(path_in: Path) -> pd.DataFrame:
    df = pd.read_csv(path_in)

    df["nama_produk"] = df["nama_produk"].apply(strip_leading_number)

    split_result = df["teks_ulasan"].apply(split_label_teks)
    df["label_atribut"] = split_result.apply(lambda x: x[0])
    df["teks_bebas"] = split_result.apply(lambda x: x[1])

    before = len(df)
    df = df.drop_duplicates(subset=["link_produk", "teks_ulasan"]).reset_index(drop=True)
    print(f"[ulasan] drop duplicate: {before - len(df)} baris")

    # buang ulasan kosong/terlalu pendek (< 5 karakter) setelah label dipisah
    before = len(df)
    df = df[df["teks_bebas"].str.len().fillna(0) >= 5].reset_index(drop=True)
    print(f"[ulasan] drop ulasan terlalu pendek: {before - len(df)} baris")

    dist = df["rating"].value_counts(normalize=True).round(3) * 100
    print(f"[ulasan] distribusi rating (%):\n{dist}")

    return df

# 3. CLEAN DATA X
from urllib.parse import urlparse


def kategorikan_link(url):
    if not isinstance(url, str):
        return None
    domain = urlparse(url).netloc.replace("www.", "").lower()

    if any(d in domain for d in ["shopee", "shope.ee"]):
        return "ecommerce_shopee"
    if "tokopedia" in domain:
        return "ecommerce_tokopedia"
    if "blibli" in domain:
        return "ecommerce_blibli"
    if "amzn" in domain or "amazon" in domain:
        return "ecommerce_amazon"
    if domain in ("x.com", "twitter.com"):
        return "social_media"
    if "indeed" in domain:
        return "lowongan_kerja"
    if "halodoc" in domain:
        return "kesehatan_app"
    if "ncbi" in domain or "pmc" in domain:
        return "jurnal_medis"
    if "forms.gle" in domain:
        return "survey_form"
    if domain in ("bit.ly",):
        return "shortlink_tidak_jelas"
    return "blog_lain_lain"


NOISE_KATEGORI = {"lowongan_kerja", "shortlink_tidak_jelas", "blog_lain_lain", "social_media"}


def clean_x(path_in: Path) -> pd.DataFrame:
    # utf-8-sig buang BOM di kolom pertama otomatis
    df = pd.read_csv(path_in, encoding="utf-8-sig")

    df["tanggal"] = pd.to_datetime(df["tanggal"], errors="coerce")

    # '-' berarti tidak ada brand disebut -> jadikan null, bukan string '-'
    df["brand_disebut"] = df["brand_disebut"].replace("-", pd.NA)
    df["link_rekomendasi"] = df["link_rekomendasi"].replace("-", pd.NA)

    before = len(df)
    df = df.drop_duplicates(subset="teks").reset_index(drop=True)
    print(f"[x] drop duplicate teks: {before - len(df)} baris")

    # bersihin whitespace berlebih
    df["teks"] = df["teks"].str.replace(r"\s+", " ", regex=True).str.strip()

    # kategorisasi & tandai noise pada link_rekomendasi
    df["kategori_link"] = df["link_rekomendasi"].apply(kategorikan_link)
    df["link_noise"] = df["kategori_link"].isin(NOISE_KATEGORI)
    n_noise = df["link_noise"].sum()
    print(f"[x] link_rekomendasi kategori noise (lowongan/blog/social/shortlink): {n_noise} baris (ditandai, tidak dibuang)")

    print(f"[x] distribusi sentimen:\n{df['sentimen'].value_counts()}")

    return df


# 4. MERGE PRODUK + ULASAN (untuk item profile CBF)
def merge_produk_ulasan(produk: pd.DataFrame, ulasan: pd.DataFrame) -> pd.DataFrame:
    merged = ulasan.merge(
        produk,
        left_on="link_produk",
        right_on="link",
        how="left",
        suffixes=("_ulasan", "_produk"),
    )
    n_unmatch = merged["link"].isna().sum()
    print(f"[merge] ulasan yang gagal ketemu produknya: {n_unmatch} / {len(merged)}")
    return merged

#Main
def main():
    produk = clean_produk(INPUT_DIR / "raw_shopee_produk.csv")
    produk.to_csv(OUTPUT_DIR / "clean_produk.csv", index=False)
    print(f"-> saved clean_produk.csv ({len(produk)} baris)\n")

    # BARU: bersihkan deskripsi_produk.csv dan gabungkan ke produk
    deskripsi_path = INPUT_DIR / "deskripsi_produk.csv"
    if deskripsi_path.exists():
        deskripsi = clean_deskripsi(deskripsi_path)
        deskripsi.to_csv(OUTPUT_DIR / "clean_deskripsi.csv", index=False)
        print(f"-> saved clean_deskripsi.csv ({len(deskripsi)} baris)\n")

        produk_full = merge_produk_deskripsi(produk, deskripsi)
        produk_full.to_csv(OUTPUT_DIR / "clean_produk_full.csv", index=False)
        print(f"-> saved clean_produk_full.csv ({len(produk_full)} baris) -- INI dasar untuk labelling tipe kulit\n")
    else:
        print("[deskripsi] file deskripsi_produk.csv tidak ditemukan, skip\n")

    ulasan = clean_ulasan(INPUT_DIR / "raw_shopee_ulasan.csv")
    ulasan.to_csv(OUTPUT_DIR / "clean_ulasan.csv", index=False)
    print(f"-> saved clean_ulasan.csv ({len(ulasan)} baris)\n")

    merged = merge_produk_ulasan(produk, ulasan)
    merged.to_csv(OUTPUT_DIR / "clean_merged_produk_ulasan.csv", index=False)
    print(f"-> saved clean_merged_produk_ulasan.csv ({len(merged)} baris)\n")

    # sesuaikan nama file input kalau timestamp beda
    x_files = list(INPUT_DIR.glob("review_skincare_x_*.csv"))
    if x_files:
        x_data = clean_x(x_files[0])
        x_data.to_csv(OUTPUT_DIR / "clean_x.csv", index=False)
        print(f"-> saved clean_x.csv ({len(x_data)} baris)\n")
        print("[catatan] clean_x.csv SENGAJA TIDAK di-merge ke produk+ulasan -- lihat penjelasan di chat.")
    else:
        print("[x] file review_skincare_x_*.csv tidak ditemukan, skip")


if __name__ == "__main__":
    main()