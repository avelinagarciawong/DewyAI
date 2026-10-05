"""
agregasi_sentimen.py

Mengubah hasil label_sentimen.py (ribuan baris ulasan, satu baris per
ulasan) menjadi ringkasan PER PRODUK: skor_sentimen & jml_ulasan, sesuai kolom
skor_sentimen & jml_ulasan pada Tabel 3.13 (struktur tabel products).

DEFINISI skor_sentimen (Tabel 3.13):
    "proporsi ulasan positif (0-1)"
    = jumlah ulasan berlabel Positif / jumlah ulasan yang berhasil dilabeli
    (Netral dan Negatif masuk penyebut; hanya Positif yang menjadi pembilang)

Produk digabung pakai kolom 'link' (URL produk), karena itu satu-satunya
kolom yang identik nilainya antara file ulasan dan file produk.

CARA PAKAI (dari root repo):
    python pipeline/agregasi_sentimen.py
Sesuaikan INPUT_FILE bila nama file hasil pelabelan sentimen berbeda.
"""
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data")
INPUT_FILE = DATA_DIR / "clean_merged_produk_ulasan_labelled_v2.csv"
OUTPUT_FILE = DATA_DIR / "agregasi_sentimen_produk.csv"


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"{INPUT_FILE} tidak ditemukan.")

    df = pd.read_csv(INPUT_FILE)

    labeled = df[df["sentimen_prediksi"].notna() & (df["sentimen_prediksi"] != "")]
    n_unlabeled = len(df) - len(labeled)
    if n_unlabeled > 0:
        print(f"Peringatan: {n_unlabeled} ulasan belum berlabel (sentimen_prediksi kosong) -- "
              f"tidak ikut dihitung. Pastikan label_sentimen.py sudah selesai 100% dulu.")

    # 'link' = link produk. Kolom ini ada di file ulasan dengan nama 'link'
    # (hasil merge produk+ulasan sebelumnya menimpa nama kolom jadi 'link').
    if "link" not in labeled.columns:
        raise KeyError("Kolom 'link' tidak ditemukan di file ulasan -- cek nama kolom link produk yang benar.")

    grouped = labeled.groupby("link")["sentimen_prediksi"]
    jml_ulasan = grouped.count()
    jml_positif = grouped.apply(lambda s: (s == "Positif").sum())
    skor_sentimen = (jml_positif / jml_ulasan).round(4)

    hasil = pd.DataFrame({
        "link": jml_ulasan.index,
        "skor_sentimen": skor_sentimen.values,
        "jml_ulasan": jml_ulasan.values,
    })

    hasil.to_csv(OUTPUT_FILE, index=False)
    print(f"-> saved {OUTPUT_FILE} ({len(hasil)} produk)\n")
    print(f"Total ulasan terlabeli yang diagregasi: {len(labeled)}")
    print(f"Total produk unik yang punya minimal 1 ulasan: {len(hasil)}")
    print("\nContoh distribusi skor_sentimen:")
    print(hasil["skor_sentimen"].describe())


if __name__ == "__main__":
    main()
