"""
build_products_final.py

Menggabungkan tiga hasil pipeline (tipe kulit, masalah kulit, sentimen)
menjadi SATU tabel products final, mengikuti Tabel 3.13 (struktur tabel products)
dengan satu kolom tambahan (lihat CATATAN di bawah).

Sumber data:
  - data/clean_produk_labelled_tipe_kulit_v2.csv (kalau sudah ada, hasil
    llm_fallback_tipe_kulit.py -- pakai tipe_kulit_cocok_final &
    masalah_kulit_cocok_final) ATAU data/clean_produk_labelled_tipe_kulit.csv
    (fallback kalau llm_fallback belum dijalankan -- pakai kolom biasa)
  - data/agregasi_sentimen_produk.csv (dari agregasi_sentimen.py)

CATATAN:
  Tabel 3.13 awalnya hanya memuat kolom 'tipe_kulit_cocok'. Kolom
  'masalah_kulit_cocok' ditambahkan karena onboarding mengumpulkan tipe kulit DAN
  masalah kulit, sehingga produk perlu dilabeli pada kedua dimensi agar CBF dapat
  mencocokkan keduanya.

CATATAN #2:
  brand & kategori diisi dari data/brand_kategori_produk.csv, hasil
  ekstrak_brand_kategori.py (heuristik keyword/frekuensi dari nama_produk +
  deskripsi -- BUKAN sitasi/ground truth, sehingga tidak 100% akurat). Kategori
  dibiarkan kosong (~7,5% produk) bila tidak cocok dengan kata kunci mana pun.
  Brand berstatus 'perlu_cek' (bukan 'yakin') perlu diperiksa sebelum dipakai
  untuk klaim apa pun. Jalankan ekstrak_brand_kategori.py lebih dulu bila
  brand_kategori_produk.csv belum ada.

CARA PAKAI (dari root repo):
    python pipeline/build_products_final.py
"""
import re
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data")
TIPE_KULIT_FILE_V2 = DATA_DIR / "clean_produk_labelled_tipe_kulit_v2.csv"  # setelah llm_fallback
TIPE_KULIT_FILE_V1 = DATA_DIR / "clean_produk_labelled_tipe_kulit.csv"     # sebelum llm_fallback
SENTIMEN_AGG_FILE = DATA_DIR / "agregasi_sentimen_produk.csv"
BRAND_KATEGORI_FILE = DATA_DIR / "brand_kategori_produk.csv"
DIKELUARKAN_FILE = DATA_DIR / "produk_dikeluarkan.csv"  # hasil review manual (kolom link), lihat main()
OUTPUT_FILE = DATA_DIR / "products_final.csv"


def pick_source_tipe_kulit():
    if TIPE_KULIT_FILE_V2.exists():
        print(f"Pakai {TIPE_KULIT_FILE_V2.name} (sudah termasuk hasil llm_fallback).")
        return pd.read_csv(TIPE_KULIT_FILE_V2), True
    if TIPE_KULIT_FILE_V1.exists():
        print(f"[Peringatan] {TIPE_KULIT_FILE_V2.name} belum ada -- pakai "
              f"{TIPE_KULIT_FILE_V1.name} (BELUM termasuk llm_fallback, "
              f"produk perlu_llm_fallback/sinyal_rendah masih kosong labelnya).")
        return pd.read_csv(TIPE_KULIT_FILE_V1), False
    raise FileNotFoundError("Tidak ada file hasil label tipe kulit ditemukan. Jalankan label_tipe_kulit.py dulu.")


def to_str(v):
    return "" if pd.isna(v) else str(v)


# token generik yang ikut kebawa dari kolom atribut Shopee (bukan nama bahan
# beneran) -- ditemukan lewat inspeksi manual data (lihat obrolan/chat log):
# "natural charcoal, other" / "premium" / "1" / "masker" / "dll".
KANDUNGAN_NOISE = {
    "other", "lainnya", "premium", "original", "dll", "masker", "produk",
    "bahan", "campuran", "-", "n/a", "na",
}


def clean_kandungan(raw: str) -> str:
    """Membuang token generik/angka saja dari daftar kandungan gabungan. TIDAK
    menyaring berdasarkan panjang teks (bahan sah yang pendek seperti 'UV', 'AHA',
    'BHA', 'PHA' bisa ikut terbuang); hanya blocklist eksplisit + angka murni."""
    if not raw:
        return raw
    tokens = re.split(r"[,|]", raw)
    kept = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if t.lower() in KANDUNGAN_NOISE:
            continue
        if re.fullmatch(r"\d+", t):  # token berupa angka saja, misal "1"
            continue
        kept.append(t)
    return ", ".join(kept)


def main():
    produk, ada_llm_fallback = pick_source_tipe_kulit()

    if not SENTIMEN_AGG_FILE.exists():
        raise FileNotFoundError(f"{SENTIMEN_AGG_FILE} tidak ditemukan. Jalankan agregasi_sentimen.py dulu.")
    sentimen_agg = pd.read_csv(SENTIMEN_AGG_FILE)

    # kolom tipe_kulit_cocok / masalah_kulit_cocok final -- pakai versi
    # "_final" (hasil llm_fallback) kalau ada, else versi dasar bahan.
    col_tipe = "tipe_kulit_cocok_final" if ada_llm_fallback and "tipe_kulit_cocok_final" in produk.columns else "tipe_kulit_cocok"
    col_masalah = "masalah_kulit_cocok_final" if ada_llm_fallback and "masalah_kulit_cocok_final" in produk.columns else "masalah_kulit_cocok"

    # produk yang sama sekali tidak memiliki informasi (deskripsi kosong DAN ketiga
    # field bahan terstruktur kosong) DAN tidak mendapat label dari jalur lain
    # (misal nama produk kebetulan cocok dengan bahan referensi) dianggap data tidak
    # valid dan dikeluarkan dari dataset. Berbeda dengan 251 produk yang diproses
    # tetapi labelnya kosong: produk tersebut tetap masuk dataset.
    deskripsi_kosong = produk["deskripsi"].isna() | (produk["deskripsi"].astype(str).str.strip() == "")
    bahan_kosong = (
        produk["raw_zat_aktif"].isna()
        & produk["raw_komposisi"].isna()
        & produk["raw_ingredient_komposisi"].isna()
    )
    tanpa_label = produk[col_tipe].isna() | (produk[col_tipe].astype(str).str.strip() == "")
    data_tidak_valid = deskripsi_kosong & bahan_kosong & tanpa_label
    n_invalid = data_tidak_valid.sum()
    if n_invalid > 0:
        print(f"[Data tidak valid] {n_invalid} produk tanpa deskripsi, tanpa bahan terstruktur, DAN "
              f"tanpa label sama sekali -- dikeluarkan dari products_final.csv (bukan dipertahankan kosong).")
        produk = produk.loc[~data_tidak_valid].reset_index(drop=True)

    # produk yang ikut terambil dari kategori "Perawatan Wajah" tetapi di luar
    # cakupan skincare wajah (masker kesehatan/PPE, listing "jangan dipesan",
    # prosedur kosmetik non-skincare), ditemukan lewat audit manual. Polanya
    # dibuat sespesifik mungkin, bukan kata umum seperti "mask"/"parfum"/"capsule"
    # yang banyak mengenai produk skincare asli ("Parfum" misalnya nama INCI bahan
    # pewangi, bukan berarti produknya parfum).
    pola_di_luar_scope = r"kn95|duckbill|do not order|\bkutil\b|tahi lalat|wart remover"
    teks_cek = (produk["nama_produk"].astype(str) + " " + produk["deskripsi"].astype(str)).str.lower()
    di_luar_scope = teks_cek.str.contains(pola_di_luar_scope, regex=True, na=False)
    n_luar_scope = di_luar_scope.sum()
    if n_luar_scope > 0:
        print(f"[Di luar scope] {n_luar_scope} produk terdeteksi bukan skincare wajah "
              f"(masker kesehatan/PPE, listing decoy, atau prosedur non-skincare) -- dikeluarkan.")
        produk = produk.loc[~di_luar_scope].reset_index(drop=True)

    merged = produk.merge(sentimen_agg, on="link", how="left")

    if BRAND_KATEGORI_FILE.exists():
        brand_kategori = pd.read_csv(BRAND_KATEGORI_FILE)[["link", "brand", "kategori"]]
        merged = merged.merge(brand_kategori, on="link", how="left")
    else:
        print(f"[Peringatan] {BRAND_KATEGORI_FILE.name} belum ada -- jalankan "
              f"ekstrak_brand_kategori.py dulu. brand & kategori diisi kosong dulu.")
        merged["brand"] = pd.NA
        merged["kategori"] = pd.NA

    n_tanpa_ulasan = merged["jml_ulasan"].isna().sum()
    if n_tanpa_ulasan > 0:
        print(f"Peringatan: {n_tanpa_ulasan} produk tidak punya ulasan sama sekali -- "
              f"skor_sentimen & jml_ulasan diisi kosong/0.")
    merged["jml_ulasan"] = merged["jml_ulasan"].fillna(0).astype(int)
    # skor_sentimen dibiarkan NaN (bukan 0) kalau tidak ada ulasan -- karena
    # 0 ulasan itu beda makna dari "0% ulasan positif".

    kandungan = (
        merged["raw_zat_aktif"].apply(to_str) + " | "
        + merged["raw_komposisi"].apply(to_str) + " | "
        + merged["raw_ingredient_komposisi"].apply(to_str)
    ).str.strip(" |")
    kandungan = kandungan.replace(r"^(\s*\|\s*)+$", "", regex=True)
    kandungan = kandungan.apply(clean_kandungan)

    out = pd.DataFrame({
        "id": [f"PRD{idx+1:04d}" for idx in range(len(merged))],
        "nama_produk": merged["nama_produk"],
        "link": merged["link"],        # penting: satu-satunya jalan balik ke halaman produk asli
        "brand": merged["brand"],      # lihat CATATAN PENTING #2 di docstring -- heuristik, cek status_ekstraksi_brand
        "kategori": merged["kategori"],
        "kandungan": kandungan,
        "deskripsi": merged["deskripsi"].apply(lambda v: v.strip() if isinstance(v, str) else v),
        "tipe_kulit_cocok": merged[col_tipe],
        "masalah_kulit_cocok": merged[col_masalah],  # TAMBAHAN di luar Tabel 3.13 -- lihat CATATAN PENTING
        # TAMBAHAN -- flag sumber label ('bahan' = keyword matching bersitasi,
        # 'llm' = LLM baca deskripsi). Disepakati eksplisit (lihat obrolan)
        # supaya evaluasi akurasi nanti bisa dipisah antara dua jalur ini,
        # karena tingkat kepercayaan dasarnya beda jauh (sitasi jurnal vs
        # klaim tekstual + pengetahuan umum LLM).
        "sumber_label_tipe_kulit": merged["sumber_label_tipe_kulit"] if "sumber_label_tipe_kulit" in merged.columns else pd.NA,
        "sumber_label_masalah_kulit": merged["sumber_label_masalah_kulit"] if "sumber_label_masalah_kulit" in merged.columns else pd.NA,
        "harga": merged["harga_bersih"],
        "harga_outlier": merged["harga_outlier"],  # True = harga tidak wajar (listing "DO NOT ORDER" dll),
                                                    # filter dulu (df[~df["harga_outlier"]]) sebelum pakai kolom harga
        "rating": merged["rating"],
        "skor_sentimen": merged["skor_sentimen"],
        "jml_ulasan": merged["jml_ulasan"],
        "sumber": merged["sumber"],
        "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    # produk yang diputuskan user untuk dikeluarkan saat review manual (paket
    # bundling, listing tidak jelas, bukan skincare wajah) -- dibuang SETELAH id
    # dibuat, supaya id produk lain tidak bergeser (data evaluasi & riwayat chat
    # merujuk ke id). Nomornya jadi bolong, itu disengaja.
    if DIKELUARKAN_FILE.exists():
        keluar = set(pd.read_csv(DIKELUARKAN_FILE)["link"])
        dibuang = out["link"].isin(keluar)
        print(f"[Review manual] {int(dibuang.sum())} produk dikeluarkan sesuai {DIKELUARKAN_FILE.name}.")
        out = out.loc[~dibuang].reset_index(drop=True)

    out.to_csv(OUTPUT_FILE, index=False)
    print(f"\n-> saved {OUTPUT_FILE} ({len(out)} produk, {len(out.columns)} kolom)")
    print(f"\nProduk dengan tipe_kulit_cocok kosong: {(out['tipe_kulit_cocok'].fillna('') == '').sum()} / {len(out)}")
    print(f"Produk dengan masalah_kulit_cocok kosong: {(out['masalah_kulit_cocok'].fillna('') == '').sum()} / {len(out)}")
    print(f"Produk tanpa skor_sentimen (0 ulasan): {out['skor_sentimen'].isna().sum()} / {len(out)}")
    print(f"Produk dengan harga_outlier=True (jangan dipakai buat fitur harga): {out['harga_outlier'].sum()} / {len(out)}")
    if not ada_llm_fallback:
        print("\n[Ingat] Ini belum termasuk hasil llm_fallback_tipe_kulit.py -- jalankan itu dulu "
              "lalu jalankan ulang script ini kalau mau angka di atas final.")


if __name__ == "__main__":
    main()
