"""
cbf_engine.py

Mesin Content-Based Filtering (CBF) untuk rekomendasi produk skincare,
sesuai proposal Bab II 2.1.2 & Bab III: TF-IDF atas karakteristik item
(deskripsi, kategori, kandungan bahan) + cosine similarity terhadap
profil preferensi pengguna (tipe kulit, masalah kulit, budget).

CARA KERJA (singkat):
  1. Tiap produk digabung jadi satu "teks gabungan" isinya tipe_kulit_cocok,
     masalah_kulit_cocok, kategori, kandungan, deskripsi -- tag terstruktur
     (tipe_kulit_cocok, masalah_kulit_cocok) DIULANG beberapa kali di teks
     gabungan supaya bobotnya lebih besar daripada teks bebas (deskripsi),
     karena profil pengguna hanya diisi dari tag ini (bukan kalimat bebas).
  2. Deskripsi (teks bebas Bahasa Indonesia) dibersihkan dari stopword dan
     di-stem pakai Sastrawi -- supaya "melembapkan"/"kelembapan"/"lembap"
     dianggap kata yang sama, dan kata umum ("yang", "untuk", "dengan")
     tidak ikut menjadi sinyal TF-IDF. Tag terstruktur (tipe_kulit_cocok,
     masalah_kulit_cocok, kategori) SENGAJA TIDAK di-stem -- itu kosakata
     terkontrol (mis. "kemerahan_iritasi"), stemming malah bisa merusaknya.
  3. TfidfVectorizer di-fit ke seluruh teks gabungan produk -> tiap produk
     jadi 1 vektor TF-IDF.
  4. Profil pengguna (tipe kulit + daftar masalah kulit dari onboarding)
     diubah jadi "kalimat" pakai kosakata yang sama (mis. tipe_kulit
     "kering" -> teks "kering kering kering kering"), lalu ditransform
     pakai vectorizer YANG SAMA -> jadi 1 vektor di ruang yang sama.
  5. Cosine similarity antara vektor pengguna vs semua vektor produk ->
     itu skor kecocokan CBF.
  6. Budget & kategori (kalau user minta kategori spesifik lewat chat)
     diterapkan sebagai FILTER KERAS sebelum ranking -- bukan ikut masuk
     ke similarity, karena ini preferensi pasti (bukan soal "mirip").
  7. Hasil akhir: Top-N produk dengan skor similarity tertinggi di antara
     yang lolos filter.

KETERBATASAN YANG PERLU DICATAT DI SKRIPSI (Bab III/IV, evaluasi):
  - 145/984 produk (14,7%) tipe_kulit_cocok kosong, 55/984 (5,6%)
    masalah_kulit_cocok kosong (sudah lewat llm_fallback tapi tetap
    gagal). Produk ini TIDAK
    dibuang, tetapi similarity-nya hanya mengandalkan kategori/kandungan/
    deskripsi -- kemungkinan skornya lebih rendah / kalah ranking
    dibanding produk yang tag-nya lengkap. Ini bias yang harus diakui,
    bukan disembunyikan.
  - 481/984 (48,9%) kandungan kosong -- karena itu deskripsi tetap
    dimasukkan ke teks gabungan sebagai sinyal cadangan.
  - 54/984 harga kosong (NaN) -- bila pengguna memberi batas budget, produk
    ini otomatis TIDAK muncul (skema "aman": tidak yakin harganya,
    jangan direkomendasikan sebagai "sesuai budget").
  - Produk dengan harga_outlier=True (kalaupun muncul lagi di scraping
    berikutnya) SELALU dibuang dari recommend(), ada filter budget atau
    tidak; harganya juga dikosongkan di self.df (asli di harga_asli) supaya
    tidak ikut ke perhitungan apa pun -- lihat _tandai_harga_outlier().

CARA PAKAI:
    python cbf_engine.py          # jalanin demo/self-test di bawah
    # atau import:
    from cbf_engine import CBFEngine
    engine = CBFEngine("data/products_final.csv")
    hasil = engine.recommend(tipe_kulit="kering",
                              masalah_kulit=["jerawat", "kusam"],
                              budget_max=100000, top_n=10)
"""
import re
import pandas as pd
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
from Sastrawi.StopWordRemover.StopWordRemoverFactory import StopWordRemoverFactory

DATA_FILE = Path("data/products_final.csv")

# Berapa kali tag terstruktur diulang di teks gabungan, supaya bobotnya
# lebih besar daripada kata-kata bebas di deskripsi/kandungan. Angka ini
# heuristik awal -- kalau nanti dievaluasi (precision/recall/F1/NDCG,
# lihat proposal Bab III) dan hasilnya kurang bagus, ini yang pertama
# dituning.
# Riwayat: 4/4/2/2/1 -> 6/4/2/2/1 (tipe kulit dinaikkan: masalah kulit boleh
# >1 pilihan, jadi dengan bobot sama similarity-nya "menang" atas tipe kulit)
# -> 4/4/4/2/1 (FINAL, 27 Sep 2026). Setelah data kategori dibersihkan lewat
# review manual (961 produk, 0 tanpa kategori), evaluasi 60/20/20 x 3 seed
# (models/evaluasi_cbf_split.py) memilih 4/4/4/2/1 di 2 dari 3 seed dengan
# kriteria NDCG@10 validasi tertinggi (rata-rata 0.8367 vs 0.8309). Uji
# berdampingan di test set: NDCG@10 0.8589 vs 0.8397, precision@10 0.8443 vs
# 0.8360; 6/4/2/2/1 sedikit unggul di recall (0.3384 vs 0.3327) & lebih stabil
# antar seed -- trade-off ini ditulis di pembahasan skripsi.
BOBOT_TIPE_KULIT = 4
BOBOT_MASALAH_KULIT = 4
BOBOT_KATEGORI = 4
BOBOT_KANDUNGAN = 2
BOBOT_DESKRIPSI = 1

# 'link' dibutuhkan generate_jawaban.py untuk menghubungkan hasil CBF ke RAG
# (agar ulasan yang diambil memang milik produk yang direkomendasikan)
KOLOM_TAMPIL = [
    "id", "nama_produk", "link", "brand", "kategori", "harga", "harga_outlier",
    "tipe_kulit_cocok", "masalah_kulit_cocok", "kandungan", "rating",
    "skor_sentimen", "jml_ulasan", "skor_cbf",
]

TIPE_KULIT_VALID = {"berminyak", "kering", "kombinasi", "sensitif", "normal"}
# sama dengan pipeline/cleaning_data.py -- harga di atas ini bukan harga produk
# beneran (listing "FREE GIFT / DO NOT ORDER" berharga Rp1 miliar)
HARGA_OUTLIER_THRESHOLD = 10_000_000
MASALAH_KULIT_VALID = {
    "jerawat", "kusam", "hiperpigmentasi", "penuaan",
    "kemerahan_iritasi", "dehidrasi",
}

# Sastrawi -- dibuat sekali di level modul (bukan per baris/per panggilan)
# karena factory-nya lumayan berat buat dibangun ulang tiap kali.
_stemmer = StemmerFactory().create_stemmer()
_stopword_remover = StopWordRemoverFactory().create_stop_word_remover()


def _bersihkan_tag(teks: str) -> str:
    """'kering; sensitif; normal' -> 'kering sensitif normal'."""
    if pd.isna(teks) or not str(teks).strip():
        return ""
    return " ".join(t.strip() for t in str(teks).split(";") if t.strip())


def _bersihkan_kandungan(teks: str) -> str:
    """'AHA BHA PHA, Centella Asiatica' -> 'aha bha pha centella asiatica'.
    Tidak di-stem -- ini nama bahan/INCI, bukan kalimat Bahasa Indonesia,
    stemming hanya akan merusak nama bahan (mis. 'niacinamide' terpotong)."""
    if pd.isna(teks) or not str(teks).strip():
        return ""
    return re.sub(r"[,\|]+", " ", str(teks)).lower()


# hasil stemming per teks deskripsi -- stemming Sastrawi ~3,5 detik untuk
# seluruh katalog, padahal saat admin menambah/mengubah 1 produk (index
# di-fit ulang) deskripsi produk lain tidak berubah
_cache_stem = {}


def _bersihkan_teks_bebas(teks: str) -> str:
    """Deskripsi produk (kalimat bebas Bahasa Indonesia) -> lowercase,
    buang stopword ('yang', 'untuk', 'dengan', dst), lalu stem tiap kata
    ke kata dasarnya ('melembapkan'/'kelembapan' -> 'lembap'). Dengan begitu
    TF-IDF menangkap makna yang sama walau bentuk katanya berbeda."""
    if pd.isna(teks) or not str(teks).strip():
        return ""
    teks = str(teks)
    hasil = _cache_stem.get(teks)
    if hasil is None:
        hasil = _cache_stem[teks] = _stemmer.stem(_stopword_remover.remove(teks.lower()))
    return hasil


class CBFEngine:
    def __init__(self, data_path=DATA_FILE, df=None, stem_deskripsi=True,
                 bobot_tipe_kulit=BOBOT_TIPE_KULIT, bobot_masalah_kulit=BOBOT_MASALAH_KULIT,
                 bobot_kategori=BOBOT_KATEGORI, bobot_kandungan=BOBOT_KANDUNGAN,
                 bobot_deskripsi=BOBOT_DESKRIPSI):
        """
        data_path / df: kasih SALAH SATU. data_path (default) baca CSV dari
            disk -- dipakai buat penggunaan normal (1 file utuh). df dipakai
            buat kasih DataFrame yang sudah di-split di memori (mis. subset
            training hasil train/val/test split) tanpa perlu ditulis ke CSV
            dulu -- dibutuhkan evaluasi_cbf_split.py.
        bobot_*: override bobot per-instance (default-nya = konstanta modul
            di atas). Dibutuhkan buat tuning hyperparameter di validation
            set -- tiap kombinasi bobot yang dicoba butuh instance
            CBFEngine sendiri dengan bobot beda, TANPA harus edit konstanta
            modul (yang sifatnya global/shared).
        stem_deskripsi=False untuk melewati stemming (inisialisasi lebih cepat,
            cocok untuk eksperimen/debug) -- default True karena kualitas
            pencocokan lebih baik dan hanya dijalankan sekali saat startup,
            bukan per request.
        """
        self.bobot_tipe_kulit = bobot_tipe_kulit
        self.bobot_masalah_kulit = bobot_masalah_kulit
        self.bobot_kategori = bobot_kategori
        self.bobot_kandungan = bobot_kandungan
        self.bobot_deskripsi = bobot_deskripsi
        self.stem_deskripsi = stem_deskripsi
        self.versi = 0
        self.muat_ulang(df if df is not None else pd.read_csv(data_path))

    def muat_ulang(self, df):
        """Bangun ulang index TF-IDF dari data produk yang baru -- dipanggil
        panel admin setiap kali produk ditambah/diubah/dinonaktifkan, supaya
        perubahan LANGSUNG berlaku di rekomendasi (tidak hanya tersimpan di
        database). Data, vectorizer, dan matriks diganti dalam SATU assignment:
        request chat yang sedang berjalan tetap memakai versi lama yang utuh,
        tidak pernah campuran data baru dengan matriks lama."""
        df = df.copy().reset_index(drop=True)
        self._tandai_harga_outlier(df)
        df["_korpus"] = self._korpus(df)
        self._indeks = (df, *self._fit_vectorizer(df["_korpus"]))
        self.versi += 1

    @property
    def df(self):
        return self._indeks[0]

    @property
    def vectorizer(self):
        return self._indeks[1]

    @property
    def matrix(self):
        return self._indeks[2]

    @staticmethod
    def _tandai_harga_outlier(df):
        """harga_outlier = flag dari pipeline (cleaning_data.py) ATAU harga di
        atas HARGA_OUTLIER_THRESHOLD -- jadi tetap tertangkap walau data hasil
        refresh berikutnya kolomnya hilang/belum diisi. Harganya disimpan di
        harga_asli, kolom harga dikosongkan: harga "Rp1 miliar" (listing DO NOT
        ORDER) tidak boleh ikut ke filter budget, pengurutan harga, skor, dst."""
        flag = df["harga_outlier"].fillna(False).astype(bool) if "harga_outlier" in df else False
        df["harga_outlier"] = flag | (df["harga"] > HARGA_OUTLIER_THRESHOLD)
        df["harga_asli"] = df["harga"]
        df.loc[df["harga_outlier"], "harga"] = float("nan")

    def _korpus(self, df):
        tipe = df["tipe_kulit_cocok"].apply(_bersihkan_tag)
        masalah = df["masalah_kulit_cocok"].apply(_bersihkan_tag)
        kategori = df["kategori"].fillna("").astype(str).str.lower()
        kandungan = df["kandungan"].apply(_bersihkan_kandungan)
        if self.stem_deskripsi:
            deskripsi = df["deskripsi"].apply(_bersihkan_teks_bebas)
        else:
            deskripsi = df["deskripsi"].fillna("").astype(str).str.lower()

        korpus = (
            ((tipe + " ") * self.bobot_tipe_kulit)
            + ((masalah + " ") * self.bobot_masalah_kulit)
            + ((kategori + " ") * self.bobot_kategori)
            + ((kandungan + " ") * self.bobot_kandungan)
            + ((deskripsi + " ") * self.bobot_deskripsi)
        )
        return korpus.astype(str).str.strip()

    @staticmethod
    def _fit_vectorizer(korpus):
        """return: (vectorizer, matrix), atau (None, None) kalau belum ada
        produk sama sekali (instalasi baru) -- recommend() lalu balik kosong,
        bukan error."""
        vectorizer = TfidfVectorizer(
            lowercase=True,
            token_pattern=r"(?u)\b[a-zA-Z_][a-zA-Z_]+\b",  # buang token angka murni
            min_df=1,
        )
        try:
            return vectorizer, vectorizer.fit_transform(korpus)
        except ValueError:  # korpus kosong -> "empty vocabulary"
            return None, None

    def _profil_pengguna_ke_teks(self, tipe_kulit=None, masalah_kulit=None):
        bagian = []
        if tipe_kulit:
            tipe_kulit = tipe_kulit.strip().lower()
            if tipe_kulit not in TIPE_KULIT_VALID:
                raise ValueError(
                    f"tipe_kulit '{tipe_kulit}' tidak dikenal. Pilihan valid: {sorted(TIPE_KULIT_VALID)}"
                )
            bagian.append((tipe_kulit + " ") * self.bobot_tipe_kulit)
        if masalah_kulit:
            for m in masalah_kulit:
                m = m.strip().lower()
                if m not in MASALAH_KULIT_VALID:
                    raise ValueError(
                        f"masalah_kulit '{m}' tidak dikenal. Pilihan valid: {sorted(MASALAH_KULIT_VALID)}"
                    )
                bagian.append((m + " ") * self.bobot_masalah_kulit)
        return " ".join(bagian).strip()

    def recommend(self, tipe_kulit=None, masalah_kulit=None,
                   budget_max=None, budget_min=None, kategori=None, top_n=10,
                   wajib_cocok_tipe_kulit=True, hanya_relevan=False):
        """
        tipe_kulit: salah satu dari TIPE_KULIT_VALID, atau None.
        masalah_kulit: list dari MASALAH_KULIT_VALID (boleh lebih dari 1), atau None.
        budget_max: harga maksimum (Rupiah). Produk dengan harga kosong (NaN)
                    ikut DIBUANG kalau budget_max ATAU budget_min diisi -- lihat
                    catatan di docstring atas. Produk dengan harga_outlier=True
                    ikut dibuang juga (harganya tidak masuk akal, mis. listing
                    "DO NOT ORDER" -- jangan sampai lolos filter budget hanya
                    karena kebetulan angkanya di luar jangkauan).
        budget_min: harga minimum (Rupiah), opsional -- dipakai kalau user minta
                    produk "di atas harga X" lewat chat (lihat nlu.py:
                    ekstrak_budget). Bukan bagian dari onboarding awal
                    (onboarding hanya memiliki budget_max).
        kategori: filter kategori produk (exact match, case-insensitive), opsional --
                  dipakai kalau chatbot mendeteksi user minta kategori spesifik
                  (mis. "carikan sunscreen"), BUKAN bagian dari onboarding awal.
        top_n: jumlah rekomendasi yang dikembalikan.
        wajib_cocok_tipe_kulit: kalau True (default) dan tipe_kulit diisi,
            produk yang tipe_kulit_cocok-nya TERISI tapi TIDAK memuat tipe
            kulit pengguna DIBUANG lebih dulu (sebelum ranking), bukan sekadar
            diberi skor cosine yang kebetulan rendah. Produk yang
            tipe_kulit_cocok-nya KOSONG tetap boleh lolos (dianggap belum
            diketahui, bukan "tidak cocok").

            KENAPA INI PENTING (lihat CATATAN DESAIN di bawah __main__):
            cosine similarity murni hanya "menghargai" kata yang sama-sama
            muncul, tidak pernah "menghukum" kata yang beda. Akibatnya
            produk untuk kulit berminyak bisa berada di atas untuk pengguna
            kulit kering, asal kecocokan masalah_kulit-nya kuat. Untuk
            chatbot yang tujuannya "rekomendasi sesuai tipe kulit", itu
            kesalahan dari sisi tujuan produk meski benar secara matematis.
            Karena itu tipe_kulit dijadikan filter keras, sedangkan
            masalah_kulit tetap murni similarity (boleh hanya cocok
            sebagian, karena pengguna sering memilih >1 masalah kulit).
        hanya_relevan: kalau True, buang produk yang tidak relevan walau
            lolos filter lain: skor_cbf 0 (sama sekali tidak nyambung), atau
            tag masalah_kulit_cocok-nya TERISI tapi tidak memuat satu pun
            masalah kulit user (tag kosong tetap lolos = belum diketahui,
            sama seperti aturan tipe kulit). Definisinya sama dengan "relevan"
            di evaluasi_cbf_split.py. Dipakai chatbot supaya tidak menampilkan
            produk asal-asalan demi memenuhi jumlah yang diminta; default False
            supaya evaluasi yang sudah ada tidak berubah.

        return: DataFrame produk hasil filter + kolom skor_cbf, diurutkan
                dari skor tertinggi.
        """
        if not tipe_kulit and not masalah_kulit:
            raise ValueError("Minimal isi salah satu: tipe_kulit atau masalah_kulit.")

        teks_profil = self._profil_pengguna_ke_teks(tipe_kulit, masalah_kulit)
        df, vectorizer, matrix = self._indeks  # snapshot -- lihat muat_ulang()
        if vectorizer is None:
            return pd.DataFrame(columns=KOLOM_TAMPIL)
        vektor_profil = vectorizer.transform([teks_profil])
        skor = cosine_similarity(vektor_profil, matrix).flatten()

        hasil = df.copy()
        hasil["skor_cbf"] = skor

        if tipe_kulit and wajib_cocok_tipe_kulit:
            tipe_kulit_lower = tipe_kulit.strip().lower()
            tag_terisi = hasil["tipe_kulit_cocok"].notna() & (hasil["tipe_kulit_cocok"] != "")
            tag_cocok = hasil["tipe_kulit_cocok"].fillna("").str.lower().apply(
                lambda t: tipe_kulit_lower in [x.strip() for x in t.split(";")]
            )
            hasil = hasil[~tag_terisi | tag_cocok]

        # harga_outlier SELALU dibuang dari rekomendasi, bukan hanya saat ada
        # filter budget (user "tanpa batas budget" pun tidak boleh dapat listing
        # "DO NOT ORDER")
        hasil = hasil[~hasil["harga_outlier"]]
        if budget_max or budget_min:
            hasil = hasil[hasil["harga"].notna()]
            if budget_max:
                hasil = hasil[hasil["harga"] <= budget_max]
            if budget_min:
                hasil = hasil[hasil["harga"] >= budget_min]
        if kategori:
            hasil = hasil[hasil["kategori"].fillna("").str.lower() == kategori.strip().lower()]
        if hanya_relevan:
            hasil = hasil[hasil["skor_cbf"] > 0]
            if masalah_kulit:
                diminta = {m.strip().lower() for m in masalah_kulit}
                tag = hasil["masalah_kulit_cocok"].fillna("").str.lower()
                cocok = tag.apply(lambda t: bool(diminta & {x.strip() for x in t.split(";")}))
                hasil = hasil[(tag.str.strip() == "") | cocok]

        hasil = hasil.sort_values("skor_cbf", ascending=False).head(top_n)
        return hasil[KOLOM_TAMPIL].reset_index(drop=True)

    def ambil_produk(self, ids):
        """Produk berdasarkan daftar id, urutan dipertahankan (id yang tidak
        ada di data dilewati). Kolom sama dengan hasil recommend()."""
        per_id = self.df.set_index("id", drop=False)
        ada = [i for i in ids if i in per_id.index]
        hasil = per_id.loc[ada].copy()
        hasil["skor_cbf"] = float("nan")
        return hasil[KOLOM_TAMPIL].reset_index(drop=True)

    def bandingkan_produk(self, ids):
        """Atribut 2+ produk untuk dibandingkan berdampingan (satu baris per
        produk, urutan sama dengan ids). Nilai kosong dibiarkan NaN -- yang
        menampilkan ke user wajib menuliskannya sebagai "tidak ada data"."""
        per_id = self.df.set_index("id", drop=False)
        ada = [i for i in ids if i in per_id.index]
        kolom = ["id", "nama_produk", "brand", "kategori", "harga", "harga_outlier", "rating", "jml_ulasan",
                 "skor_sentimen", "tipe_kulit_cocok", "masalah_kulit_cocok", "kandungan", "link"]
        return per_id.loc[ada, kolom].reset_index(drop=True)


def _demo():
    engine = CBFEngine()
    print(f"Data dimuat: {len(engine.df)} produk, kosakata TF-IDF: {len(engine.vectorizer.vocabulary_)} term\n")

    kasus_uji = [
        dict(tipe_kulit="kering", masalah_kulit=["jerawat", "kusam"], budget_max=100_000),
        dict(tipe_kulit="berminyak", masalah_kulit=["jerawat"], budget_max=50_000),
        dict(tipe_kulit="sensitif", masalah_kulit=["kemerahan_iritasi", "dehidrasi"], budget_max=None),
        dict(tipe_kulit="kombinasi", masalah_kulit=["penuaan"], budget_max=200_000, kategori="serum"),
    ]

    for i, kasus in enumerate(kasus_uji, 1):
        print(f"=== Kasus uji {i}: {kasus} ===")
        hasil = engine.recommend(**kasus, top_n=5)
        if hasil.empty:
            print("  (tidak ada produk yang lolos filter -- cek kombinasi budget/kategori)")
        else:
            for _, r in hasil.iterrows():
                print(f"  [{r['skor_cbf']:.3f}] {r['nama_produk'][:60]:<60} "
                      f"Rp{r['harga']:>10,.0f}  ({r['kategori']}) "
                      f"tipe={r['tipe_kulit_cocok']!s:<25} masalah={r['masalah_kulit_cocok']}")
        print()

    print("=== Uji tambahan: produk dengan tipe_kulit_cocok KOSONG tetap bisa dapat skor > 0 ===")
    kosong = engine.df[engine.df["tipe_kulit_cocok"].isna() | (engine.df["tipe_kulit_cocok"] == "")]
    print(f"Jumlah produk tipe_kulit_cocok kosong: {len(kosong)}")
    contoh = kosong.iloc[0]
    print(f"Contoh: {contoh['nama_produk'][:60]} | kategori={contoh['kategori']} | kandungan={contoh['kandungan']}")


if __name__ == "__main__":
    _demo()
