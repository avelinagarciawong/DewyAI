"""
generate_jawaban.py

Titik penyatuan CBF + RAG + LLM, bagian terakhir arsitektur tiga komponen (CBF
memilih produk, RAG mengambil bukti ulasan asli, LLM menyusun jawaban natural).
Dipanggil backend untuk setiap pesan chat.

ALUR:
  1. Profil user (tipe kulit, masalah kulit, budget, opsional pertanyaan
     spesifik) -> CBFEngine.recommend() -> Top-N produk kandidat.
  2. Buat tiap produk kandidat -> RAGRetriever.ambil_konteks() -> 2-3
     kutipan ulasan/opini asli paling relevan (query = pertanyaan pengguna
     bila ada, atau disusun dari masalah_kulit bila tidak ada).
  3. Top-N produk + kutipan digabung jadi 1 prompt terstruktur -> Groq.
  4. Mengembalikan teks jawaban natural berbahasa Indonesia.

PRINSIP PROMPT (mencegah klaim berlebihan):
  - LLM HANYA boleh memakai data yang diberikan (produk dari CBF + kutipan dari
    RAG); menambah klaim dari pengetahuan umum tentang bahan/merek yang tidak ada
    di konteks dilarang secara eksplisit.
  - Bila kutipan ulasan beragam (ada yang negatif/netral), hal itu HARUS
    disebutkan apa adanya.
  - Bila data produk terbatas (tipe_kulit_cocok/masalah_kulit_cocok atau
    kandungan kosong), LLM diminta menyatakan bahwa informasinya terbatas.

DESAIN: CBFEngine dan RAGRetriever diberikan dari luar kelas ini karena
inisialisasinya berat (stemming deskripsi produk + memuat model embedding);
di backend keduanya dibuat SEKALI saat server menyala dan dipakai untuk setiap
chat.

MODEL & FALLBACK: beberapa model Groq dicoba berurutan (MODELS) dengan timeout
dan max_retries=0, seperti di label_sentimen.py / llm_fallback_tipe_kulit.py.
Setiap chat hanya memerlukan satu panggilan API, tetapi tetap dijaga agar tidak
menggantung saat ada gangguan jaringan atau batas kuota.

CARA PAKAI:
    from cbf_engine import CBFEngine
    from rag_retrieve import RAGRetriever
    from generate_jawaban import GeneratorJawaban

    cbf = CBFEngine()               # sekali di startup
    rag = RAGRetriever()            # sekali di startup
    generator = GeneratorJawaban(cbf, rag)

    jawaban = generator.jawab(
        tipe_kulit="sensitif",
        masalah_kulit=["kemerahan_iritasi", "dehidrasi"],
        budget_max=150_000,
        pertanyaan_user="ada yang bikin kulit sensitif ga gampang merah ga?",
    )
    print(jawaban)
"""
import json
import threading
import time
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from groq import APIConnectionError, APITimeoutError, Groq

# model utama lalu cadangan, dicoba berurutan
MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]
TOP_N_PRODUK = 5
N_KONTEKS_PER_PRODUK = 3
# degradasi bertahap bila Groq bermasalah: satu chat menunggu LLM paling lama
# BATAS_WAKTU_LLM (semua model digabung); setelah semua model gagal, LLM dilewati
# selama JEDA_SETELAH_GAGAL sehingga pesan berikutnya langsung memakai penjelasan
# otomatis tanpa menunggu timeout lagi
BATAS_WAKTU_LLM = 30.0
JEDA_SETELAH_GAGAL = 60.0
# NLU hibrida (pahami_profil): LLM hanya dimintai tafsiran bila aturan nlu.py tidak yakin;
# dibatasi lebih pendek karena ini baru tahap memahami pesan, belum menyusun jawaban
BATAS_WAKTU_NLU = 10.0
TIPE_KULIT_VALID = ("berminyak", "kering", "kombinasi", "sensitif", "normal")
MASALAH_KULIT_VALID = ("jerawat", "kusam", "hiperpigmentasi", "penuaan", "kemerahan_iritasi", "dehidrasi")
SYSTEM_PROMPT_NLU = """Kamu modul pemahaman bahasa (NLU) untuk chatbot rekomendasi skincare berbahasa Indonesia.
Tugasmu HANYA membaca pesan pengguna dan menentukan kondisi kulit yang pengguna ceritakan tentang DIRINYA SENDIRI.

Nilai yang boleh dipakai (tidak boleh di luar daftar):
- tipe_kulit: "berminyak", "kering", "kombinasi", "sensitif", "normal", atau null
- masalah_kulit: daftar berisi nol atau lebih dari "jerawat", "kusam", "hiperpigmentasi", "penuaan", "kemerahan_iritasi", "dehidrasi"

Aturan:
1. Isi hanya kalau pesan JELAS menyiratkannya, termasuk lewat bahasa sehari-hari, perumpamaan, atau gejala yang diceritakan. Kalau ragu, pakai null / [].
2. Jangan menebak dari kata yang tidak bermakna atau tidak jelas (misalnya "aneh", "xyz") -- hasilnya null / [].
3. Abaikan kondisi yang disangkal ("bukan kulit berminyak", "ga kayak orang tua") dan nama produk.
4. Untuk setiap nilai yang kamu isi, beri "bukti": potongan kalimat PERSIS (disalin apa adanya) dari pesan pengguna yang menjadi dasarnya.
5. Jawab HANYA dengan satu objek JSON tanpa teks lain:
{"tipe_kulit": null, "masalah_kulit": [], "bukti": {"<nilai>": "<kutipan persis dari pesan>"}}

Contoh:
Pesan: "umur 24 tapi kulit saya kayak orang 70 tahun"
{"tipe_kulit": null, "masalah_kulit": ["penuaan"], "bukti": {"penuaan": "kulit saya kayak orang 70 tahun"}}
Pesan: "baru 2 jam abis cuci muka udah licin lagi mukanya"
{"tipe_kulit": "berminyak", "masalah_kulit": [], "bukti": {"berminyak": "udah licin lagi mukanya"}}
Pesan: "kulitku aneh"
{"tipe_kulit": null, "masalah_kulit": [], "bukti": {}}"""


def _muat_client():
    # .env dicari di root repo (bukan models/), sehingga terbaca dari working
    # directory mana pun
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY tidak ditemukan di .env.")
    # timeout pendek: kalau Groq lambat/hang, chat jatuh ke penjelasan otomatis
    # (lihat GeneratorJawaban._panggil_llm) alih-alih membuat pengguna menunggu lama
    return Groq(api_key=api_key, timeout=25.0, max_retries=0)


def _ada(v):
    return v is not None and v == v and str(v).strip() != ""  # bukan None/NaN/kosong


def _format_produk(produk_row, konteks_list):
    # data yang kosong ditulis sebagai larangan eksplisit, bukan sekadar "(tidak ada
    # info)" -- tanpa ini LLM cenderung mengisinya sendiri dari nama produk/ulasan
    tipe, kandungan, rating = (produk_row.get(x) for x in ("tipe_kulit_cocok", "kandungan", "rating"))
    baris = [
        f"- {produk_row['nama_produk']}",
        f"  Kategori: {produk_row.get('kategori') or 'tidak diketahui'}",
        f"  Harga: Rp{produk_row['harga']:,.0f}" if _ada(produk_row.get("harga")) else "  Harga: tidak diketahui",
        f"  Cocok tipe kulit: {tipe}" if _ada(tipe) else
        "  Cocok tipe kulit: TIDAK ADA DATA -- jangan bilang produk ini cocok untuk tipe kulit apa pun (termasuk "
        "'semua jenis kulit'); tulis bahwa data kecocokan tipe kulitnya belum ada",
        f"  Menangani masalah kulit: {produk_row.get('masalah_kulit_cocok') or '(tidak ada info eksplisit)'}",
        f"  Kandungan: {kandungan}" if _ada(kandungan) else
        "  Kandungan: TIDAK ADA DATA -- jangan sebut bahan aktif apa pun yang tidak tertulis di nama produk",
        f"  Rating: {float(rating):.1f}" if _ada(rating) else "  Rating: belum ada rating -- jangan sebut rating",
    ]
    if _ada(produk_row.get("skor_sentimen")) and _ada(produk_row.get("jml_ulasan")) and produk_row["jml_ulasan"] > 0:
        baris.append(f"  Sentimen ulasan: {produk_row['skor_sentimen']*100:.0f}% positif dari {int(produk_row['jml_ulasan'])} ulasan")
    else:
        baris.append("  Sentimen ulasan: belum ada ulasan -- jangan klaim ulasannya positif/bagus")

    if konteks_list:
        baris.append("  Kutipan ulasan/opini asli:")
        for k in konteks_list:
            tanda = {"Positif": "+", "Negatif": "-", "Netral": "="}.get(k.get("sentimen", ""), "?")
            baris.append(f"    [{tanda}] \"{k['teks'][:180]}\"")
    else:
        baris.append("  Kutipan ulasan/opini asli: (tidak ditemukan konteks relevan)")
    return "\n".join(baris)


SYSTEM_PROMPT = (
    "Kamu adalah konsultan skincare yang menjawab dalam Bahasa Indonesia santai tapi jelas.\n"
    "SELALU jawab dalam Bahasa Indonesia, walaupun pertanyaan user ditulis dalam bahasa Inggris atau campuran.\n"
    "Kamu HANYA boleh memakai informasi yang diberikan di bawah (data produk + kutipan ulasan asli).\n"
    "ATURAN KETAT:\n"
    "1. Jangan menambahkan klaim soal bahan/manfaat yang TIDAK ada di data atau kutipan yang diberikan -- "
    "jangan mengarang dari pengetahuan umummu sendiri soal suatu merek/bahan, TERMASUK soal keamanan "
    "medis (kehamilan, alergi, interaksi obat, dst). Kalau user tanya hal yang datanya nggak mencakup itu, "
    "bilang terus terang 'di luar data yang saya punya, sebaiknya konsultasi ke dokter/dermatolog' -- "
    "JANGAN menambahkan 'tapi biasanya bahan X perlu hati-hati untuk kondisi Y' dari pengetahuanmu sendiri, "
    "meski niatnya membantu -- itu tetap klaim di luar data yang diberikan.\n"
    "2. Kalau kutipan ulasan untuk suatu produk campur (ada yang negatif/netral), sebutkan itu jujur -- "
    "jangan cuma tampilkan sisi positifnya saja.\n"
    "3. Kalau info suatu produk terbatas (tipe/masalah kulit tidak ada info eksplisit, atau tidak ada kutipan "
    "ulasan), katakan terus terang 'infonya terbatas untuk produk ini' -- jangan berpura-pura yakin.\n"
    "4. Jelaskan SINGKAT kenapa tiap produk direkomendasikan (kaitkan ke tipe/masalah kulit user & kutipan ulasan).\n"
    "5. Jangan menjanjikan hasil medis pasti (mis. 'pasti sembuh') -- pakai bahasa 'membantu', 'banyak yang cocok', dst.\n"
    "Jawab dengan menyapa singkat, lalu rekomendasi 2-4 produk paling relevan dari daftar yang diberikan, "
    "tutup dengan 1 kalimat pengingat kalau reaksi kulit tiap orang bisa beda."
)


SYSTEM_PROMPT_JSON = (
    SYSTEM_PROMPT
    + "\n\nFORMAT OUTPUT WAJIB: balas HANYA dengan satu objek JSON valid, TIDAK ADA teks lain "
    "di luar JSON (tidak ada salam pembuka/penutup di luar field, tidak ada markdown code fence). "
    "Bentuknya persis:\n"
    '{"explanation": "penjelasan umum, 2-4 kalimat", '
    '"alasan_per_produk": ["alasan singkat produk ke-1", "alasan singkat produk ke-2", ...]}\n'
    "Jumlah item di \"alasan_per_produk\" HARUS SAMA PERSIS dengan jumlah produk di DAFTAR PRODUK "
    "KANDIDAT, urut sesuai urutan daftar itu -- jangan kurang, jangan lebih, jangan diberi nomor.\n"
    "KHUSUS field \"explanation\" -- ABAIKAN instruksi 'rekomendasi 2-4 produk paling relevan' di atas, "
    "karena di format JSON ini alasan per-produk sudah dipisah sendiri ke \"alasan_per_produk\" dan "
    "ditampilkan aplikasi tepat di bawah kartu masing-masing produk (urut sesuai DAFTAR PRODUK KANDIDAT). "
    "\"explanation\" JANGAN menyebut nama produk spesifik ATAU menonjolkan salah satu produk seolah paling "
    "utama -- cukup rangkuman umum kriteria pencarian (tipe kulit, masalah kulit, budget kalau ada) dan "
    "kenapa jenis/kategori produk di daftar ini relevan secara umum. Kalau menyebut nama produk spesifik di "
    "\"explanation\" tetap membuat user bingung produk mana yang dimaksud karena urutan sebutan di teks bisa "
    "beda dari urutan kartu di aplikasi -- jadi nama produk HANYA boleh disebut di \"alasan_per_produk\"."
)


def _parse_json_longgar(teks: str) -> dict:
    """LLM kadang tetap bungkus JSON-nya dengan ```json ... ``` atau nambah kalimat
    di luar objeknya walau sudah diminta jangan -- daripada gagal total, coba
    beberapa cara ekstraksi sebelum benar-benar nyerah."""
    try:
        return json.loads(teks)
    except json.JSONDecodeError:
        pass
    tanpa_fence = re.sub(r"^```(?:json)?\s*|\s*```$", "", teks.strip())
    try:
        return json.loads(tanpa_fence)
    except json.JSONDecodeError:
        pass
    cocok = re.search(r"\{.*\}", teks, re.DOTALL)
    if cocok:
        return json.loads(cocok.group(0))  # bila ini pun gagal, exception aslinya dibiarkan muncul
    raise json.JSONDecodeError("Tidak ditemukan objek JSON di respons LLM", teks, 0)


def _normal_bukti(teks):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(teks or "").lower()).split())


def _validasi_pemahaman(data, pesan):
    """Jawaban LLM untuk pahami_profil -> hanya nilai dari daftar baku YANG BUKTINYA benar-benar
    ada di pesan user (kutipan persis, setelah huruf kecil & tanda baca dibuang). Nilai di luar
    daftar, tanpa bukti, atau buktinya karangan LLM dibuang. Tidak ada yang lolos -> None."""
    if not isinstance(data, dict):
        return None
    pesan_n = _normal_bukti(pesan)
    bukti = data.get("bukti") if isinstance(data.get("bukti"), dict) else {}

    def bukti_sah(nilai):
        b = _normal_bukti(bukti.get(nilai))
        return len(b) >= 3 and f" {b} " in f" {pesan_n} "

    tipe = data.get("tipe_kulit")
    tipe = tipe if tipe in TIPE_KULIT_VALID and bukti_sah(tipe) else None
    masalah = data.get("masalah_kulit") if isinstance(data.get("masalah_kulit"), list) else []
    masalah = list(dict.fromkeys(m for m in masalah if m in MASALAH_KULIT_VALID and bukti_sah(m)))
    if not tipe and not masalah:
        return None
    return {"tipe_kulit": tipe, "masalah_kulit": masalah,
            "bukti": {n: str(bukti[n]).strip() for n in ([tipe] if tipe else []) + masalah}}


def _teks_profil(profil, pertanyaan_user=None):
    masalah = profil.get("masalah_kulit") or []
    baris = [f"Tipe kulit user: {profil.get('tipe_kulit') or '(tidak disebutkan)'}",
             f"Masalah kulit user: {', '.join(masalah) if masalah else '(tidak disebutkan)'}"]
    if profil.get("budget_max"):
        baris.append(f"Budget maksimal: Rp{profil['budget_max']:,.0f}")
    if profil.get("budget_min"):
        baris.append(f"Budget minimal: Rp{profil['budget_min']:,.0f}")
    if profil.get("kategori"):
        baris.append(f"Kategori produk yang dicari: {', '.join(profil['kategori'])}")
    if pertanyaan_user:
        baris.append(f"Pertanyaan user: \"{pertanyaan_user}\"")
    return "\n".join(baris)


class GeneratorJawaban:
    """LLM hanya menyusun PROSA (penjelasan & alasan per produk) -- produk mana
    yang direkomendasikan, harga, dst tetap dari CBF (deterministik)."""

    def __init__(self, cbf_engine, rag_retriever=None, top_n_produk=TOP_N_PRODUK,
                 n_konteks_per_produk=N_KONTEKS_PER_PRODUK):
        self.cbf = cbf_engine
        self.rag = rag_retriever
        self.top_n_produk = top_n_produk
        self.n_konteks_per_produk = n_konteks_per_produk
        self.client = _muat_client()
        self._model_index = 0
        self._libur_sampai = 0.0  # time.monotonic(): sebelum ini LLM dilewati (baru saja gagal semua)
        self._kunci = threading.Lock()  # backend melayani beberapa chat sekaligus

    def _susun_prompt(self, produk_df, profil, pertanyaan_user=None):
        masalah = profil.get("masalah_kulit") or []
        query_rag = pertanyaan_user or f"produk untuk kulit {profil.get('tipe_kulit')} yang mengatasi {', '.join(masalah)}"
        blok_produk = []
        for _, row in produk_df.iterrows():
            konteks = []
            if self.rag is not None:
                try:
                    konteks = self.rag.ambil_konteks(query_rag, link_produk=row.get("link"),
                                                     n_hasil=self.n_konteks_per_produk)
                except Exception as e:
                    # RAG gagal -> lanjut tanpa kutipan ulasan, jangan gagalkan chat
                    print(f"[generate_jawaban] RAG gagal diakses, lanjut tanpa konteks ulasan: {type(e).__name__}: {e}")
            blok_produk.append(_format_produk(row, konteks))
        return (f"{_teks_profil(profil, pertanyaan_user)}\n\n"
                "DAFTAR PRODUK KANDIDAT (dari mesin pencocokan, urut paling cocok):\n\n" + "\n\n".join(blok_produk))

    def _panggil_llm(self, system_prompt, isi_prompt, max_tokens, parse_json=False, temperature=0.3,
                     batas_waktu=None):
        """Coba tiap model di MODELS paling banyak sekali, tanpa jeda/tidur --
        untuk chat, lebih baik segera beralih ke penjelasan otomatis daripada
        pengguna menunggu puluhan detik. Total waktu dibatasi batas_waktu; timeout/
        gangguan jaringan langsung berhenti (model lain di server yang sama
        hampir pasti ikut kena). Gagal semua -> LLM dilewati selama
        JEDA_SETELAH_GAGAL. Tidak pernah raise: gagal -> None."""
        if time.monotonic() < self._libur_sampai:
            return None
        # dibaca saat dipanggil (bukan nilai default parameter), supaya batas global bisa diubah (tes 7.8)
        batas_waktu = BATAS_WAKTU_LLM if batas_waktu is None else batas_waktu
        mulai = time.monotonic()
        for _ in range(len(MODELS)):
            sisa = batas_waktu - (time.monotonic() - mulai)
            if sisa < 2:
                break
            model_aktif = MODELS[self._model_index]
            try:
                response = self.client.with_options(timeout=sisa).chat.completions.create(
                    model=model_aktif,
                    messages=[{"role": "system", "content": system_prompt},
                              {"role": "user", "content": isi_prompt}],
                    temperature=temperature,
                    reasoning_effort="none" if "qwen" in model_aktif else "low",
                    reasoning_format="hidden",
                    max_tokens=max_tokens,
                )
                isi = response.choices[0].message.content
                return _parse_json_longgar(isi) if parse_json else isi
            except (APITimeoutError, APIConnectionError) as e:
                print(f"[generate_jawaban] {model_aktif} tidak terjangkau ({type(e).__name__}), pakai penjelasan otomatis")
                break
            except Exception as e:
                print(f"[generate_jawaban] {model_aktif} gagal ({type(e).__name__}: {e}), coba model berikutnya")
                with self._kunci:
                    self._model_index = (self._model_index + 1) % len(MODELS)
        with self._kunci:
            self._libur_sampai = time.monotonic() + JEDA_SETELAH_GAGAL
        print(f"[generate_jawaban] LLM dilewati {JEDA_SETELAH_GAGAL:.0f} detik ke depan")
        return None

    def narasi(self, produk_df, profil, pertanyaan_user=None):
        """Penjelasan umum + alasan per produk (urut sama dengan produk_df) dari LLM.

        profil: dict {tipe_kulit, masalah_kulit (list), budget_max, budget_min}.
        return: {"explanation": str, "alasan_per_produk": [str, ...]}, atau None
            kalau LLM tidak tersedia -- pemanggil wajib punya penjelasan cadangan.
        """
        prompt = self._susun_prompt(produk_df, profil, pertanyaan_user)
        data = self._panggil_llm(SYSTEM_PROMPT_JSON, prompt, max_tokens=250 + 120 * len(produk_df), parse_json=True)
        if not isinstance(data, dict):
            return None
        return {"explanation": str(data.get("explanation") or "").strip(),
                "alasan_per_produk": [str(x) for x in (data.get("alasan_per_produk") or [])]}

    def pahami_profil(self, pesan, menunggu=None):
        """NLU hybrid: tafsiran LLM atas cerita kondisi kulit yang TIDAK tertangkap aturan nlu.py
        ("kulit saya kayak orang 70 tahun", "pori-pori gede, siang dikit udah lengket").
        Dipanggil Percakapan hanya kalau aturan tidak yakin (analisis()['perlu_llm']).

        menunggu: pertanyaan profil yang sedang ditunggu bot ('tipe_kulit'/'masalah_kulit'),
            supaya jawaban singkat ditafsirkan sesuai pertanyaannya.
        return: {tipe_kulit, masalah_kulit, bukti} yang sudah divalidasi (_validasi_pemahaman),
            atau None -- tidak paham, tidak ada yang lolos validasi, atau LLM tidak tersedia
            (pemanggil kembali ke perilaku aturan biasa).
        """
        konteks = {"tipe_kulit": "Chatbot baru saja menanyakan TIPE kulit pengguna.\n",
                   "masalah_kulit": "Chatbot baru saja menanyakan MASALAH kulit pengguna.\n"}.get(menunggu, "")
        data = self._panggil_llm(SYSTEM_PROMPT_NLU, f"{konteks}Pesan: \"{pesan[:400]}\"", max_tokens=200,
                                 parse_json=True, temperature=0.0, batas_waktu=BATAS_WAKTU_NLU)
        return _validasi_pemahaman(data, pesan)

    def jawab(self, tipe_kulit=None, masalah_kulit=None, budget_max=None, pertanyaan_user=None, kategori=None):
        """Jawaban teks bebas (dipakai _demo di bawah)."""
        produk_top = self.cbf.recommend(tipe_kulit=tipe_kulit, masalah_kulit=masalah_kulit,
                                        budget_max=budget_max, kategori=kategori, top_n=self.top_n_produk)
        if produk_top.empty:
            return "Tidak ada produk yang cocok dengan kriteria itu."
        profil = {"tipe_kulit": tipe_kulit, "masalah_kulit": masalah_kulit, "budget_max": budget_max}
        teks = self._panggil_llm(SYSTEM_PROMPT, self._susun_prompt(produk_top, profil, pertanyaan_user), 700)
        return teks or ("Maaf, layanan AI lagi sibuk. Produk kandidat teratas: " + produk_top.iloc[0]["nama_produk"])


def _demo():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from cbf_engine import CBFEngine
    from rag_retrieve import RAGRetriever

    print("Memuat CBF engine + RAG retriever (sekali, seperti di backend beneran)...")
    cbf = CBFEngine()
    rag = RAGRetriever()
    generator = GeneratorJawaban(cbf, rag)

    print("\n=== Uji coba: sensitif + kemerahan_iritasi + dehidrasi, budget 150rb ===\n")
    jawaban = generator.jawab(
        tipe_kulit="sensitif",
        masalah_kulit=["kemerahan_iritasi", "dehidrasi"],
        budget_max=150_000,
        pertanyaan_user="ada yang bikin kulit sensitif ga gampang merah ga?",
    )
    print(jawaban)


if __name__ == "__main__":
    _demo()
