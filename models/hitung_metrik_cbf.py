"""
hitung_metrik_cbf.py

Menghitung Precision@10, Recall (relatif ke pool), F1@10, dan NDCG@10
dari data/evaluasi_cbf_untuk_dinilai.xlsx yang sudah diisi manual
(kolom relevan_1_0, 1/0 per baris).

CATATAN METODE (dicantumkan sebagai batasan di Bab III/IV):
  Recall baku (buku teks) = (relevan yang ketemu) / (SEMUA relevan yang
  ADA, di seluruh 984 produk). Kita tidak menilai seluruh 984 produk per
  persona (tidak masuk akal dikerjakan manual, 10 x 984 = 9.840 baris),
  hanya 30 produk yang DITAWARKAN sistem (top-30) yang dinilai -- metode
  "pooling" standar di riset information retrieval kalau ground truth
  penuh mustahil dibuat.
  Konsekuensinya: "Recall" di sini dihitung RELATIF TERHADAP JUMLAH
  RELEVAN YANG DITEMUKAN DI DALAM POOL 30, bukan recall murni. Kalau
  ternyata ada produk relevan di luar top-30 yang tidak pernah dinilai,
  itu tidak pernah ikut dihitung -- recall bisa kelihatan lebih tinggi
  dari recall sebenarnya. Ini bukan kecurangan selama disebutkan
  eksplisit sebagai batasan metode.

CARA PAKAI (dari root repo):
    python models/hitung_metrik_cbf.py
Menolak jalan (exit dengan pesan jelas) kalau ada baris yang kolom
relevan_1_0-nya masih kosong.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

INPUT_FILE = Path("data/evaluasi_cbf_untuk_dinilai.xlsx")
K = 10  # Precision@K / NDCG@K


def hitung_ndcg_at_k(relevansi_terurut: list, k: int) -> float:
    """relevansi_terurut: list 0/1 sudah terurut sesuai rank sistem (rank 1 duluan).
    'Ideal' dihitung dari relevansi yang SAMA (disusun ulang: semua 1
    didahulukan) -- konsisten dengan pooling, karena relevansi hanya diketahui
    di dalam pool yang dinilai, bukan di seluruh katalog."""
    rel_k = relevansi_terurut[:k]
    dcg = sum(rel / np.log2(i + 2) for i, rel in enumerate(rel_k))
    ideal = sorted(relevansi_terurut, reverse=True)[:k]
    idcg = sum(rel / np.log2(i + 2) for i, rel in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"{INPUT_FILE} tidak ditemukan. Jalankan buat_data_evaluasi_cbf.py dulu.")

    df = pd.read_excel(INPUT_FILE)

    kosong = df["relevan_1_0"].isna()
    if kosong.any():
        print(f"[GAGAL] Masih ada {kosong.sum()} / {len(df)} baris yang kolom 'relevan_1_0'-nya "
              f"belum diisi (kosong). Isi semua baris dulu (1 = cocok, 0 = tidak cocok) sebelum "
              f"menjalankan script ini.\n")
        print("Persona yang belum lengkap:")
        print(df.loc[kosong, "persona_id"].value_counts())
        sys.exit(1)

    df["relevan_1_0"] = df["relevan_1_0"].astype(int)
    if not df["relevan_1_0"].isin([0, 1]).all():
        aneh = df.loc[~df["relevan_1_0"].isin([0, 1]), ["persona_id", "rank", "relevan_1_0"]]
        raise ValueError(f"Ada nilai relevan_1_0 selain 0/1:\n{aneh}")

    df = df.sort_values(["persona_id", "rank"])

    baris_metrik = []
    for persona_id, grup in df.groupby("persona_id", sort=False):
        grup = grup.sort_values("rank")
        relevansi = grup["relevan_1_0"].tolist()
        n_pool = len(relevansi)
        n_relevan_pool = sum(relevansi)

        top_k = relevansi[:K]
        precision_k = sum(top_k) / K

        # Recall RELATIF ke pool (lihat catatan metode di docstring) --
        # bukan recall murni. Kalau tidak ada satupun relevan di pool
        # (n_relevan_pool == 0), recall didefinisikan 0 (bukan dibagi 0).
        recall_pool = (sum(top_k) / n_relevan_pool) if n_relevan_pool > 0 else 0.0

        f1 = (2 * precision_k * recall_pool / (precision_k + recall_pool)
              if (precision_k + recall_pool) > 0 else 0.0)

        ndcg_k = hitung_ndcg_at_k(relevansi, K)

        baris_metrik.append({
            "persona_id": persona_id,
            "n_pool": n_pool,
            "n_relevan_di_pool": n_relevan_pool,
            f"precision_at_{K}": round(precision_k, 4),
            "recall_relatif_pool": round(recall_pool, 4),
            f"f1_at_{K}": round(f1, 4),
            f"ndcg_at_{K}": round(ndcg_k, 4),
        })

    hasil = pd.DataFrame(baris_metrik)

    print("=" * 78)
    print(f"METRIK CBF PER PERSONA (K={K}, dihitung dari pooling top-{df.groupby('persona_id').size().iloc[0]})")
    print("=" * 78)
    print(hasil.to_string(index=False))

    print()
    print("=" * 78)
    print("RATA-RATA (macro-average lintas persona)")
    print("=" * 78)
    for kol in [f"precision_at_{K}", "recall_relatif_pool", f"f1_at_{K}", f"ndcg_at_{K}"]:
        print(f"{kol}: {hasil[kol].mean():.4f}")

    print()
    print("[Catatan metode -- wajib dicantumkan] 'recall_relatif_pool' di atas BUKAN recall baku.")
    print("Dihitung relatif terhadap jumlah produk relevan yang ditemukan DI DALAM pool top-"
          f"{df.groupby('persona_id').size().iloc[0]} yang dinilai manual, bukan terhadap seluruh")
    print("produk relevan di katalog (yang tidak dinilai karena tidak masuk akal dikerjakan manual).")

    out_path = INPUT_FILE.parent / "hasil_metrik_cbf.csv"
    hasil.to_csv(out_path, index=False)
    print(f"\n-> Detail per-persona disimpan ke {out_path}")


if __name__ == "__main__":
    main()
