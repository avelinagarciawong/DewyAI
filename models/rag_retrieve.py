"""
rag_retrieve.py

Mengambil potongan ulasan Shopee/opini X yang relevan dari index RAG (dibangun
oleh bangun_rag_index.py). Dipanggil backend untuk memberi KONTEKS TAMBAHAN
kepada LLM, di luar Top-N hasil CBF (cbf_engine.py).

ALUR DI BACKEND (ringkas):
  1. Pesan pengguna -> profil (tipe kulit, masalah kulit, budget) -> CBF
     (cbf_engine.py) -> Top-N produk kandidat.
  2. Untuk tiap produk kandidat, ambil_konteks() mengambil 3-5 potongan ulasan/
     opini asli yang paling relevan dengan pertanyaan/keluhan pengguna.
  3. Top-N produk dan potongan ulasan digabung menjadi satu prompt untuk LLM
     (lewat Groq) yang menyusun jawaban natural.

SYARAT: bangun_rag_index.py harus sudah dijalankan (membuat folder
data/chroma_db/); bila belum, skrip ini berhenti dengan pesan yang jelas.

CATATAN ChromaDB (versi 1.5.9): filter `where` dengan lebih dari satu kondisi
harus dibungkus operator `$and`; dict datar (mis. {"link_produk":.., "sumber":..})
ditolak dengan error "Expected where to have exactly one operator". Ditangani di
_bangun_where().

CARA PAKAI:
    from rag_retrieve import RAGRetriever
    retriever = RAGRetriever()
    konteks = retriever.ambil_konteks(
        query="apakah bikin iritasi di kulit sensitif?",
        link_produk="https://shopee.co.id/...",  # opsional -- kosongin buat cari di semua produk
        n_hasil=5,
    )
    for k in konteks:
        print(k["sentimen"], k["teks"])
"""
from pathlib import Path

CHROMA_DIR = Path("data/chroma_db")
NAMA_KOLEKSI = "ulasan_dan_x"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


def _bangun_where(link_produk=None, sumber=None, sentimen=None):
    """ChromaDB 1.5.9 menolak where berupa dict datar bila ada >1 kondisi (wajib
    dibungkus $and), tetapi juga menolak $and berisi satu kondisi (harus dict
    polos). Karena itu ketiga kasus (0, 1, >1 kondisi) ditangani terpisah."""
    kondisi = []
    if link_produk:
        kondisi.append({"link_produk": link_produk})
    if sumber:
        kondisi.append({"sumber": sumber})
    if sentimen:
        # label di index tidak seragam hurufnya ("Positif" dari ulasan Shopee,
        # "positif" dari post X) -> cocokkan dua-duanya
        kondisi.append({"sentimen": {"$in": [sentimen.capitalize(), sentimen.lower()]}})
    if not kondisi:
        return None
    if len(kondisi) == 1:
        return kondisi[0]
    return {"$and": kondisi}


class RAGRetriever:
    def __init__(self):
        if not CHROMA_DIR.exists():
            raise FileNotFoundError(
                f"{CHROMA_DIR} belum ada. Jalankan `python bangun_rag_index.py` dulu "
                f"buat bikin index RAG-nya."
            )
        from sentence_transformers import SentenceTransformer
        import chromadb

        self.model = SentenceTransformer(MODEL_NAME)
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self.koleksi = client.get_collection(NAMA_KOLEKSI)

    def ambil_konteks(self, query, link_produk=None, sumber=None, n_hasil=5, sentimen=None):
        """
        query: pertanyaan/keluhan pengguna dalam bahasa natural (bukan sekadar
               kata kunci) -- mis. "apakah cocok buat kulit berminyak
               dan gampang jerawatan?".
        link_produk: bila diisi, hanya mencari ulasan/opini yang terkait produk
               itu (paling umum dipakai -- "apa kata orang tentang produk INI").
        sumber: "ulasan_shopee" atau "x", opsional -- filter sumber.
        n_hasil: jumlah potongan yang dikembalikan.
        sentimen: "Positif" / "Netral" / "Negatif", opsional -- hanya mengambil
               ulasan dengan label sentimen itu (mis. "keluhan orang apa aja?").

        return: list of dict {teks, sumber, link_produk, sentimen, rating}
                diurutkan dari yang paling mirip makna ke query.
        """
        vektor_query = self.model.encode([query])[0].tolist()
        where = _bangun_where(link_produk, sumber, sentimen)

        hasil = self.koleksi.query(query_embeddings=[vektor_query], n_results=n_hasil, where=where)
        if not hasil["ids"][0]:
            return []

        potongan = []
        for dok, meta in zip(hasil["documents"][0], hasil["metadatas"][0]):
            potongan.append({"teks": dok, **meta})
        return potongan


if __name__ == "__main__":
    retriever = RAGRetriever()
    print("=== Uji coba: cari opini soal 'bikin iritasi di kulit sensitif' (semua produk) ===")
    for h in retriever.ambil_konteks("apakah bikin iritasi di kulit sensitif?", n_hasil=5):
        print(f"  [{h['sumber']} | {h['sentimen']}] {h['teks'][:100]}")
