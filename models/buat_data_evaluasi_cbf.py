"""
buat_data_evaluasi_cbf.py

Menyiapkan data untuk verifikasi manual kualitas rekomendasi CBF. Berbeda dengan
verifikasi label sentimen/tipe kulit (satu jawaban benar per baris), yang dinilai
di sini adalah satu DAFTAR rekomendasi: produk mana yang benar-benar cocok, dan
apakah produk yang paling cocok berada di urutan teratas.

METODE: 10 "persona" (kombinasi tipe kulit + masalah kulit + budget)
dirancang menyebar ke semua pilihan yang ada (5 tipe kulit, 6 masalah
kulit, campuran budget terbatas & tanpa batas). Tiap persona diminta
Top-30 dari CBFEngine, disusun jadi 1 baris per (persona, produk) --
total 10 x 30 = 300 baris.

KENAPA TOP-30, BUKAN SEMUA 984 PRODUK (catatan metode untuk Bab III/IV):
Menilai relevansi ke SEMUA 984 produk per persona (10.840 penilaian
manual) tidak masuk akal dikerjakan manusia. Yang dipakai di sini adalah
"pooling" -- metode standar riset information retrieval kalau ground
truth lengkap mustahil dibuat: hanya kandidat yang benar-benar
direkomendasikan sistem (top-30) yang dinilai. Konsekuensinya, "Recall"
yang dihitung di hitung_metrik_cbf.py BUKAN recall murni (yang memerlukan
semua produk relevan di seluruh 984), melainkan recall RELATIF
terhadap jumlah relevan yang ketemu DI DALAM pool 30 itu. Ini harus
disebut eksplisit sebagai batasan metode, bukan diam-diam diklaim
recall penuh.

CARA PAKAI (dari root repo):
    python models/buat_data_evaluasi_cbf.py
Lalu buka data/evaluasi_cbf_untuk_dinilai.xlsx, isi kolom relevan_1_0
(1 = produk itu memang cocok buat persona di baris itu, 0 = tidak) untuk
SEMUA 300 baris, baru jalankan hitung_metrik_cbf.py.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from cbf_engine import CBFEngine

DATA_FILE = Path("data/products_final.csv")
OUTPUT_FILE = Path("data/evaluasi_cbf_untuk_dinilai.xlsx")
TOP_N = 30

# 10 persona dirancang menyebar: tiap 5 tipe kulit muncul 2x, tiap 6
# masalah kulit muncul minimal 2x, budget dicampur (ada yang dibatasi,
# ada yang tidak) -- supaya evaluasi tidak bias ke 1-2 kombinasi tertentu.
PERSONA = [
    dict(id="P01", tipe_kulit="berminyak", masalah_kulit=["jerawat"], budget_max=50_000),
    dict(id="P02", tipe_kulit="berminyak", masalah_kulit=["jerawat", "kusam"], budget_max=100_000),
    dict(id="P03", tipe_kulit="kering", masalah_kulit=["dehidrasi", "kusam"], budget_max=150_000),
    dict(id="P04", tipe_kulit="kering", masalah_kulit=["penuaan"], budget_max=None),
    dict(id="P05", tipe_kulit="sensitif", masalah_kulit=["kemerahan_iritasi"], budget_max=75_000),
    dict(id="P06", tipe_kulit="sensitif", masalah_kulit=["kemerahan_iritasi", "dehidrasi"], budget_max=200_000),
    dict(id="P07", tipe_kulit="normal", masalah_kulit=["penuaan", "hiperpigmentasi"], budget_max=150_000),
    dict(id="P08", tipe_kulit="normal", masalah_kulit=["kusam"], budget_max=50_000),
    dict(id="P09", tipe_kulit="kombinasi", masalah_kulit=["jerawat", "hiperpigmentasi"], budget_max=100_000),
    dict(id="P10", tipe_kulit="kombinasi", masalah_kulit=["penuaan", "dehidrasi"], budget_max=None),
]


def main():
    engine = CBFEngine(DATA_FILE)
    print(f"Data dimuat: {len(engine.df)} produk.\n")

    semua_baris = []
    for p in PERSONA:
        hasil = engine.recommend(
            tipe_kulit=p["tipe_kulit"],
            masalah_kulit=p["masalah_kulit"],
            budget_max=p["budget_max"],
            top_n=TOP_N,
        )
        n_hasil = len(hasil)
        if n_hasil < TOP_N:
            print(f"[Peringatan] Persona {p['id']} cuma dapat {n_hasil} produk "
                  f"(kurang dari {TOP_N}) -- kombinasi filter budget/tipe kulit ini "
                  f"kemungkinan terlalu ketat buat katalog yang ada.")

        for rank, (_, row) in enumerate(hasil.iterrows(), start=1):
            semua_baris.append({
                "persona_id": p["id"],
                "persona_tipe_kulit": p["tipe_kulit"],
                "persona_masalah_kulit": "; ".join(p["masalah_kulit"]),
                "persona_budget_max": p["budget_max"] if p["budget_max"] is not None else "(tanpa batas)",
                "rank": rank,
                "id_produk": row["id"],
                "nama_produk": row["nama_produk"],
                "kategori": row["kategori"],
                "harga": row["harga"],
                "tipe_kulit_cocok": row["tipe_kulit_cocok"],
                "masalah_kulit_cocok": row["masalah_kulit_cocok"],
                "skor_cbf": round(row["skor_cbf"], 4),
                "relevan_1_0": pd.NA,  # <-- ISI INI MANUAL: 1 = cocok, 0 = tidak cocok
            })

    out = pd.DataFrame(semua_baris)
    out.to_excel(OUTPUT_FILE, index=False)

    print(f"-> saved {OUTPUT_FILE} ({len(out)} baris = {len(PERSONA)} persona x {TOP_N} produk)")
    print("\nSebaran persona:")
    for p in PERSONA:
        print(f"  {p['id']}: tipe={p['tipe_kulit']:<10} masalah={p['masalah_kulit']!s:<35} "
              f"budget={p['budget_max']}")
    print(f"\nLangkah berikutnya: buka {OUTPUT_FILE}, isi kolom 'relevan_1_0' "
          f"(1/0) untuk SEMUA {len(out)} baris, lalu jalankan hitung_metrik_cbf.py.")


if __name__ == "__main__":
    main()
