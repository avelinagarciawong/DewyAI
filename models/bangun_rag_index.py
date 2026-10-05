"""
bangun_rag_index.py

Membangun index RAG: ulasan Shopee dan post X diubah menjadi embedding (vektor
makna kalimat) lalu disimpan ke ChromaDB lokal di disk. Backend memakainya untuk
mengambil potongan ulasan/opini asli yang relevan sebagai konteks tambahan bagi
LLM, terpisah dari Top-N hasil CBF (cbf_engine.py); keduanya digabung saat prompt
disusun.

Embedding dihitung lokal, sekali di awal (bukan setiap ada chat), sehingga tidak
terkena batas kuota API. Model: paraphrase-multilingual-MiniLM-L12-v2 (~420 MB,
diunduh sekali lalu disimpan di cache), mendukung bahasa Indonesia dan bahasa
lain untuk ulasan campuran.

Isi dokumen ulasan memakai kolom `teks_bebas` (sudah dipisahkan dari label
terstruktur "Tekstur:.. Performa:.."), bukan `teks_ulasan` mentah, agar kutipan
yang diteruskan LLM ke pengguna terbaca wajar.

SUMBER DATA:
  - data/clean_merged_produk_ulasan_labelled_v2.csv (ulasan Shopee): 26.877 baris,
    kolom `teks_bebas`; teks kurang dari 8 karakter (mis. "bagus", "ok") dibuang
    karena terlalu pendek untuk menjadi konteks.
  - Post X (493 baris): hanya sebagian yang terkait link produk tertentu
    (link_rekomendasi); sisanya opini umum tentang skincare, tetap disimpan dengan
    metadata link_produk kosong.
    data/clean_x.csv memuat username dan url akun X sehingga tidak di-upload ke
    repo. Index dibangun dari data/x_untuk_rag.csv: hanya kolom yang dipakai
    (teks, link_rekomendasi, sentimen) dan setiap @akun di teks diganti "@akun",
    sehingga LLM juga tidak pernah mengutip nama akun orang. File anonim ini dibuat
    ulang dari clean_x.csv setiap skrip dijalankan (bila clean_x.csv ada) dan ikut
    di-upload, sehingga repo hasil clone tetap dapat membangun index.

CARA PAKAI (dari root repo):
    python models/bangun_rag_index.py
Output: folder data/chroma_db/ (tersimpan di disk). Koleksi lama dihapus dan
dibangun ulang setiap skrip dijalankan.
"""
import re
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data")
ULASAN_FILE = DATA_DIR / "clean_merged_produk_ulasan_labelled_v2.csv"
X_FILE = DATA_DIR / "clean_x.csv"           # hasil cleaning, ada username & url -- tidak di-upload
X_FILE_RAG = DATA_DIR / "x_untuk_rag.csv"   # versi anonim yang dipakai index & ikut di-upload
KOLOM_X_RAG = ["teks", "link_rekomendasi", "sentimen"]
CHROMA_DIR = DATA_DIR / "chroma_db"
NAMA_KOLEKSI = "ulasan_dan_x"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
PANJANG_MIN_TEKS = 8  # buang teks yg kependekan buat jadi konteks berarti


def bersihkan_teks(t):
    if pd.isna(t):
        return ""
    return re.sub(r"\s+", " ", str(t)).strip()


def siapkan_dokumen_ulasan():
    df = pd.read_csv(ULASAN_FILE)
    # teks_bebas (sudah dipisah dari label terstruktur di cleaning_data.py), bukan
    # teks_ulasan mentah yang masih diawali "Tekstur:.. Performa:.."
    teks = df["teks_bebas"].apply(bersihkan_teks)
    valid = teks.str.len() >= PANJANG_MIN_TEKS
    df = df[valid].reset_index(drop=True)
    teks = teks[valid].reset_index(drop=True)

    dokumen, metadatas, ids = [], [], []
    for i, row in df.iterrows():
        dokumen.append(teks[i])
        metadatas.append({
            "sumber": "ulasan_shopee",
            "link_produk": str(row.get("link", "") or ""),
            "sentimen": str(row.get("sentimen_prediksi", "") or ""),
            "rating": float(row["rating_ulasan"]) if pd.notna(row.get("rating_ulasan")) else -1.0,
        })
        ids.append(f"ulasan_{i}")
    return dokumen, metadatas, ids


def perbarui_x_anonim():
    """clean_x.csv -> x_untuk_rag.csv: buang username/url/tweet_id, samarkan @akun di teks.
    Tanpa clean_x.csv (repo hasil clone) dipakai x_untuk_rag.csv yang sudah ada."""
    if not X_FILE.exists():
        return
    df = pd.read_csv(X_FILE)[KOLOM_X_RAG]
    df["teks"] = df["teks"].apply(lambda t: re.sub(r"@\w+", "@akun", t) if isinstance(t, str) else t)
    df.to_csv(X_FILE_RAG, index=False)


def siapkan_dokumen_x():
    perbarui_x_anonim()
    df = pd.read_csv(X_FILE_RAG)
    teks = df["teks"].apply(bersihkan_teks)
    valid = teks.str.len() >= PANJANG_MIN_TEKS
    df = df[valid].reset_index(drop=True)
    teks = teks[valid].reset_index(drop=True)

    dokumen, metadatas, ids = [], [], []
    for i, row in df.iterrows():
        link = row.get("link_rekomendasi", "")
        link = str(link) if pd.notna(link) else ""
        dokumen.append(teks[i])
        metadatas.append({
            "sumber": "x",
            "link_produk": link,  # kosong bila post tidak terkait produk tertentu
            "sentimen": str(row.get("sentimen", "") or ""),
            "rating": -1.0,  # X tidak punya rating; -1 berarti "tidak berlaku"
        })
        ids.append(f"x_{i}")
    return dokumen, metadatas, ids


def main():
    print("Menyiapkan dokumen dari ulasan Shopee + post X...")
    dok_ulasan, meta_ulasan, id_ulasan = siapkan_dokumen_ulasan()
    dok_x, meta_x, id_x = siapkan_dokumen_x()
    print(f"  ulasan Shopee valid : {len(dok_ulasan)}")
    print(f"  post X valid        : {len(dok_x)}")

    semua_dokumen = dok_ulasan + dok_x
    semua_meta = meta_ulasan + meta_x
    semua_id = id_ulasan + id_x
    print(f"  total dokumen       : {len(semua_dokumen)}")

    print(f"\nMemuat model embedding ({MODEL_NAME})...")
    print("(sekali download lalu dicache lokal -- butuh koneksi internet cuma di run pertama)")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)

    print("\nMengubah dokumen jadi embedding (bisa beberapa menit tergantung laptop)...")
    embeddings = model.encode(semua_dokumen, batch_size=64, show_progress_bar=True)

    print("\nMenyimpan ke ChromaDB lokal...")
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(NAMA_KOLEKSI)
        print(f"  (koleksi '{NAMA_KOLEKSI}' lama ditemukan & dihapus dulu, biar ga dobel)")
    except Exception:
        pass
    koleksi = client.create_collection(NAMA_KOLEKSI)

    # ChromaDB (backend SQLite) nolak nambah >5461 dokumen sekaligus dlm 1 panggilan
    # add() -- makanya dimasukin per-batch, bukan sekali semua.
    BATCH = 5000
    for start in range(0, len(semua_dokumen), BATCH):
        end = min(start + BATCH, len(semua_dokumen))
        koleksi.add(
            ids=semua_id[start:end],
            embeddings=embeddings[start:end].tolist(),
            documents=semua_dokumen[start:end],
            metadatas=semua_meta[start:end],
        )
        print(f"  tersimpan {end}/{len(semua_dokumen)}")

    print(f"\n-> selesai. Database tersimpan di {CHROMA_DIR}/ ({koleksi.count()} dokumen)")
    print("Lanjut ke rag_retrieve.py buat coba narik balik konteks dari database ini.")


if __name__ == "__main__":
    main()
