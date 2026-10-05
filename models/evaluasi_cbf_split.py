"""
evaluasi_cbf_split.py

Evaluasi CBF dengan pembagian data training 60% / validation 20% / testing 20%
yang diacak dan diulang 3 kali (seed berbeda). Angka ketiga putaran dirata-rata
dan dihitung standar deviasinya: hasil yang stabil di 3 putaran menunjukkan
kinerja sistem konsisten, bukan kebetulan dari satu kali pengacakan data.

CBF di sini (TF-IDF + cosine similarity) tidak dilatih seperti model supervised
learning: tidak ada parameter yang dipelajari dengan gradient descent. Karena itu
makna ketiga bagian data diadaptasi:

  - TRAINING SET (60%): produk yang menjadi katalog pencarian. Hanya bagian ini
    yang di-fit ke TfidfVectorizer dan boleh muncul sebagai hasil rekomendasi.
  - VALIDATION SET (20%): produk yang dikeluarkan dari katalog; tag
    tipe_kulit_cocok dan masalah_kulit_cocok milik produk itu dipakai sebagai
    profil pengguna simulasi. Dipakai untuk mencoba beberapa kombinasi bobot
    (BOBOT_TIPE_KULIT dst di cbf_engine.py) dan memilih yang terbaik, sebagai
    pengganti tuning hyperparameter.
  - TESTING SET (20%): tidak disentuh sampai kombinasi bobot dipilih, lalu
    dipakai sekali untuk menghasilkan Precision/Recall/F1/NDCG yang dilaporkan.

Relevansi dihitung otomatis dari label tipe_kulit_cocok/masalah_kulit_cocok yang
sudah diverifikasi manual (akurasi tipe kulit 87,8%, lihat
pipeline/hitung_akurasi.py). Sebuah rekomendasi RELEVAN bila tag tipe_kulit_cocok-nya
memuat tipe kulit query secara eksplisit DAN berbagi minimal 1 tag masalah_kulit
dengan produk query.

Cakupan (batasan metode): hanya produk dengan tipe_kulit_cocok DAN
masalah_kulit_cocok terisi yang dipakai sebagai query. Produk dengan tag kosong
tetap dapat menjadi bagian training set/kandidat rekomendasi.

CARA PAKAI (dari root repo):
    python models/evaluasi_cbf_split.py
"""
import math
import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from cbf_engine import CBFEngine, _bersihkan_tag

DATA_FILE = Path("data/products_final.csv")
# 3 seed berbeda -> 3 pengacakan data. Seed ditetapkan agar hasil dapat diulang
# persis sama (reproducible) dan angkanya dapat diperiksa ulang.
DAFTAR_SEED = [42, 123, 2026]
RASIO_TRAIN, RASIO_VAL, RASIO_TEST = 0.6, 0.2, 0.2
K = 10
UKURAN_KOLAM = 30  # top-N yang diambil per query buat dihitung metriknya

# Kombinasi bobot yang dicoba di validation set -- (bobot_tipe_kulit,
# bobot_masalah_kulit, bobot_kategori, bobot_kandungan, bobot_deskripsi).
# Baris pertama = default yang sudah dipakai di cbf_engine.py sekarang.
KANDIDAT_BOBOT = [
    (6, 4, 2, 2, 1),   # default sebelumnya -- tipe kulit lebih diutamakan
    (4, 4, 2, 2, 1),   # versi awal -- tipe & masalah kulit sama berat
    (4, 6, 2, 2, 1),   # masalah_kulit lebih diutamakan
    (4, 4, 4, 2, 1),   # kategori lebih diutamakan -- DIPAKAI chatbot sekarang (lihat cbf_engine.py)
    (3, 3, 1, 1, 1),   # semua tag dibobot lebih ringan, deskripsi lebih berpengaruh
]
# bobot final yang dipakai chatbot -- dievaluasi TERSENDIRI (bobot sama di semua
# seed) supaya ada angka training/validasi/testing untuk konfigurasi yang benar-benar dipakai
BOBOT_FINAL = (4, 4, 4, 2, 1)


def split_data(df, seed):
    idx = list(df.index)
    random.Random(seed).shuffle(idx)
    n = len(idx)
    n_train = int(n * RASIO_TRAIN)
    n_val = int(n * RASIO_VAL)
    idx_train = idx[:n_train]
    idx_val = idx[n_train:n_train + n_val]
    idx_test = idx[n_train + n_val:]
    return df.loc[idx_train].reset_index(drop=True), \
        df.loc[idx_val].reset_index(drop=True), \
        df.loc[idx_test].reset_index(drop=True)


def punya_tag_lengkap(row):
    tipe = _bersihkan_tag(row["tipe_kulit_cocok"])
    masalah = _bersihkan_tag(row["masalah_kulit_cocok"])
    return bool(tipe) and bool(masalah)


def evaluasi_satu_query(engine, query_row, k=K, kolam=UKURAN_KOLAM, exclude_id=None):
    """exclude_id: WAJIB diisi kalau query_row berasal dari dataset yang SAMA
    dengan yang di-fit ke engine (mis. evaluasi di training set sendiri) --
    tanpa ini, produk query akan merekomendasikan dirinya sendiri (cosine
    similarity terhadap diri sendiri = 1.0), sehingga skor training tampak bagus
    karena self-match, bukan karena sistem menemukan produk LAIN yang mirip."""
    tipe_query = _bersihkan_tag(query_row["tipe_kulit_cocok"]).split()
    masalah_query = set(_bersihkan_tag(query_row["masalah_kulit_cocok"]).split())

    hasil = engine.recommend(
        tipe_kulit=tipe_query[0] if tipe_query else None,
        masalah_kulit=list(masalah_query) if masalah_query else None,
        top_n=kolam + (1 if exclude_id is not None else 0),
    )
    if exclude_id is not None:
        hasil = hasil[hasil["id"] != exclude_id].head(kolam)
    if hasil.empty:
        return [0] * 0

    # Relevan WAJIB memenuhi dua syarat: tag tipe_kulit_cocok kandidat memuat tipe
    # kulit query secara EKSPLISIT (bukan sekadar kosong lalu lolos filter) DAN
    # berbagi minimal 1 tag masalah_kulit. Bila hanya masalah_kulit yang diukur,
    # kombinasi bobot yang menekankan masalah_kulit akan selalu unggul di
    # validation (circular), sedangkan bobot tipe_kulit ikut dituning.
    tipe_query_str = tipe_query[0] if tipe_query else None
    relevan = []
    for _, r in hasil.iterrows():
        tipe_kandidat = set(_bersihkan_tag(r["tipe_kulit_cocok"]).split())
        masalah_kandidat = set(_bersihkan_tag(r["masalah_kulit_cocok"]).split())
        cocok_tipe = (tipe_query_str in tipe_kandidat) if tipe_query_str else True
        cocok_masalah = bool(masalah_query & masalah_kandidat) if masalah_query else True
        relevan.append(1 if (cocok_tipe and cocok_masalah) else 0)
    return relevan


def precision_at_k(relevan, k):
    top = relevan[:k]
    return sum(top) / len(top) if top else 0.0


def recall_dalam_kolam(relevan):
    total = sum(relevan)
    if total == 0:
        return 0.0
    return sum(relevan[:K]) / total


def f1(p, r):
    return 0.0 if (p + r) == 0 else 2 * p * r / (p + r)


def dcg_at_k(relevan, k):
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevan[:k]))


def ndcg_at_k(relevan, k):
    dcg = dcg_at_k(relevan, k)
    idcg = dcg_at_k(sorted(relevan, reverse=True), k)
    return dcg / idcg if idcg > 0 else 0.0


def evaluasi_di_set(engine, query_df, k=K, exclude_self=False):
    """exclude_self=True dipakai KHUSUS untuk evaluasi di training set (lihat
    catatan self-match di evaluasi_satu_query). Validation/test set tidak
    memerlukannya karena produknya sudah dikeluarkan dari katalog training,
    sehingga tidak mungkin merekomendasikan dirinya sendiri."""
    semua_p, semua_r, semua_f1, semua_ndcg = [], [], [], []
    n_dilewati = 0
    for _, row in query_df.iterrows():
        if not punya_tag_lengkap(row):
            n_dilewati += 1
            continue
        relevan = evaluasi_satu_query(engine, row, k=k, exclude_id=row["id"] if exclude_self else None)
        if not relevan:
            n_dilewati += 1
            continue
        p = precision_at_k(relevan, k)
        r = recall_dalam_kolam(relevan)
        semua_p.append(p)
        semua_r.append(r)
        semua_f1.append(f1(p, r))
        semua_ndcg.append(ndcg_at_k(relevan, k))

    n = len(semua_p)
    if n == 0:
        return None
    return {
        "n_query": n,
        "n_dilewati": n_dilewati,
        f"precision@{k}": sum(semua_p) / n,
        "recall_dalam_kolam": sum(semua_r) / n,
        "f1": sum(semua_f1) / n,
        f"ndcg@{k}": sum(semua_ndcg) / n,
    }


def jalankan_satu_putaran(df, seed, verbose=True):
    """Satu putaran lengkap: split 60/20/20 (pakai seed ini) -> tuning bobot
    di validation -> evaluasi final di test. Return dict hasil test set."""
    train_df, val_df, test_df = split_data(df, seed)
    if verbose:
        print(f"Split (seed={seed}): train={len(train_df)} ({len(train_df)/len(df):.1%}), "
              f"val={len(val_df)} ({len(val_df)/len(df):.1%}), "
              f"test={len(test_df)} ({len(test_df)/len(df):.1%})")

    hasil_tuning = []
    for bobot in KANDIDAT_BOBOT:
        engine = CBFEngine(
            df=train_df,
            bobot_tipe_kulit=bobot[0], bobot_masalah_kulit=bobot[1],
            bobot_kategori=bobot[2], bobot_kandungan=bobot[3], bobot_deskripsi=bobot[4],
        )
        skor = evaluasi_di_set(engine, val_df)
        if skor is None:
            continue
        skor["bobot"] = bobot
        hasil_tuning.append(skor)

    if not hasil_tuning:
        if verbose:
            print("  Tidak ada kombinasi bobot yang menghasilkan query valid di validation -- putaran dilewati.")
        return None

    for h in hasil_tuning:
        h["seed"] = seed

    terbaik = max(hasil_tuning, key=lambda h: h[f"ndcg@{K}"])
    if verbose:
        print(f"  Bobot terbaik di validation (seed={seed}): {terbaik['bobot']} "
              f"(ndcg@{K}={terbaik[f'ndcg@{K}']:.4f})")

    engine_final = CBFEngine(
        df=train_df,
        bobot_tipe_kulit=terbaik["bobot"][0], bobot_masalah_kulit=terbaik["bobot"][1],
        bobot_kategori=terbaik["bobot"][2], bobot_kandungan=terbaik["bobot"][3],
        bobot_deskripsi=terbaik["bobot"][4],
    )
    skor_test = evaluasi_di_set(engine_final, test_df)
    if skor_test is None:
        if verbose:
            print("  Tidak ada query valid di test set -- putaran dilewati.")
        return None
    skor_train = evaluasi_di_set(engine_final, train_df, exclude_self=True)
    skor_val = {kunci: terbaik[kunci] for kunci in skor_test if kunci in terbaik}

    baris = []
    for nama_set, skor in (("training", skor_train), ("validasi", skor_val), ("testing", skor_test)):
        baris.append({"seed": seed, "set": nama_set, "bobot_terpilih": terbaik["bobot"], **skor})
        if verbose:
            print(f"  {nama_set.upper():<9}(seed={seed}): n_query={skor['n_query']:<4} "
                  f"precision@{K}={skor[f'precision@{K}']:.4f}  "
                  f"recall_dalam_kolam={skor['recall_dalam_kolam']:.4f}  "
                  f"f1={skor['f1']:.4f}  ndcg@{K}={skor[f'ndcg@{K}']:.4f}")
    if verbose:
        print()
    return baris, hasil_tuning


def main():
    df = pd.read_csv(DATA_FILE)
    print(f"Data: {len(df)} produk. Evaluasi split 60/20/20, diulang {len(DAFTAR_SEED)}x "
          f"dengan kocokan data (seed) beda-beda: {DAFTAR_SEED}\n")

    semua_hasil = []
    semua_tuning = []
    for seed in DAFTAR_SEED:
        print(f"=== PUTARAN seed={seed} ===")
        keluaran = jalankan_satu_putaran(df, seed)
        if keluaran is not None:
            baris, hasil_tuning = keluaran
            semua_hasil.extend(baris)
            semua_tuning.extend(hasil_tuning)

    if not semua_hasil:
        print("Tidak ada putaran yang berhasil menghasilkan evaluasi -- cek data.")
        return

    ringkasan = pd.DataFrame(semua_hasil)
    kolom_metrik = [f"precision@{K}", "recall_dalam_kolam", "f1", f"ndcg@{K}"]
    urutan_set = ["training", "validasi", "testing"]

    print("=== HASIL PER PUTARAN (training / validasi / testing) ===")
    print(ringkasan[["seed", "set", "bobot_terpilih", "n_query"] + kolom_metrik].to_string(index=False))

    n_putaran = ringkasan["seed"].nunique()
    print(f"\n=== RATA-RATA DARI {n_putaran} PUTARAN per set (angka testing yang dilaporkan sebagai hasil akhir) ===")
    rata = ringkasan.groupby("set")[kolom_metrik].mean().reindex(urutan_set)
    std = ringkasan.groupby("set")[kolom_metrik].std().reindex(urutan_set)
    tabel = rata.round(4).astype(str) + " +/- " + std.round(4).astype(str)
    print(tabel.to_string())

    print(f"\nCatatan cara baca: angka '+/- std' yang kecil (mis. < 0,03) artinya hasilnya STABIL "
          f"walau data dikocok beda-beda -- bukan kebetulan 1 kali kocokan yang bagus.\n"
          f"Training dievaluasi TANPA self-match (produk query tidak boleh merekomendasikan "
          f"dirinya sendiri). Selisih kecil training vs testing = sistem tidak overfit.")

    # bukti pengacakan: tiap seed benar-benar menghasilkan isi test set yang beda
    test_ids = {s: set(split_data(df, s)[2]["id"]) for s in DAFTAR_SEED}
    print("\n=== BUKTI PENGACAKAN: irisan produk test set antar seed ===")
    for i, s1 in enumerate(DAFTAR_SEED):
        for s2 in DAFTAR_SEED[i + 1:]:
            irisan = len(test_ids[s1] & test_ids[s2])
            print(f"  seed {s1} vs seed {s2}: {irisan} dari {len(test_ids[s1])} produk sama "
                  f"({irisan/len(test_ids[s1]):.1%}) -- sisanya beda")

    out_file = Path("data/hasil_evaluasi_cbf_split.csv")
    ringkasan.to_csv(out_file, index=False)
    print(f"\n-> hasil per putaran disimpan ke {out_file}")

    # --- Bobot FINAL yang dipakai chatbot, dievaluasi dengan bobot yang SAMA di
    # ketiga seed (angka di atas memakai bobot terbaik masing-masing seed)
    final = []
    for seed in DAFTAR_SEED:
        train_df, val_df, test_df = split_data(df, seed)
        engine = CBFEngine(df=train_df, bobot_tipe_kulit=BOBOT_FINAL[0], bobot_masalah_kulit=BOBOT_FINAL[1],
                           bobot_kategori=BOBOT_FINAL[2], bobot_kandungan=BOBOT_FINAL[3], bobot_deskripsi=BOBOT_FINAL[4])
        for nama_set, data, tanpa_diri in (("training", train_df, True), ("validasi", val_df, False),
                                           ("testing", test_df, False)):
            final.append({"seed": seed, "set": nama_set, "bobot": str(BOBOT_FINAL),
                          **evaluasi_di_set(engine, data, exclude_self=tanpa_diri)})
    final_df = pd.DataFrame(final)
    print(f"\n=== BOBOT FINAL CHATBOT {BOBOT_FINAL} -- bobot sama di semua seed ===")
    print(final_df[["seed", "set", "n_query"] + kolom_metrik].round(4).to_string(index=False))
    rata = final_df.groupby("set")[kolom_metrik].mean().reindex(urutan_set)
    std = final_df.groupby("set")[kolom_metrik].std().reindex(urutan_set)
    print("\nRata-rata 3 seed:")
    print((rata.round(4).astype(str) + " +/- " + std.round(4).astype(str)).to_string())
    final_file = Path("data/hasil_evaluasi_bobot_final.csv")
    final_df.to_csv(final_file, index=False)
    print(f"-> disimpan ke {final_file}")

    # --- Tabel PARETO: rata-rata performa TIAP kombinasi bobot yang dicoba
    # di validation (lintas putaran), untuk melihat trade-off antar kombinasi
    # (tidak hanya pemenangnya) dan kombinasi mana yang "Pareto-optimal" (tidak
    # ada kombinasi lain yang lebih baik di SEMUA metrik sekaligus).
    tuning_df = pd.DataFrame(semua_tuning)
    tuning_df["bobot_str"] = tuning_df["bobot"].apply(str)
    pareto = tuning_df.groupby("bobot_str")[kolom_metrik].mean().round(4)
    pareto = pareto.reset_index().sort_values(f"ndcg@{K}", ascending=False)

    def cek_pareto_optimal(baris, semua):
        for _, lain in semua.iterrows():
            if lain["bobot_str"] == baris["bobot_str"]:
                continue
            lebih_baik_semua = all(lain[k] >= baris[k] for k in kolom_metrik)
            ada_yg_lebih_baik = any(lain[k] > baris[k] for k in kolom_metrik)
            if lebih_baik_semua and ada_yg_lebih_baik:
                return False  # ada kombinasi lain yang mendominasi -- bukan optimal
        return True

    pareto["pareto_optimal"] = pareto.apply(lambda b: cek_pareto_optimal(b, pareto), axis=1)

    print(f"\n=== TABEL PARETO -- rata-rata VALIDATION tiap kombinasi bobot (lintas {len(DAFTAR_SEED)} putaran) ===")
    print(pareto.to_string(index=False))
    print("\n'pareto_optimal=True' artinya nggak ada kombinasi lain yang menang di SEMUA metrik "
          "sekaligus -- kombinasi itu punya trade-off tersendiri (unggul di 1+ metrik), bukan kalah total.")

    pareto_file = Path("data/hasil_pareto_bobot_cbf.csv")
    pareto.to_csv(pareto_file, index=False)
    print(f"-> tabel pareto disimpan ke {pareto_file}")


if __name__ == "__main__":
    main()
