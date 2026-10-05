"""
percakapan.py -- lapisan orkestrasi chat: pesan user + konteks percakapan
-> baca maksudnya (nlu.py) -> panggil CBF (+ LLM buat prosa) -> respons
terstruktur + konteks baru.

Backend tetap stateless: seluruh "ingatan" percakapan (profil yang diubah
lewat chat, produk yang sudah tampil, dst) ada di dict `konteks` yang dikirim
bolak-balik dengan frontend tiap pesan. Konteks dari client divalidasi ulang
di sini, karena client tidak boleh dipercaya begitu saja.

Keputusan desain:
  - Profil awal = isian form onboarding. Perubahan tipe kulit / masalah kulit
    / budget lewat chat BERLAKU sampai diganti lagi di percakapan itu; field
    yang tidak disebut tetap. Profil di form/akun tidak ikut berubah.
  - Jumlah produk TIDAK sticky: permintaan baru tanpa angka -> TOP_N_DEFAULT.
    "2 aja deh" / "banyakin" setelah ada hasil -> potong/tambah dari hasil
    yang SAMA (konteks["pool"]), bukan cari ulang dari nol.
  - Yang ditampilkan hanya produk yang relevan (CBFEngine.recommend(
    hanya_relevan=True)); bila yang relevan kurang dari yang diminta, bilang
    terus terang, jangan diisi produk asal-asalan.
"""
import copy
import re

import pandas as pd

import nlu
from cbf_engine import MASALAH_KULIT_VALID, TIPE_KULIT_VALID

TOP_N_DEFAULT = 3
UKURAN_POOL = nlu.JUMLAH_MAKS
MAKS_BANDING = 5  # kolom tabel perbandingan, agar tetap terbaca
MAKS_SUDAH_TAMPIL = 200
MAKS_JELASKAN = 5  # "kenapa produk ini direkomendasiin?" / ulasan -> paling banyak 5 produk sekaligus
# "yang bagusan mana?" -> skor pemenang 0-100 (disepakati dengan user)
BOBOT_PEMENANG = {"kecocokan": 0.4, "ulasan": 0.4, "harga": 0.2}
ULASAN_PRIOR_N = 20   # ulasan "semu" di rata-rata katalog: 3 ulasan 100% positif tidak otomatis
                      # menang atas 200 ulasan 85% positif (rata-rata Bayesian)
SELISIH_TIPIS = 5     # selisih skor di bawah ini -> jelaskan trade-off, jangan hanya menyebut 1 nama
PILIHAN_TIPE = "berminyak, kering, kombinasi, sensitif, atau normal"
PILIHAN_MASALAH = "jerawat, kusam, hiperpigmentasi, penuaan, kemerahan & iritasi, atau dehidrasi"
# pertanyaan profil yang bisa sedang ditunggu jawabannya (lihat _gagal_paham)
_TUNGGU_PROFIL = ("tipe_kulit", "masalah_kulit", "pilih_field")

# kata di nama produk Shopee yang tidak membedakan satu produk dengan produk
# lain -- query yang hanya berisi kata-kata ini (+ nama brand) dianggap ambigu
_KATA_UMUM_NAMA = {t for s in nlu._SINONIM_KATEGORI for t in re.findall(r"[a-z0-9]+", s)} | {
    "face", "wash", "facial", "gel", "cream", "krim", "lotion", "skin", "original", "ori", "bpom", "ml", "gr",
    "g", "series", "new", "spf", "pa", "the", "wajah", "muka", "kulit", "dan", "untuk", "with", "for", "sabun",
    "pembersih", "ultimate", "premium", "all", "size", "travel", "mini", "pcs", "isi", "paket", "set"}
_ISIAN_NAMA = {"produk", "yang", "yg", "dong", "ya", "deh", "aja", "saja", "tolong", "coba", "si", "nya", "itu",
               "ini", "tadi", "merek", "merk", "brand"}
# ulasan yang isinya soal pengiriman/penjual, bukan produknya -- tidak dikutip
# (pola yang sama dengan penyaring di pipeline/label_sentimen.py, ditambah
# paket/packing/seller karena lolos dari penyaring itu)
# id produk di konteks (format katalog) -- dipakai untuk mengenali produk yang
# pernah tampil tapi SEKARANG sudah dinonaktifkan admin (bukan id sembarangan)
_POLA_ID_PRODUK = re.compile(r"^PRD\d{1,9}$")
PESAN_TIDAK_TERSEDIA = ("Produk nomor {n} sudah tidak tersedia lagi (sudah dinonaktifkan dari katalog), jadi aku "
                        "nggak bisa membahas produk itu. Mau aku carikan penggantinya?")

_POLA_ULASAN_LOGISTIK = re.compile(r"pengiriman|kirim|kurir|ekspedisi|ongkir|delivery|shipping|paket|packing|"
                                   r"kemasan|dikemas|bungkus|seller|penjual|admin|toko|beli di ?sini|order di ?sini|"
                                   r"\bb(e)?lanja|\bdsni\b|\bdisni\b|"
                                   r"\bdi ?sini\b|\bsampai\b|\bsampe\b|sampei|nyampe|\bdatang|\bdateng|\brespon|\bcs\b|expired|"
                                   r"\bexp\b", re.I)
# ulasan "baru coba, semoga cocok" -- belum ada pengalaman yang bisa dikutip
_POLA_ULASAN_BELUM_COBA = re.compile(r"semoga|\bsmg\b|\bmoga\b|mudah[ -]?mudahan|mudah2an|"
                                     r"baru (pertama|coba|nyoba|pake|pakai|beli)|"
                                     r"belum (di ?)?(coba|nyoba|pake|pakai|dipakai|dicoba)|masih (nyoba|coba)", re.I)
# kueri RAG untuk "keluhan orang apa aja?" -- pesan user sendiri terlalu umum
# untuk menemukan ulasan yang benar-benar mengeluh
KUERI_KELUHAN = "tidak cocok, bikin jerawat, breakout, iritasi, perih, gatal, kering, lengket, tidak ada efek, kecewa"
# ulasan yang membahas efeknya ke kulit diutamakan untuk dikutip
_POLA_ULASAN_KULIT = re.compile(r"jerawat|kulit|wajah|muka|minyak|kering|kusam|cerah|lembab|lembap|iritasi|bruntus|"
                                r"breakout|komedo|glowing|flek|noda|pori|kemerahan|perih|gatal|ngefek|efek", re.I)
# kutipan wajib membahas produknya (bukan sekadar "langganan di sini, belanja
# banyak") -- daftar kata logistik saja tidak cukup menangkap semua variasi ejaan
_POLA_ULASAN_PRODUK = re.compile(_POLA_ULASAN_KULIT.pattern + r"|cocok|produk|tekstur|wangi|aroma|meresap|lengket|"
                                 r"ringan|hasil|ngaruh|ampuh|cream|krim|serum|toner|sunscreen|sabun", re.I)
# ulasan Shopee berformat "Tekstur:ringan Performa:bagus ..." yang tidak
# terpisah di cleaning_data.py (tanpa spasi ganda) -- dirapikan saat dikutip
_LABEL_ULASAN = re.compile(r"\b(tekstur|efektivitas|keaslian|kualitas|pengalaman penggunaan|kenyamanan|aroma|"
                           r"cocok untuk|efek|kemasan|profil kecantikan|manfaat|wangi|daya serap|performa|warna|"
                           r"hasil)\s*:\s*", re.I)
_LABEL_BUKAN_PRODUK = {"kemasan", "keaslian"}
MAKS_KUTIPAN = 3
PANJANG_KUTIPAN = 240
# pesan berisi beberapa permintaan: intent yang tidak perlu dijawab sendiri kalau
# ada permintaan lain di pesan yang sama, dan intent yang sama-sama "cari produk"
_TANPA_ISI = {"kosong", "tidak_jelas", "sapaan", "terima_kasih", "konfirmasi"}
_KELUARGA_REKOMENDASI = {"rekomendasi", "alternatif", "lebih_murah", "ubah_jumlah"}
CATATAN_MEDIS_LUNAK = ("_Catatan: ini produk skincare umum yang dijual bebas, bukan obat. Kalau keluhannya parah, "
                       "meradang, atau nggak membaik, sebaiknya konsultasi ke dokter kulit._")
CATATAN_TANPA_LLM = "_(Penjelasan AI lagi nggak tersedia, jadi penjelasannya aku susun otomatis dari data.)_"
_ALASAN_MEDIS = {
    "obat resep": "obat resep dokter",
    "obat minum & dosis": "obat minum atau dosis",
    "konsentrasi bahan aktif": "berapa persen/konsentrasi bahan aktif yang pas buat kulit kamu",
    "obat keras": "obat keras (misalnya tretinoin, antibiotik, atau hidrokuinon)",
    "kehamilan": "keamanan produk saat hamil atau menyusui",
    "kondisi kulit yang perlu diperiksa": "kondisi kulit yang perlu diperiksa langsung (meradang parah, bernanah, "
                                          "infeksi, eksim, dan sejenisnya)",
}


def rupiah(n):
    return f"Rp{n:,.0f}".replace(",", ".")


def _kosong(v):
    return v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and not v.strip())


def _tag(teks):
    return [] if _kosong(teks) else [t.strip() for t in str(teks).split(";") if t.strip()]


# ---------- penjaga klaim alasan dari LLM (bagian 8: data kosong/terbatas) ----------

_TIPE_KATA = {"berminyak": "berminyak", "oily": "berminyak", "kering": "kering", "dry": "kering",
              "kombinasi": "kombinasi", "combination": "kombinasi", "campuran": "kombinasi", "sensitif": "sensitif",
              "sensitive": "sensitif", "normal": "normal"}
_KATA_TIPE = r"(?:berminyak|oily|kering|dry|kombinasi|combination|campuran|sensitif|sensitive|normal)"
# "kulit sensitif dan kering" / "kulit berminyak, kombinasi, atau normal" -> semua tipe di daftarnya
_POLA_SEBUT_TIPE = re.compile(
    rf"\bkulit\s+(?:yang\s+)?({_KATA_TIPE}(?:\s*(?:,\s*(?:dan|serta|atau)?|dan|serta|atau|/|&)\s*{_KATA_TIPE})*)\b|"
    rf"\b({_KATA_TIPE}(?:\s*(?:,\s*(?:and|or)?|and|or|/|&)\s*{_KATA_TIPE})*)\s+skin\b", re.I)
_POLA_SEMUA_TIPE = re.compile(r"\b(semua|segala) (jenis|tipe) kulit\b|\ball skin types?\b", re.I)
_POLA_JUJUR_KOSONG = re.compile(r"\b(belum|tidak|tak|nggak|gak|ga) ada (data|info\w*)|\b(info|data)\w* (masih |cukup )?"
                                r"terbatas|\bbelum (jelas|diketahui|ada rating|ada ulasan)", re.I)
# kelompok sinonim bahan aktif: menyebut salah satunya sah kalau salah satu
# anggota kelompoknya ada di nama/kandungan/deskripsi produk
BAHAN_AKTIF = [
    ("niacinamide", "nicotinamide", "vitamin b3", "vit b3"), ("retinol", "retinoid", "retinal", "retinyl"),
    ("salicylic", "salisilat", "bha"), ("aha", "glycolic", "glikolat", "lactic", "laktat", "mandelic"), ("pha",),
    ("hyaluronic", "hyaluron", "hialuronat", "hyaluronate"), ("ceramide", "ceramid"),
    ("centella", "cica", "madecassoside", "pegagan", "gotu kola"), ("vitamin c", "vit c", "ascorbic", "askorbat"),
    ("vitamin e", "vit e", "tocopherol"), ("collagen", "kolagen"), ("peptide", "peptida"), ("azelaic",),
    ("kojic",), ("arbutin",), ("tranexamic", "traneksamat"), ("bakuchiol",), ("snail",), ("mugwort",),
    ("tea tree",), ("zinc",), ("sulfur", "sulphur", "belerang"), ("benzoyl",), ("squalane",), ("panthenol",),
    ("allantoin",), ("propolis",), ("galactomyces",), ("licorice", "akar manis"), ("aloe", "lidah buaya"),
]
_POLA_PERSEN_ULASAN = re.compile(r"(\d+)\s*%\s*(?:dari\s+)?(?:ulasan|review|pembeli|pengguna|positif)", re.I)
_POLA_KLAIM_ULASAN = re.compile(r"\d+\s*%\s*(ulasan|positif|review)|ulasan\w*\s+(yang\s+)?(positif|bagus|baik|"
                                r"memuaskan)|banyak (pembeli|pengguna|yang) (suka|puas|cocok)|disukai|review\w*\s+"
                                r"(positif|bagus)", re.I)
_POLA_KLAIM_RATING = re.compile(r"\brating\b|★|\bbintang\b", re.I)


def _harga_kosong(row):
    """Teks harga untuk produk yang harganya tidak dipakai: memang kosong di
    data, atau harga_outlier (angkanya tidak wajar, mis. listing DO NOT ORDER
    Rp1 miliar -- sengaja dikosongkan di CBFEngine, jangan ditampilkan)."""
    if bool(row.get("harga_outlier", False)):
        return "harga di data tidak wajar (kemungkinan listing \"jangan dibeli\"), jadi nggak aku pakai"
    return "tidak ada di data"


def _angka_positif(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _rp_di_bawah(b):
    """budget_max b = harga <= b. Hasil "lebih murah dari Rp37.900" disimpan
    sebagai 37.899 -> ditulis "di bawah Rp37.900" (sama persis maknanya)."""
    return rupiah(b + 1) if (b + 1) % 100 == 0 else rupiah(b)


def teks_budget(p):
    if p.get("budget_min") and p.get("budget_max"):
        return f"{rupiah(p['budget_min'])} – {rupiah(p['budget_max'])}"
    if p.get("budget_max"):
        return f"di bawah {_rp_di_bawah(p['budget_max'])}"
    if p.get("budget_min"):
        return f"di atas {rupiah(p['budget_min'])}"
    return "tanpa batas"


def _token_nama(teks_atau_token):
    """Token nama yang sudah dinormalisasi + gabungan 2 token bersebelahan,
    supaya beda spasi tetap cocok ke dua arah ("hada labo" <-> "hadalabo")."""
    token = nlu.normalisasi_nama(teks_atau_token) if isinstance(teks_atau_token, str) else list(teks_atau_token)
    return set(token) | {a + b for a, b in zip(token, token[1:])}


def profil_dari_onboarding(ob):
    masalah = ob.get("masalah_kulit") or []
    if isinstance(masalah, str):
        masalah = [masalah]
    return {
        "tipe_kulit": ob.get("tipe_kulit") or None,
        "masalah_kulit": [m for m in masalah if m in MASALAH_KULIT_VALID],
        "budget_max": None if ob.get("tanpa_batas_budget") else _angka_positif(ob.get("budget")),
        "budget_min": None,
    }


class Percakapan:
    def __init__(self, cbf, generator=None, rag=None):
        self.cbf = cbf
        self.generator = generator  # None -> selalu pakai penjelasan otomatis (tanpa LLM)
        self.rag = rag  # None -> pertanyaan soal ulasan dijawab dari ringkasan data saja
        self._id_valid = set(cbf.df["id"])
        self._kategori_id = dict(zip(cbf.df["id"], cbf.df["kategori"]))
        self._merek = frozenset(cbf.df["brand"].dropna().astype(str).str.lower().str.strip())
        self._token_merek = {t for m in self._merek for t in _token_nama(m)}
        self._indeks_nama = []
        for _, r in cbf.df.iterrows():
            dasar = nlu.normalisasi_nama(f"{r['nama_produk']} {'' if _kosong(r['brand']) else r['brand']}")
            # listing yang datanya lengkap (ada harga) diutamakan kalau skor namanya sama
            lengkap = int(not _kosong(r["harga"])) + int(not _kosong(r["rating"]))
            self._indeks_nama.append((r["id"], _token_nama(dasar), len(set(dasar)), lengkap,
                                      0 if _kosong(r["jml_ulasan"]) else int(r["jml_ulasan"])))
        self._kosakata_nama = set().union(*(tok for _, tok, _, _, _ in self._indeks_nama))
        self._nama = dict(zip(cbf.df["id"], cbf.df["nama_produk"]))
        # sumber sah untuk klaim bahan aktif di alasan LLM
        self._teks_sumber = {r["id"]: " ".join("" if _kosong(r[c]) else str(r[c]) for c in
                                               ("nama_produk", "kandungan", "deskripsi") if c in r).lower()
                             for _, r in cbf.df.iterrows()}
        berulasan = cbf.df[cbf.df["jml_ulasan"].fillna(0) > 0]["skor_sentimen"].dropna()
        self._prior_sentimen = float(berulasan.mean()) if not berulasan.empty else 0.5

    # ---------- konteks ----------

    def _pulihkan_konteks(self, konteks, onboarding):
        # fokus: daftar yang terakhir dibahas ("tampil" = rekomendasi, "banding" =
        # tabel perbandingan) -- rujukan "yang mana yang lebih murah?" /
        # "yang bagusan mana?" mengarah ke sini
        # sudah_tampil: semua produk yang pernah ditampilkan di percakapan ini --
        # "yang lain dong" tidak boleh menampilkan ulang produk-produk ini
        # gagal: berapa kali berturut-turut bot tidak paham jawaban atas pertanyaan profil
        k = {"profil": profil_dari_onboarding(onboarding or {}), "kategori": [], "menunggu": None, "gagal": 0,
             "pool": [], "tampil": [], "alasan": {}, "banding": [], "fokus": "tampil", "sudah_tampil": []}
        if not isinstance(konteks, dict):
            return k
        lama = konteks.get("profil") if isinstance(konteks.get("profil"), dict) else {}
        p = k["profil"]
        if lama.get("tipe_kulit") in TIPE_KULIT_VALID:
            p["tipe_kulit"] = lama["tipe_kulit"]
        masalah = [m for m in (lama.get("masalah_kulit") or []) if m in MASALAH_KULIT_VALID]
        if masalah:
            p["masalah_kulit"] = masalah
        for kunci in ("budget_max", "budget_min"):
            if kunci in lama:  # None di konteks = sengaja diubah jadi tanpa batas lewat chat
                p[kunci] = _angka_positif(lama[kunci])
        kategori = konteks.get("kategori") if isinstance(konteks.get("kategori"), list) else []
        k["kategori"] = [x for x in kategori if x in nlu.KATEGORI][:len(nlu.KATEGORI)]
        if konteks.get("menunggu") in _TUNGGU_PROFIL:
            k["menunggu"] = konteks["menunggu"]
            gagal = konteks.get("gagal")
            k["gagal"] = gagal if isinstance(gagal, int) and not isinstance(gagal, bool) and 0 <= gagal <= 3 else 0
        if konteks.get("fokus") in ("tampil", "banding"):
            k["fokus"] = konteks["fokus"]
        for kunci, batas in (("pool", UKURAN_POOL), ("sudah_tampil", MAKS_SUDAH_TAMPIL)):
            ids = konteks.get(kunci) if isinstance(konteks.get(kunci), list) else []
            k[kunci] = [i for i in ids if isinstance(i, str) and i in self._id_valid][:batas]
        # tampil/banding = nomor yang DILIHAT user di layar: produk yang sudah
        # dinonaktifkan admin tetap di posisinya (tidak dibuang), supaya "nomor 2"
        # tidak diam-diam bergeser menunjuk produk lain -- lihat _id_nomor()
        for kunci, batas in (("tampil", UKURAN_POOL), ("banding", MAKS_BANDING)):
            ids = konteks.get(kunci) if isinstance(konteks.get(kunci), list) else []
            k[kunci] = [i for i in ids if isinstance(i, str) and (i in self._id_valid or _POLA_ID_PRODUK.match(i))
                        ][:batas]
        alasan = konteks.get("alasan") if isinstance(konteks.get("alasan"), dict) else {}
        k["alasan"] = {i: str(t)[:600] for i, t in alasan.items() if i in k["tampil"]}
        return k

    def _terapkan_profil(self, a, k):
        """Terapkan perubahan profil yang disebut di pesan. Field yang tidak
        disebut TIDAK diubah. return: list kalimat konfirmasi perubahan."""
        p = k["profil"]
        catatan = []
        if a["tipe_kulit"] and a["tipe_kulit"] != p["tipe_kulit"]:
            p["tipe_kulit"] = a["tipe_kulit"]
            catatan.append(f"Oke, tipe kulit kamu aku ubah jadi **{a['tipe_kulit']}**.")
        if a["masalah_kulit"]:
            baru = list(dict.fromkeys(p["masalah_kulit"] + a["masalah_kulit"])) if a["masalah_tambah"] \
                else a["masalah_kulit"]
            if baru != p["masalah_kulit"]:
                p["masalah_kulit"] = baru
                label = ", ".join(nlu.LABEL_MASALAH[m] for m in baru)
                catatan.append(f"Masalah kulit kamu sekarang: **{label}**.")
        b = a["budget"]
        if b.get("reset"):
            if p["budget_max"] or p["budget_min"]:
                p["budget_max"] = p["budget_min"] = None
                catatan.append("Oke, budget sekarang **tanpa batas**.")
        elif b:
            baru = (b.get("budget_max"), b.get("budget_min"))
            if baru != (p["budget_max"], p["budget_min"]):
                p["budget_max"], p["budget_min"] = baru
                kalimat = f"Budget aku ubah jadi **{teks_budget(p)}**."
                if b.get("asumsi_ribu"):
                    kalimat += " (Angkanya aku anggap dalam ribuan rupiah.)"
                catatan.append(kalimat)
        return catatan

    def _pahami_dengan_llm(self, a, k, pesan):
        """Isi tipe/masalah kulit yang tidak tertangkap aturan dengan tafsiran LLM yang sudah
        divalidasi (nilai baku + bukti kutipan persis dari pesan). Nilai yang SUDAH terbaca
        aturan tidak pernah ditimpa."""
        pahami = getattr(self.generator, "pahami_profil", None)
        if pahami is None:
            return
        hasil = pahami(pesan, menunggu=k["menunggu"] if k["menunggu"] in ("tipe_kulit", "masalah_kulit") else None)
        if not hasil:
            return
        if hasil["tipe_kulit"] and not a["tipe_kulit"]:
            a["tipe_kulit"] = hasil["tipe_kulit"]
        if hasil["masalah_kulit"] and not a["masalah_kulit"]:
            a["masalah_kulit"] = hasil["masalah_kulit"]
        # kalimatnya sudah dipahami -> kata yang tadinya "tidak dikenal" bukan nilai yang perlu ditanyakan
        a["tipe_tidak_dikenal"] = a["masalah_tidak_dikenal"] = None
        a["salah_field"] = []
        if a["intent"] in ("tidak_jelas", "di_luar_topik"):
            a["intent"] = "rekomendasi"
        a["dari_llm"] = hasil

    @staticmethod
    def _catatan_llm(a):
        """Tafsiran LLM selalu disebut terbuka beserta kutipannya, supaya user bisa mengoreksi."""
        h = a.get("dari_llm")
        if not h:
            return []
        bagian = ([f"tipe kulit **{h['tipe_kulit']}**"] if h["tipe_kulit"] else []) + \
            ([f"masalah kulit **{', '.join(nlu.LABEL_MASALAH[m] for m in h['masalah_kulit'])}**"]
             if h["masalah_kulit"] else [])
        kutipan = "; ".join(f"\"{b}\"" for b in dict.fromkeys(h["bukti"].values()))
        return [f"Dari ceritamu ({kutipan}), aku tangkap {' dan '.join(bagian)}. Kalau keliru, koreksi saja, "
                f"misalnya \"masalah kulit saya jerawat\"."]

    @staticmethod
    def _catatan_salah_field(a):
        """Nilai yang dikenali ternyata milik field lain dari yang disebut/ditanyakan
        ("tipe kulit saya jerawat", atau "kusam" saat bot menanyakan tipe kulit) ->
        tetap dicatat ke field yang benar, dan user diberi tahu."""
        masalah = [nlu.LABEL_MASALAH[kunci] for field, kunci in a["salah_field"] if field == "masalah_kulit"]
        tipe = [kunci for field, kunci in a["salah_field"] if field == "tipe_kulit"]
        if masalah:
            masalah[0] = masalah[0][:1].upper() + masalah[0][1:]
            daftar = ", ".join(f"**{m}**" for m in masalah)
            return [f"{daftar} itu termasuk masalah kulit, bukan tipe kulit, jadi aku catat sebagai masalah kulit kamu."]
        if tipe:
            return [f"**{tipe[0].capitalize()}** itu termasuk tipe kulit, bukan masalah kulit, jadi aku catat "
                    f"sebagai tipe kulit kamu."]
        return []

    @staticmethod
    def _tanya_field(field, k, kata=None):
        p = k["profil"]
        if field == "tipe_kulit":
            awal = f"Aku belum kenal tipe kulit \"{kata}\". " if kata else ""
            return (f"{awal}Tipe kulit kamu yang mana: {PILIHAN_TIPE}? (Sementara profil kamu masih tercatat "
                    f"kulit **{p['tipe_kulit']}**.)")
        awal = f"Aku belum kenal masalah kulit \"{kata}\". " if kata else ""
        sekarang = ", ".join(nlu.LABEL_MASALAH[m] for m in p["masalah_kulit"]) or "belum diisi"
        return (f"{awal}Masalah kulit kamu yang mana: {PILIHAN_MASALAH}? Boleh lebih dari satu. (Sementara profil "
                f"kamu masih tercatat masalah **{sekarang}**.)")

    def _gagal_paham(self, k, field, kata, catatan):
        """Bot tidak paham jawaban soal profil kulit. Pertanyaan yang sama TIDAK diulang
        terus (user bisa terjebak loop tanpa jalan keluar):
          gagal ke-1 -> tanya pilihan untuk field itu,
          gagal ke-2 berturut-turut -> tanya lebih jelas: mau ganti TIPE atau MASALAH kulit?
          gagal ke-3 -> berhenti bertanya, profil dibiarkan, beri contoh kalimat yang dipahami."""
        k["gagal"] = k["gagal"] + 1 if k["menunggu"] in _TUNGGU_PROFIL else 1
        if k["gagal"] == 1 and field != "pilih_field":
            k["menunggu"] = field
            teks = self._tanya_field(field, k, kata)
        elif k["gagal"] <= 2:
            k["menunggu"] = "pilih_field"
            teks = (f"Maaf, aku masih belum nangkep maksudnya. Kamu mau ganti **tipe kulit** ({PILIHAN_TIPE}) atau "
                    f"**masalah kulit** ({PILIHAN_MASALAH})? Jawab \"tipe\" atau \"masalah\", atau langsung sebut "
                    f"salah satu pilihannya.")
        else:
            k["menunggu"], k["gagal"] = None, 0
            teks = (f"Oke, profil kamu aku biarkan seperti sekarang dulu: {self._teks_profil(k['profil'])}. Kalau mau "
                    f"mengubahnya, sebut langsung, misalnya \"tipe kulit saya kering\" atau \"masalah kulit saya "
                    f"kusam\". Kamu juga bisa langsung minta rekomendasi, misalnya \"rekomendasiin sunscreen\".")
        return self._respons(k, "klarifikasi", "\n\n".join(catatan + [teks]))

    # ---------- alur utama ----------

    def proses(self, pesan, konteks=None, onboarding=None):
        """return: dict {tipe, explanation, recommendation, grup, perbandingan, konteks}."""
        k = self._pulihkan_konteks(konteks, onboarding)
        klausa = self._klausa_diproses(nlu.pecah_klausa(pesan), k)
        if len(klausa) >= 2:
            return self._proses_berurutan(klausa, k)
        return self._jalankan(klausa[0] if klausa else pesan, k)

    def _analisis(self, pesan, k, ada_hasil=None):
        return nlu.analisis(pesan, menunggu=k["menunggu"], ada_banding=bool(k["banding"]), kosakata_merek=self._merek,
                            ada_hasil=bool(k["tampil"]) if ada_hasil is None else ada_hasil)

    def _klausa_diproses(self, klausa, k):
        """1 pesan, beberapa permintaan ("rekomendasiin sunscreen, terus
        bandingin nomor 1 sama 2") -> potongan yang diproses berurutan.
        Basa-basi di sela permintaan ("makasih! carikan toner juga") dibuang.
        Bila semuanya hanya permintaan rekomendasi yang filternya tersebar
        ("kulitku kering. budget 100rb"), tetap diproses sebagai 1 pesan utuh
        supaya filternya digabung, bukan jadi 2 daftar."""
        if len(klausa) < 2:
            return klausa
        ada_hasil, penting = bool(k["tampil"]), []
        for c in klausa:
            intent = self._analisis(c, k, ada_hasil)["intent"]
            if intent not in _TANPA_ISI:
                penting.append((c, intent))
            ada_hasil = ada_hasil or intent in _KELUARGA_REKOMENDASI
        if len(penting) == 1:
            return [penting[0][0]]
        if not penting or all(i in _KELUARGA_REKOMENDASI for _, i in penting):
            return [" ".join(klausa)]
        return [c for c, _ in penting]

    def _proses_berurutan(self, klausa, k):
        """Tiap permintaan dijalankan berurutan dengan konteks hasil permintaan
        sebelumnya (nomor produk, filter). Semua jawaban ditampilkan; kartu
        produk & tabel dari permintaan terakhir yang menghasilkannya."""
        hasil = []
        for c in klausa:
            r = self._jalankan(c, k)
            hasil.append((c, r))
            k = r["konteks"]
        teks = "\n\n".join(f"**{i}. \"{c}\"**\n\n{r['explanation']}" for i, (c, r) in enumerate(hasil, 1))
        teks = f"Kamu minta {len(hasil)} hal sekaligus, aku kerjakan berurutan ya.\n\n" + teks
        dengan_produk = [r for _, r in hasil if r["recommendation"]]
        dengan_tabel = [r for _, r in hasil if r["perbandingan"]]
        terakhir = dengan_produk[-1] if dengan_produk else {}
        return {"tipe": "+".join(r["tipe"] for _, r in hasil), "explanation": teks,
                "recommendation": terakhir.get("recommendation") or [], "grup": terakhir.get("grup"),
                "perbandingan": dengan_tabel[-1]["perbandingan"] if dengan_tabel else None, "konteks": k}

    def _jalankan(self, pesan, k):
        a = self._analisis(pesan, k)
        # "dari produk A dengan produk B, bagusan yg mana" -> bandingkan A & B yang
        # disebut (skenario 4.1b), BUKAN rekomendasi baru lalu dipilih satu. Syaratnya
        # minimal satu nama benar-benar produk di katalog; nama lain yang tidak
        # ketemu/ambigu dilaporkan terus terang oleh _banding.
        if a["banding_implisit"] and a["intent"] not in ("ulasan", "alasan") \
                and any(self._cari_nama(n)["status"] == "ketemu" for n in a["banding_implisit"]["nama"]):
            a["intent"], a["rujukan"] = "banding", a["banding_implisit"]
        # NLU hybrid: aturan nlu.py tidak yakin (cerita/perumpamaan soal kulit yang tidak
        # tertangkap kosakata) -> minta tafsiran LLM; gagal/tidak paham -> perilaku aturan biasa
        if a["perlu_llm"] and a["intent"] in ("rekomendasi", "tidak_jelas", "di_luar_topik"):
            self._pahami_dengan_llm(a, k, pesan)

        if a["intent"] == "kosong":
            return self._respons(k, "klarifikasi",
                                 "Pesannya kosong atau kurang jelas nih. Coba ceritakan kondisi kulit kamu atau "
                                 "produk yang kamu cari, misalnya: \"rekomendasiin sunscreen dong\".")
        if a["intent"] == "ubah_profil":  # jawaban atas "mau ganti tipe kulit atau masalah kulit?"
            if a["pilih_field"]:
                # hitungan gagal TIDAK di-reset: kalau jawaban berikutnya tetap tidak
                # dipahami, bot berhenti bertanya (lihat _gagal_paham), bukan berputar lagi
                k["menunggu"] = a["pilih_field"]
                return self._respons(k, "klarifikasi", self._tanya_field(a["pilih_field"], k))
            return self._gagal_paham(k, "pilih_field", None, [])
        if a["intent"] in ("tidak_jelas", "di_luar_topik", "medis", "sapaan", "terima_kasih", "konfirmasi",
                           "bantuan"):
            return self._di_luar_rekomendasi(a, k)
        if a["intent"] == "info_produk":
            return self._info_produk(a, k)
        if a["intent"] in ("banding", "banding_atribut"):
            return self._banding(a, k)
        if a["intent"] == "pilih_satu":
            return self._pilih_satu(a, k)
        if a["intent"] == "urutkan":
            return self._urutkan(a, k)
        if a["intent"] == "alasan":
            return self._alasan(a, k)
        if a["intent"] == "ulasan":
            return self._ulasan(a, k, pesan)

        catatan = self._catatan_llm(a) + self._catatan_salah_field(a) + self._terapkan_profil(a, k)
        if a["tipe_tidak_dikenal"] and not a["tipe_kulit"]:
            return self._gagal_paham(k, "tipe_kulit", a["tipe_tidak_dikenal"], catatan)
        if a["masalah_tidak_dikenal"] and not a["masalah_kulit"]:
            return self._gagal_paham(k, "masalah_kulit", a["masalah_tidak_dikenal"], catatan)
        k["menunggu"], k["gagal"] = None, 0

        if a["kategori_tidak_dikenal"]:
            daftar = ", ".join(nlu.LABEL_KATEGORI.values())
            return self._respons(k, "klarifikasi", "\n\n".join(catatan + [
                f"Kategori \"{a['kategori_tidak_dikenal']}\" nggak ada di data aku. Kategori yang tersedia: {daftar}. "
                "Mau cari yang mana?"]))
        catatan += self._terapkan_kategori(a, k)

        if a["jumlah_flag"] == "tidak_valid":
            return self._respons(k, "klarifikasi", "\n\n".join(catatan + [
                "Jumlah produknya minimal 1 ya. Mau aku tampilkan berapa? Misalnya \"kasih 3\"."]))
        if a["intent"] == "ubah_jumlah":
            return self._ubah_jumlah(a, k)
        if a["intent"] == "lebih_murah":
            return self._lebih_murah(a, k, pesan, catatan)
        if a["intent"] == "alternatif":
            # jumlahnya sama dengan daftar terakhir (kecuali disebut lain), produk
            # yang pernah tampil di percakapan ini dikeluarkan
            return self._rekomendasi(a, k, pesan, catatan, kecuali=set(k["sudah_tampil"]),
                                     diminta=a["jumlah"] or len(k["tampil"]) or TOP_N_DEFAULT)
        return self._rekomendasi(a, k, pesan, catatan)

    def _terapkan_kategori(self, a, k):
        """Filter kategori sticky: berlaku sampai diganti atau user bilang
        "semua kategori". return: list kalimat konfirmasi perubahan."""
        if a["kategori_reset"]:
            if k["kategori"]:
                k["kategori"] = []
                return ["Oke, sekarang aku cari dari **semua kategori**."]
            return []
        baru = [kat for kat, _ in a["multi"]] or a["kategori"]
        if baru and baru != k["kategori"]:
            sebelumnya = k["kategori"]
            k["kategori"] = baru
            if sebelumnya:
                return [f"Kategori aku ganti ke **{self._label_kategori(baru)}**."]
        return []

    @staticmethod
    def _label_kategori(daftar):
        return " & ".join(nlu.LABEL_KATEGORI[x] for x in daftar)

    def _cari(self, p, kategori=None, top_n=UKURAN_POOL, pakai_budget=True, kecuali=()):
        hasil = self.cbf.recommend(
            tipe_kulit=p["tipe_kulit"], masalah_kulit=p["masalah_kulit"] or None,
            budget_max=p["budget_max"] if pakai_budget else None,
            budget_min=p["budget_min"] if pakai_budget else None,
            kategori=kategori, top_n=top_n + len(kecuali), hanya_relevan=True)
        if kecuali:
            hasil = hasil[~hasil["id"].isin(kecuali)].head(top_n).reset_index(drop=True)
        return hasil

    def _semua_sudah_tampil(self, k, kategori, catatan):
        """"yang lain dong" tapi semua produk yang cocok sudah pernah tampil."""
        p = k["profil"]
        label = nlu.LABEL_KATEGORI[kategori] if kategori else "produk"
        n = len(self._cari(p, kategori, top_n=1000))
        if not n:
            return self._tanpa_hasil(k, kategori, catatan, TOP_N_DEFAULT)
        # daftar terakhir tetap diingat: "yang lain lagi" berikutnya dapat
        # jawaban yang sama, bukan diam-diam mengulang dari rekomendasi teratas
        return self._respons(k, "kosong", "\n\n".join(catatan + [
            f"Semua {label} yang cocok dengan kriteria kamu sudah aku tampilkan ({n} produk), jadi nggak ada pilihan "
            "lain lagi. Kalau mau opsi baru, coba longgarkan salah satu kriterianya, misalnya naikin budget, ganti "
            "kategori, atau bilang \"semua kategori\"."]))

    def _rekomendasi(self, a, k, pesan, catatan, kecuali=(), diminta=None):
        """kecuali: id produk yang tidak boleh tampil lagi ("yang lain dong")."""
        if len(k["kategori"]) >= 2:
            return self._rekomendasi_multi(a, k, pesan, catatan, kecuali, ikut_tampil=diminta is not None)
        p = k["profil"]
        kategori = k["kategori"][0] if k["kategori"] else None
        diminta = diminta or a["jumlah"] or TOP_N_DEFAULT
        pool = self._cari(p, kategori, kecuali=kecuali)
        if pool.empty:
            if kecuali:
                return self._semua_sudah_tampil(k, kategori, catatan)
            return self._tanpa_hasil(k, kategori, catatan, diminta)

        k["pool"] = list(pool["id"])
        k["alasan"] = {}
        if a["pilih_satu"] and not a["jumlah"]:
            # "kasih yang terbaik" tanpa daftar sebelumnya -> pilih pemenang dari
            # kandidat teratas, pakai skor yang sama dengan "yang bagusan mana?"
            k["tampil"] = []  # kandidat baru, jangan dilabeli nomor dari daftar lama
            return self._pilih_satu(a, k, kandidat=k["pool"][:MAKS_BANDING], catatan=catatan)
        tampil = pool.head(diminta)
        produk, penjelasan = self._susun_produk(tampil, k, pesan, lain=bool(kecuali))

        tambahan = []
        if len(pool) < diminta:
            tambahan.append(f"Tinggal **{len(pool)} produk** lain yang cocok dengan kriteria kamu, jadi ini semuanya."
                            if kecuali else f"Cuma ketemu **{len(pool)} produk** yang cocok dengan kriteria kamu, "
                            "jadi aku tampilkan semuanya.")
        elif a["jumlah_flag"] == "semua":
            tambahan.append(f"Aku tampilkan {len(tampil)} produk yang paling cocok (bukan seluruh katalog, "
                            "biar tetap relevan).")
        elif a["jumlah_flag"] == "dibatasi":
            tambahan.append(f"Maksimal {nlu.JUMLAH_MAKS} produk sekali tampil ya.")
        if kecuali and len(pool) > len(tampil):
            tambahan.append("Masih mau pilihan lain? Bilang aja \"yang lain lagi\".")
        elif a["jumlah"] is None and not kecuali:
            tambahan.append("Mau lebih banyak atau lebih sedikit? Tinggal bilang, misalnya \"kasih 5\" atau \"1 aja\".")
        tambahan += self._pengingat_kategori(a, k)
        if a["medis_lunak"]:
            tambahan.append(CATATAN_MEDIS_LUNAK)
        return self._respons(k, "rekomendasi", "\n\n".join(catatan + [penjelasan] + tambahan), produk)

    def _rekomendasi_multi(self, a, k, pesan, catatan, kecuali=(), ikut_tampil=False):
        """"serum atau toner" / "2 serum sama 3 toner" -> tiap kategori dicari
        terpisah dengan profil yang sama, ditampilkan per kelompok.
        ikut_tampil: jumlah per kelompok = yang tadi tampil di kelompok itu
        ("yang lain dong" / "ada yang lebih murah?")."""
        p = k["profil"]
        jumlah_per = dict(a["multi"])
        tampil_per = {}
        for i in k["tampil"]:
            tampil_per[self._kategori_id.get(i)] = tampil_per.get(self._kategori_id.get(i), 0) + 1
        bagian, catatan_grup = [], []
        for kat in k["kategori"]:
            diminta = jumlah_per.get(kat) or a["jumlah"] or (ikut_tampil and tampil_per.get(kat)) or TOP_N_DEFAULT
            df = self._cari(p, kat, kecuali=kecuali).head(diminta)
            label = nlu.LABEL_KATEGORI[kat]
            if df.empty and kecuali:
                catatan_grup.append(f"Semua **{label}** yang cocok sudah aku tampilkan, nggak ada pilihan lain lagi.")
            elif df.empty:
                catatan_grup.append(f"Nggak ketemu **{label}** yang cocok dengan kriteria kamu.")
            elif len(df) < diminta:
                catatan_grup.append(f"{label.capitalize()}: cuma ketemu **{len(df)} produk** yang cocok.")
            bagian.append((label, df))
        isi = [(label, df) for label, df in bagian if not df.empty]
        if not isi:
            k["pool"], k["tampil"], k["alasan"] = [], [], {}
            return self._respons(k, "kosong", "\n\n".join(catatan + catatan_grup))

        gabungan = pd.concat([df for _, df in isi], ignore_index=True)
        k["alasan"] = {}
        produk, penjelasan = self._susun_produk(gabungan, k, pesan, otomatis=False)
        k["pool"] = list(k["tampil"])
        grup, mulai = [], 0
        for label, df in isi:
            grup.append({"judul": label.capitalize(), "produk": produk[mulai:mulai + len(df)]})
            mulai += len(df)
        pembuka = "Ini " + " dan ".join(f"{len(df)} {label}" for label, df in isi) + \
            (" lain yang belum aku tampilkan sebelumnya" if kecuali else "") + \
            f" buat {self._teks_profil(p)}, aku pisah per kategori."
        if not penjelasan or penjelasan == CATATAN_TANPA_LLM:  # tanpa LLM: pembuka di atas sudah cukup
            pembuka += " Alasan tiap produk ada di kartunya masing-masing."
        teks = "\n\n".join(catatan + [pembuka] + ([penjelasan] if penjelasan else []) + catatan_grup
                           + self._pengingat_kategori(a, k) + ([CATATAN_MEDIS_LUNAK] if a["medis_lunak"] else []))
        return self._respons(k, "rekomendasi", teks, produk, grup)

    def _pengingat_kategori(self, a, k):
        """Filter kategori sticky yang terbawa dari pesan sebelumnya -> ingatkan
        pengguna, supaya tidak bingung mengapa hasilnya hanya kategori itu."""
        if k["kategori"] and not a["kategori"] and not a["multi"]:
            return [f"_(Masih pakai filter kategori **{self._label_kategori(k['kategori'])}**. Bilang \"semua "
                    "kategori\" kalau mau cari dari semua kategori.)_"]
        return []

    def _ubah_jumlah(self, a, k):
        """"2 aja deh" / "banyakin" -> potong/tambah dari hasil yang SAMA."""
        n = a["jumlah"]
        tampil = k["tampil"]
        tambahan = [i for i in k["pool"] if i not in tampil]
        ids = tampil[:n] if n <= len(tampil) else tampil + tambahan[:n - len(tampil)]
        df = self.cbf.ambil_produk(ids)
        produk, _ = self._susun_produk(df, k, None)
        if len(ids) < n:
            teks = (f"Dari hasil sebelumnya, cuma ada **{len(ids)} produk** yang cocok dengan kriteria kamu, "
                    "jadi ini semuanya.")
        elif n < len(tampil):
            teks = f"Oke, ini {n} teratas dari rekomendasi tadi."
        else:
            teks = f"Oke, ini jadi {n} produk (lanjutan dari rekomendasi tadi, urutannya tetap)."
        return self._respons(k, "rekomendasi", teks, produk)

    def _susun_produk(self, df, k, pesan, lain=False, otomatis=True):
        """Kartu produk untuk df (urut). Alasan yang sudah pernah dibuat untuk
        produk yang sama dipakai ulang (konsisten); sisanya dari LLM, atau
        alasan otomatis kalau LLM tidak tersedia. Mencatat df sebagai daftar
        yang sedang tampil di konteks. lain: ini hasil "yang lain dong".
        otomatis=False: penjelasan None kalau LLM tidak tersedia (pemanggil
        menyusun kalimatnya sendiri). return: (produk, penjelasan umum)."""
        p = k["profil"]
        baru = df[~df["id"].isin(list(k["alasan"]))]
        profil_llm = {**p, "kategori": [nlu.LABEL_KATEGORI[x] for x in k["kategori"]]}
        narasi = self.generator.narasi(baru, profil_llm, pesan) if (self.generator and not baru.empty) else None
        alasan_llm = dict(zip(baru["id"], narasi["alasan_per_produk"])) if narasi else {}
        for _, row in baru.iterrows():
            langgar = self._klaim_tidak_berdasar(alasan_llm.get(row["id"]) or "", row)
            if langgar:  # alasan LLM mengklaim hal yang tidak ada di data -> pakai alasan otomatis
                print(f"[percakapan] alasan LLM untuk {row['id']} dibuang: {'; '.join(langgar)}")
                alasan_llm[row["id"]] = ""
        produk, alasan_baru = [], {}
        for i, (_, row) in enumerate(df.iterrows()):
            alasan = k["alasan"].get(row["id"]) or (alasan_llm.get(row["id"]) or "").strip() \
                or self._alasan_otomatis(row, p)
            alasan_baru[row["id"]] = alasan
            produk.append(self._produk(i + 1, row, alasan))
        k["tampil"] = list(df["id"])
        k["alasan"] = alasan_baru
        k["fokus"] = "tampil"
        k["sudah_tampil"] = list(dict.fromkeys(k["sudah_tampil"] + k["tampil"]))[-MAKS_SUDAH_TAMPIL:]
        if narasi and narasi["explanation"]:
            penjelasan = narasi["explanation"]
            if lain:
                penjelasan = "Ini pilihan lain yang belum aku tampilkan sebelumnya.\n\n" + penjelasan
        else:
            penjelasan = self._penjelasan_otomatis(len(df), p, k["kategori"], lain) if otomatis else None
            if self.generator and not baru.empty and narasi is None:  # LLM ada tapi gagal -> bilang terus terang
                penjelasan = f"{penjelasan}\n\n{CATATAN_TANPA_LLM}" if penjelasan else CATATAN_TANPA_LLM
        return produk, penjelasan

    def _klaim_tidak_berdasar(self, alasan, row):
        """Klaim di alasan LLM yang tidak didukung data produk: cocok untuk
        tipe kulit yang tidak tercatat (termasuk "semua jenis kulit" saat
        datanya kosong), bahan aktif yang tidak ada di nama/kandungan/deskripsi,
        rating/ulasan padahal belum ada, atau persen ulasan positif yang salah.
        return: list pelanggaran (kosong = aman)."""
        if not alasan:
            return []
        langgar = []
        jujur = bool(_POLA_JUJUR_KOSONG.search(alasan))
        tag = set(_tag(row["tipe_kulit_cocok"]))
        disebut = {_TIPE_KATA[t.lower()] for m in _POLA_SEBUT_TIPE.finditer(alasan)
                   for t in re.findall(_KATA_TIPE, m.group(1) or m.group(2), re.I)}
        semua = bool(_POLA_SEMUA_TIPE.search(alasan))
        if not tag and (disebut or semua) and not jujur:
            langgar.append("klaim tipe kulit padahal datanya kosong")
        elif tag and (disebut - tag or (semua and len(tag) < len(TIPE_KULIT_VALID))):
            langgar.append(f"klaim tipe kulit di luar data ({', '.join(sorted(disebut - tag)) or 'semua jenis kulit'})")
        sumber = self._teks_sumber.get(row["id"], "")
        teks = alasan.lower()
        for kelompok in BAHAN_AKTIF:
            sebut = [b for b in kelompok if re.search(rf"\b{re.escape(b)}\b", teks)]
            if sebut and not any(re.search(rf"\b{re.escape(b)}\b", sumber) for b in kelompok):
                langgar.append(f"bahan {sebut[0]} tidak ada di data produk")
        n = 0 if _kosong(row["jml_ulasan"]) else int(row["jml_ulasan"])
        if (not n or _kosong(row["skor_sentimen"])) and _POLA_KLAIM_ULASAN.search(alasan) \
                and "belum ada ulasan" not in teks:
            langgar.append("klaim ulasan padahal belum ada ulasan")
        elif n and not _kosong(row["skor_sentimen"]):
            benar = round(float(row["skor_sentimen"]) * 100)
            salah = [int(m.group(1)) for m in _POLA_PERSEN_ULASAN.finditer(alasan) if abs(int(m.group(1)) - benar) > 1]
            if salah:
                langgar.append(f"persen ulasan positif salah ({salah[0]}% vs data {benar}%)")
        if _kosong(row["rating"]) and _POLA_KLAIM_RATING.search(alasan) and "belum ada rating" not in teks:
            langgar.append("klaim rating padahal belum ada rating")
        return langgar

    def _tanpa_hasil(self, k, kategori, catatan, diminta):
        """0 produk cocok -> bilang terus terang + tawarkan kriteria mana yang
        bisa dilonggarkan, dihitung dari data dan diurutkan dari yang paling
        masuk akal (budget, lalu kategori). TIDAK ada yang dilonggarkan
        diam-diam: profil & filter user tetap. Kalau budget penyebabnya,
        pilihan terdekat ditampilkan dengan tanda "di luar budget"."""
        p = k["profil"]
        k["pool"], k["tampil"], k["alasan"] = [], [], {}
        label = nlu.LABEL_KATEGORI[kategori] if kategori else "produk"
        ada_budget = bool(p["budget_max"] or p["budget_min"])
        luar = self._cari(p, kategori, top_n=1000, pakai_budget=False) if ada_budget else pd.DataFrame()
        luar = luar[luar["harga"].notna()] if not luar.empty else luar
        n_kategori = len(self._cari(p, None, top_n=1000)) if kategori else 0
        n_keduanya = len(self._cari(p, None, top_n=1000, pakai_budget=False)) if kategori and ada_budget else 0

        opsi, alternatif = [], None
        if not luar.empty and p["budget_max"]:
            alternatif = luar.sort_values("harga").head(diminta)
            termurah = float(alternatif["harga"].iloc[0])
            saran = -(-termurah // 5000) * 5000  # dibulatkan ke atas per Rp5.000
            opsi.append(f"**Budget**: ada {len(luar)} {label} yang cocok kalau budgetnya dinaikin. Yang paling murah "
                        f"mulai {rupiah(termurah)}, jadi naikin budget ke sekitar {rupiah(saran)} (misalnya bilang "
                        f"\"budget {saran / 1000:.0f}rb\").")
        elif not luar.empty:
            alternatif = luar.sort_values("harga", ascending=False).head(diminta)
            opsi.append(f"**Batas bawah harga**: ada {len(luar)} {label} yang cocok di bawah "
                        f"{rupiah(p['budget_min'])}; yang paling mahal {rupiah(alternatif['harga'].iloc[0])}. Bilang "
                        "\"budget bebas\" kalau mau batasnya dilepas.")
        if n_kategori:
            opsi.append(f"**Kategori**: di kategori lain ada {n_kategori} produk yang cocok dengan budget kamu. Bilang "
                        "\"semua kategori\" kalau mau aku carikan dari semua kategori.")
        if not opsi and n_keduanya:
            opsi.append(f"Baru ada hasil ({n_keduanya} produk) kalau **budget dan kategori sama-sama dilonggarkan**: "
                        "bilang \"semua kategori\", lalu naikin budgetnya.")

        kriteria = self._teks_profil(p) + (f", kategori {label}" if kategori else "")
        teks = [f"Nggak ada {label} yang cocok dengan semua kriteria kamu ({kriteria})."]
        if not opsi:
            teks.append("Bahkan tanpa filter budget & kategori pun nggak ada produk yang cocok dengan tipe dan masalah "
                        "kulit kamu di data aku. Coba ganti masalah kulit yang dicari, misalnya \"masalah kulitku "
                        "kusam\".")
            return self._respons(k, "kosong", "\n\n".join(catatan + teks))
        if alternatif is not None:
            teks.append(f"Ini {len(alternatif)} pilihan terdekatnya, tapi **di luar budget kamu** ya (budget kamu "
                        "tetap, nggak aku ubah).")
        teks.append("Kriteria yang bisa dilonggarkan, dari yang paling masuk akal:\n\n"
                    + "\n".join(f"{i}. {o}" for i, o in enumerate(opsi, 1)))
        if alternatif is None:
            return self._respons(k, "kosong", "\n\n".join(catatan + teks))
        produk, _ = self._susun_produk(alternatif, k, None)
        for x in produk:
            x["di_luar_budget"] = True
        k["pool"] = list(k["tampil"])
        return self._respons(k, "di_luar_budget", "\n\n".join(catatan + teks), produk)

    # ---------- di luar rekomendasi (bagian 7): medis, di luar topik, basa-basi ----------

    def _di_luar_rekomendasi(self, a, k):
        """Pesan yang tidak dijawab dengan rekomendasi. Konteks (daftar yang
        sedang tampil, profil) TIDAK diubah, jadi percakapan bisa lanjut."""
        p, intent = k["profil"], a["intent"]
        contoh = "\"rekomendasiin sunscreen dong\" atau \"serum buat jerawat di bawah 100rb\""
        if intent == "medis":
            soal = ", ".join(_ALASAN_MEDIS[m] for m in a["medis"])
            teks = [f"Soal {soal}, aku nggak bisa kasih jawaban pasti. Itu perlu dikonsultasikan ke **dokter kulit "
                    "(dermatologis)** karena butuh pemeriksaan langsung. Aku cuma chatbot rekomendasi produk skincare "
                    "umum (yang dijual bebas) berdasarkan data, bukan pengganti konsultasi medis."]
            if "kehamilan" in a["medis"]:
                teks.append("Data produk aku juga nggak mencatat keamanan produk saat hamil/menyusui, jadi aku nggak "
                            "mau menebak.")
            teks.append(f"Kalau mau, aku tetap bisa carikan produk skincare umum untuk {self._teks_profil(p)}. "
                        "Bilang aja \"carikan produknya\".")
            return self._respons(k, "medis", "\n\n".join(teks))
        if intent == "di_luar_topik":
            return self._respons(k, "di_luar_topik",
                                 "Maaf, itu di luar cakupanku. Aku khusus bantu rekomendasi produk skincare wajah "
                                 "(dari data produk & ulasan Shopee), jadi nggak bisa jawab soal itu.\n\n"
                                 f"Kalau soal skincare, aku siap bantu! Misalnya {contoh}. Ketik \"bantuan\" buat "
                                 "lihat semua yang bisa aku bantu.")
        if intent == "tidak_jelas":
            return self._respons(k, "klarifikasi",
                                 "Maaf, aku belum nangkap maksudnya. Coba ceritakan kondisi kulit kamu atau produk yang "
                                 f"kamu cari, misalnya {contoh}. Ketik \"bantuan\" buat lihat semua yang bisa aku bantu.")
        if intent == "sapaan":
            return self._respons(k, "sapaan",
                                 f"Halo! Aku Dewy, asisten rekomendasi skincare. Profil kamu sekarang: "
                                 f"{self._teks_profil(p)}. Mau aku carikan apa? Misalnya {contoh}.")
        if intent == "terima_kasih":
            return self._respons(k, "sapaan", "Sama-sama! Kalau masih mau cari, bandingkan, atau lihat ulasan "
                                              "produk, tinggal bilang ya.")
        if intent == "konfirmasi":
            return self._respons(k, "sapaan", "Oke! Kalau ada yang mau dicari atau ditanyain lagi, tinggal bilang ya.")
        return self._respons(k, "bantuan", "\n".join([
            "Aku Dewy, chatbot rekomendasi skincare berdasarkan data produk & ulasan Shopee. Yang bisa aku bantu:",
            "",
            "- **Rekomendasi sesuai profil kulit:** \"rekomendasiin sunscreen dong\", \"3 serum di bawah 100rb\"",
            "- **Ganti profil di tengah chat:** \"kulitku sebenarnya kombinasi\", \"budget 50rb aja\"",
            "- **Alasan & info produk:** \"kenapa nomor 2 direkomendasiin?\", \"bahan aktif nomor 1 apa?\"",
            "- **Bandingkan & pilih:** \"bandingkan nomor 1 sama 2\", \"yang bagusan mana?\"",
            "- **Ulasan asli pembeli:** \"review nomor 1 dong\", \"keluhan orang soal nomor 2 apa?\"",
            "- **Pilihan lain:** \"yang lain dong\", \"ada yang lebih murah?\", \"urutin dari yang termurah\"",
            "",
            "Aku bukan pengganti dokter kulit ya. Untuk obat resep atau kondisi kulit yang parah, konsultasi ke "
            "dermatologis."]))

    def _info_produk(self, a, k):
        """"harga nomor 2 berapa?" / "bahan aktifnya apa?" / "X bagus ga?" ->
        dijawab langsung dari data (tidak pernah mengarang). Profil TIDAK
        diubah; kalau pertanyaannya menyebut tipe/masalah kulit lain ("cocok ga
        buat kulit sensitif?"), produknya dinilai terhadap itu."""
        ids, masalah = self._target_produk(a, k)
        if not ids:
            if not masalah:
                masalah.append("Produk yang mana? Minta rekomendasi dulu, atau sebut nama produknya, misalnya "
                               "\"harga wardah lightening face mist berapa?\".")
            return self._respons(k, "klarifikasi", "\n\n".join(masalah))
        teks = list(masalah)
        if len(ids) > MAKS_JELASKAN:
            teks.append(f"Aku tampilkan {MAKS_JELASKAN} produk pertama dulu ya.")
            ids = ids[:MAKS_JELASKAN]
        p = dict(k["profil"])
        if a["tipe_kulit"] or a["masalah_kulit"]:
            p["tipe_kulit"] = a["tipe_kulit"] or p["tipe_kulit"]
            p["masalah_kulit"] = a["masalah_kulit"] or p["masalah_kulit"]
            teks.append(f"_Aku nilai untuk kulit {p['tipe_kulit']}"
                        + (f" dengan masalah {', '.join(nlu.LABEL_MASALAH[m] for m in p['masalah_kulit'])}"
                           if p["masalah_kulit"] else "") + " (profil kamu nggak aku ubah)._")
        bagian = {"harga": ("harga",), "kandungan": ("kandungan",), "rating": ("ulasan",), "sentimen": ("ulasan",),
                  "kecocokan": ("tipe", "masalah")}.get(a["atribut"], ("kategori", "harga", "ulasan", "tipe", "masalah",
                                                                        "kandungan"))
        for _, row in self.cbf.bandingkan_produk(ids).iterrows():
            teks.append(self._rincian_alasan(row, k, p, bagian))
        return self._respons(k, "info_produk", "\n\n".join(teks))

    # ---------- percakapan lanjutan (bagian 6) ----------

    def _lebih_murah(self, a, k, pesan, catatan):
        """"ada yang lebih murah?" -> budget_max diketatkan jadi di bawah harga
        termurah hasil tadi. Sticky (berlaku sampai diganti) dan diumumkan;
        bila memang tidak ada yang lebih murah, budget TIDAK diubah."""
        p = k["profil"]
        harga = self.cbf.ambil_produk(k["tampil"])["harga"].dropna()
        if harga.empty:
            return self._respons(k, "klarifikasi", "\n\n".join(catatan + [
                "Harga produk-produk tadi nggak ada di data, jadi aku nggak bisa cari yang lebih murah dari itu. "
                "Sebut budget kamu aja ya, misalnya \"budget 50rb\"."]))
        termurah = int(harga.min())
        if p["budget_min"] and termurah - 1 < p["budget_min"]:
            return self._respons(k, "klarifikasi", "\n\n".join(catatan + [
                f"Yang termurah tadi {rupiah(termurah)}, sudah mepet batas bawah yang kamu minta "
                f"({rupiah(p['budget_min'])}). Mau batas bawahnya dihapus? Bilang \"budget bebas\" terus minta lagi."]))
        uji = {**p, "budget_max": termurah - 1}
        kategori = k["kategori"]
        ada = any(not self._cari(uji, kat, top_n=1).empty for kat in (kategori or [None]))
        if not ada:
            label = self._label_kategori(kategori) if kategori else "produk"
            return self._respons(k, "kosong", "\n\n".join(catatan + [
                f"Produk tadi sudah yang paling murah: nggak ada {label} lain yang cocok dengan profil kamu di bawah "
                f"{rupiah(termurah)}. Budget kamu tetap **{teks_budget(p)}**."]))
        p["budget_max"] = termurah - 1
        catatan = catatan + [f"Budget aku ketatkan jadi **di bawah {rupiah(termurah)}** (lebih murah dari yang "
                             "termurah tadi). Budget ini berlaku terus sampai kamu ganti, misalnya \"budget 100rb\" "
                             "atau \"budget bebas\"."]
        return self._rekomendasi(a, k, pesan, catatan, diminta=a["jumlah"] or len(k["tampil"]) or TOP_N_DEFAULT)

    def _urutkan(self, a, k):
        """"urutin dari yang termurah" -> urutkan ulang daftar yang SAMA (bukan
        cari ulang). Nilai kosong selalu ditaruh paling bawah."""
        kolom = {"harga_asc": ("harga", True, "harga termurah", "tanpa data harga"),
                 "harga_desc": ("harga", False, "harga termahal", "tanpa data harga"),
                 "rating": ("rating", False, "rating tertinggi", "belum ada rating"),
                 "ulasan": ("jml_ulasan", False, "ulasan terbanyak", "belum ada ulasan"),
                 "sentimen": ("skor_sentimen", False, "ulasan paling positif", "belum ada ulasan")}
        if a["urut"] not in kolom:
            return self._respons(k, "klarifikasi", "Mau diurutkan berdasarkan apa? Bisa dari harga termurah, harga "
                                                  "termahal, rating tertinggi, ulasan terbanyak, atau ulasan paling "
                                                  "positif.")
        nama_kolom, naik, label, kosong = kolom[a["urut"]]
        df = self.cbf.ambil_produk(k["tampil"])
        nilai = df[nama_kolom].astype(float)
        if nama_kolom in ("skor_sentimen", "jml_ulasan"):
            nilai = nilai.where(df["jml_ulasan"].fillna(0) > 0)  # tanpa ulasan = kosong, bukan 0% / 0
        # hasil per kategori -> diurutkan di dalam tiap kelompok (nomor tetap
        # urut per kelompok); mergesort = stabil: nilai sama tetap di urutan semula
        multi = len(k["kategori"]) >= 2
        kelompok = df["kategori"].map({kat: i for i, kat in enumerate(k["kategori"])}).fillna(len(k["kategori"])) \
            if multi else pd.Series(0, index=df.index)
        kunci = pd.DataFrame({"g": kelompok, "kosong": nilai.isna(), "v": nilai if naik else -nilai})
        urutan = kunci.sort_values(["g", "kosong", "v"], kind="mergesort").index
        df, n_kosong = df.loc[urutan].reset_index(drop=True), int(nilai.isna().sum())
        pool = k["pool"]
        produk, _ = self._susun_produk(df, k, None)
        k["pool"] = k["tampil"] + [i for i in pool if i not in k["tampil"]]
        teks = [f"Oke, produk tadi diurutkan dari **{label}** di tiap kategori." if multi
                else f"Oke, ini {len(df)} produk tadi diurutkan dari **{label}**."]
        if n_kosong:
            teks.append(f"{n_kosong} produk {kosong} aku taruh paling bawah." if n_kosong < len(df)
                        else f"Semua produknya {kosong}, jadi urutannya nggak berubah.")
        grup = None
        if multi:
            grup = [{"judul": nlu.LABEL_KATEGORI[kat].capitalize(), "produk": [x for x in produk if x["kategori"] == kat]}
                    for kat in k["kategori"]]
            grup = [g for g in grup if g["produk"]]
        return self._respons(k, "rekomendasi", "\n\n".join(teks), produk, grup)

    def _target_produk(self, a, k):
        """Produk yang dirujuk pertanyaan lanjutan: nomor -> daftar terakhir,
        nama -> seluruh katalog, tanpa rujukan -> daftar yang sedang tampil.
        return: (ids, pesan_masalah)."""
        r, tampil = a["rujukan"], k["tampil"]
        ids, masalah = [], []
        for n in r["nomor"]:
            self._id_nomor(n, tampil, ids, masalah)
        for nama in r["nama"]:
            h = self._cari_nama(nama)
            if h["status"] == "ketemu":
                ids.append(h["id"])
            elif h["status"] == "ambigu":
                daftar = "\n".join(f"- {self._nama[i]}" for i in h["kandidat"])
                masalah.append(f"Ada banyak produk yang cocok dengan \"{nama}\". Maksud kamu yang mana? Misalnya:\n\n"
                               f"{daftar}\n\nSebut nama produknya lebih lengkap ya.")
            else:
                masalah.append(f"Produk \"{nama}\" nggak ada di data aku, jadi aku nggak bisa kasih info apa pun "
                               "soal produk itu (aku nggak mau mengarang data produk yang nggak ada). Coba cek lagi "
                               "ejaan namanya, atau minta aku carikan produk lain yang ada di data.")
        if r["semua"]:
            ids = list(tampil) or (k["banding"] if k["fokus"] == "banding" else [])
        return [i for i in dict.fromkeys(ids) if i in self._id_valid], masalah

    def _id_nomor(self, n, tampil, ids, masalah):
        """Nomor di daftar terakhir -> id produk (ditambahkan ke ids), atau
        alasan kenapa tidak bisa (ditambahkan ke masalah) -- termasuk produk
        yang sudah dinonaktifkan admin sejak daftar itu ditampilkan."""
        urut = len(tampil) if n == -1 else n
        if tampil and 1 <= urut <= len(tampil):
            if tampil[urut - 1] in self._id_valid:
                ids.append(tampil[urut - 1])
            else:
                masalah.append(PESAN_TIDAK_TERSEDIA.format(n=urut))
        elif tampil:
            masalah.append(f"Nomor {n} nggak ada di daftar terakhir (cuma ada nomor 1–{len(tampil)}).")
        else:
            masalah.append(f"Belum ada daftar rekomendasi, jadi nomor {n} belum merujuk ke produk apa pun.")

    def _alasan(self, a, k):
        """"kenapa produk ini direkomendasiin?" -> rincian dari data: tag tipe
        kulit / masalah kulit / kategori vs profil, harga vs budget, ulasan."""
        ids, masalah = self._target_produk(a, k)
        if not ids:
            if not masalah:
                masalah.append("Belum ada produk yang aku rekomendasikan di percakapan ini. Minta rekomendasi dulu "
                               "ya, misalnya \"rekomendasiin sunscreen dong\".")
            return self._respons(k, "klarifikasi", "\n\n".join(masalah))
        p = k["profil"]
        teks = list(masalah)
        if len(ids) > MAKS_JELASKAN:
            teks.append(f"Aku jelaskan {MAKS_JELASKAN} produk pertama dulu ya.")
            ids = ids[:MAKS_JELASKAN]
        kategori = f"kategorinya **{self._label_kategori(k['kategori'])}**" if k["kategori"] \
            else "kategorinya bebas (kamu belum memilih kategori)"
        teks.append(f"Produk aku pilih lewat 2 tahap. **Pertama, disaring:** tipe kulitnya harus cocok dengan kulit "
                    f"**{p['tipe_kulit']}** (atau datanya belum ada), masalah kulit yang ditangani harus nyambung "
                    f"dengan masalah kamu, harganya masuk budget **{teks_budget(p)}**, dan {kategori}. "
                    "**Kedua, diurutkan:** dari yang deskripsi, kandungan, dan tag-nya paling mirip dengan profil "
                    "kamu.")
        df = self.cbf.bandingkan_produk(ids)
        for _, row in df.iterrows():
            teks.append(self._rincian_alasan(row, k))
        return self._respons(k, "alasan", "\n\n".join(teks))

    def _rincian_alasan(self, row, k, p=None, bagian=("tipe", "masalah", "kategori", "harga", "ulasan")):
        """Rincian 1 produk dari data, baris per kriteria (bagian = kriteria
        yang ditampilkan). p: profil penilai (default profil percakapan)."""
        p = p or k["profil"]
        pid = row["id"]
        judul = f"**{self._label_banding(pid, k)}**"
        if pid not in k["tampil"] and pid not in k["sudah_tampil"]:
            judul += " _(bukan dari daftar rekomendasi tadi)_"
        baris, lolos = [], True

        if "kategori" in bagian:
            label_kat = None if _kosong(row["kategori"]) else nlu.LABEL_KATEGORI.get(row["kategori"], row["kategori"])
            merek = "" if _kosong(row["brand"]) else f" (brand {row['brand']})"
            if not label_kat:
                baris.append(f"Kategori: tidak ada data{merek}.")
            elif k["kategori"] and row["kategori"] in k["kategori"]:
                baris.append(f"Kategori: **{label_kat}**{merek}, sesuai yang kamu minta ✓.")
            elif k["kategori"]:
                baris.append(f"Kategori: {label_kat}{merek}, bukan kategori yang kamu minta.")
            else:
                baris.append(f"Kategori: {label_kat}{merek} (kamu belum memilih kategori tertentu).")

        if "tipe" in bagian:
            tipe_tag = _tag(row["tipe_kulit_cocok"])
            if not tipe_tag:
                baris.append("Tipe kulit: belum ada data kecocokan tipe kulit. Kalau produk ini direkomendasikan, itu "
                             "karena datanya kosong, **bukan** karena pasti cocok untuk kulit kamu.")
            elif p["tipe_kulit"] in tipe_tag:
                baris.append(f"Tipe kulit: ditandai cocok untuk kulit **{p['tipe_kulit']}** ✓ "
                             f"(data produk: {', '.join(tipe_tag)}).")
            else:
                lolos = False
                baris.append(f"Tipe kulit: **tidak** ditandai untuk kulit {p['tipe_kulit']} (data produk: "
                             f"{', '.join(tipe_tag)}).")

        if "masalah" in bagian:
            masalah_tag = _tag(row["masalah_kulit_cocok"])
            irisan = [nlu.LABEL_MASALAH[m] for m in p["masalah_kulit"] if m in masalah_tag]
            punya = ", ".join(nlu.LABEL_MASALAH.get(m, m) for m in masalah_tag)
            if not p["masalah_kulit"]:
                baris.append("Masalah kulit: kamu belum menyebut masalah kulit, jadi ini nggak dipakai buat menyaring.")
            elif not masalah_tag:
                baris.append("Masalah kulit: belum ada data masalah kulit yang ditangani produk ini.")
            elif irisan:
                baris.append(f"Masalah kulit: menangani **{', '.join(irisan)}** ✓ (data produk: {punya}).")
            else:
                lolos = False
                baris.append(f"Masalah kulit: nggak menangani masalah kulit kamu (data produk: {punya}).")

        if "harga" in bagian:
            if _kosong(row["harga"]):
                baris.append(f"Harga: {_harga_kosong(row)}.")
            else:
                h = float(row["harga"])
                masuk = (not p["budget_max"] or h <= p["budget_max"]) and (not p["budget_min"] or h >= p["budget_min"])
                lolos &= masuk
                baris.append(f"Harga: {rupiah(h)}, " + (f"masuk budget kamu ({teks_budget(p)}) ✓." if masuk
                                                        else f"**di luar** budget kamu ({teks_budget(p)})."))

        if "ulasan" in bagian:
            n = 0 if _kosong(row["jml_ulasan"]) else int(row["jml_ulasan"])
            if n and not _kosong(row["skor_sentimen"]):
                rating = "" if _kosong(row["rating"]) else f", rating ★ {float(row['rating']):.1f}"
                baris.append(f"Ulasan: {float(row['skor_sentimen']) * 100:.0f}% positif dari {n} ulasan{rating}.")
            else:
                baris.append("Ulasan: belum ada ulasan.")

        if "kandungan" in bagian:
            bahan = self._bahan(row["kandungan"])
            baris.append(f"Kandungan (dari data): {', '.join(bahan)}." if bahan else
                         "Kandungan: **tidak ada data kandungan** buat produk ini di sistem, jadi aku nggak bisa "
                         "bilang bahan aktifnya apa (aku nggak mau menebak).")

        if not lolos:
            baris.append("_Karena ada kriteria yang nggak terpenuhi di atas, produk ini nggak masuk rekomendasi "
                         "untuk profil ini._")
        return judul + "\n" + "\n".join(f"- {b}" for b in baris)

    def _ulasan(self, a, k, pesan):
        """"ada review bagus soal produk ini ga?" -> kutipan ulasan ASLI dari
        index RAG (ChromaDB), disaring per produk. Bukan dijawab dari CBF."""
        ids, masalah = self._target_produk(a, k)
        if not ids:
            if not masalah:
                masalah.append("Produk yang mana? Minta rekomendasi dulu, atau sebut nama produknya, misalnya "
                               "\"review skintific moisturizer dong\".")
            return self._respons(k, "klarifikasi", "\n\n".join(masalah))
        teks = list(masalah)
        if len(ids) > MAKS_JELASKAN:
            teks.append(f"Aku tampilkan ulasan {MAKS_JELASKAN} produk pertama dulu ya.")
            ids = ids[:MAKS_JELASKAN]
        if self.rag is None:
            teks.append("Kutipan ulasan lagi nggak bisa aku ambil (index ulasan belum siap), jadi ini ringkasan dari "
                        "data saja:")
        maks = MAKS_KUTIPAN if len(ids) == 1 else 2
        p = k["profil"]
        query = f"{pesan} kulit {p['tipe_kulit'] or ''} {' '.join(nlu.LABEL_MASALAH[m] for m in p['masalah_kulit'])}"
        for _, row in self.cbf.bandingkan_produk(ids).iterrows():
            teks.append(self._ringkas_ulasan(row, k, query, a["preferensi_ulasan"], maks))
        if self.rag is not None:
            teks.append("_Kutipan diambil apa adanya dari ulasan pembeli di Shopee (ulasan soal pengiriman/penjual "
                        "nggak aku tampilkan)._")
        return self._respons(k, "ulasan", "\n\n".join(teks))

    def _ringkas_ulasan(self, row, k, query, preferensi, maks):
        judul = f"**{self._label_banding(row['id'], k)}**"
        n = 0 if _kosong(row["jml_ulasan"]) else int(row["jml_ulasan"])
        if not n or _kosong(row["skor_sentimen"]):
            return judul + "  \nBelum ada ulasan untuk produk ini di data aku."
        ringkasan = f"{float(row['skor_sentimen']) * 100:.0f}% ulasan positif dari {n} ulasan"
        if not _kosong(row["rating"]):
            ringkasan += f", rating ★ {float(row['rating']):.1f}"
        if self.rag is None or _kosong(row["link"]):
            return f"{judul}  \n{ringkasan}."
        # positif lebih dulu + 1 yang kurang puas agar berimbang; bila yang ditanya
        # keluhannya, sebaliknya (netral dipakai bila tidak ada yang negatif)
        keluhan = f"{KUERI_KELUHAN} {query}"
        # "  \n" = pindah baris di markdown (judul & ringkasan tidak menempel)
        bagian = [f"{judul}  \n{ringkasan}."]
        try:
            positif = self._kutipan(query, row["link"], "Positif", maks if preferensi != "Negatif" else 1)
            negatif = self._kutipan(keluhan, row["link"], "Negatif", maks if preferensi == "Negatif" else 1)
            if preferensi == "Negatif":
                if negatif:
                    bagian.append(f"Yang kurang puas:\n\n{self._blok_kutipan(negatif)}")
                else:
                    netral = self._kutipan(keluhan, row["link"], "Netral", maks)
                    bagian.append("Nggak ada ulasan negatif soal produknya di data aku."
                                  + (" Yang paling mendekati keluhan (ulasan netral):\n\n" + self._blok_kutipan(netral)
                                     if netral else ""))
                if positif:
                    bagian.append(f"Sebagai pembanding, yang bilang bagus:\n\n{self._blok_kutipan(positif)}")
            else:
                if positif:
                    bagian.append(f"Yang bilang bagus:\n\n{self._blok_kutipan(positif)}")
                elif preferensi == "Positif":
                    bagian.append("Nggak ada ulasan positif soal produknya yang bisa aku kutip.")
                if negatif:
                    bagian.append(f"Yang kurang puas:\n\n{self._blok_kutipan(negatif)}")
        except Exception:  # index rusak/tidak bisa dibaca -> tetap jawab dari ringkasan data
            return f"{judul}  \n{ringkasan}. (Kutipan ulasannya lagi nggak bisa diambil.)"
        if len(bagian) == 1:
            bagian.append("Belum ada ulasan yang membahas produknya secara spesifik (kebanyakan soal pengiriman/"
                          "penjual atau terlalu singkat), jadi nggak ada yang aku kutip.")
        return "\n\n".join(bagian)

    def _kutipan(self, query, link, sentimen, jumlah):
        """Kutipan ulasan asli satu produk dengan label sentimen tertentu.
        Dibuang: yang soal pengiriman/penjual, yang belum sempat dipakai
        ("semoga cocok"), dan yang bintangnya bertolak belakang dengan
        labelnya (label "Negatif" tapi ★5 -- salah label, jangan dikutip
        sebagai keluhan). Yang membahas kulit diutamakan; di dalamnya urutan
        kemiripan makna dari RAG dipertahankan."""
        hasil = self.rag.ambil_konteks(query, link_produk=link, n_hasil=25, sentimen=sentimen)
        calon = []
        for h in hasil:
            isi = self._rapikan_kutipan(h.get("teks"))
            rating = h.get("rating")
            rating = float(rating) if isinstance(rating, (int, float)) and rating > 0 else None
            if rating is not None and ((sentimen == "Negatif" and rating >= 4) or (sentimen == "Positif" and rating <= 2)):
                continue
            if len(isi) < 15 or _POLA_ULASAN_LOGISTIK.search(isi) or _POLA_ULASAN_BELUM_COBA.search(isi) \
                    or not _POLA_ULASAN_PRODUK.search(isi) or isi in {c for c, _ in calon}:
                continue
            calon.append((isi, rating))
        calon.sort(key=lambda c: (not _POLA_ULASAN_KULIT.search(c[0]), len(c[0]) < 40))
        return calon[:jumlah]

    @staticmethod
    def _rapikan_kutipan(teks):
        """"Cocok Untuk:berminyak Tekstur:ringan  enak dipakai" -> "Cocok untuk:
        berminyak · Tekstur: ringan · enak dipakai". Isi ulasan tidak diubah,
        hanya label kemasan/keaslian (bukan tentang produknya) yang dibuang."""
        teks = re.sub(r"\s+", " ", str(teks or "")).strip()
        potong = _LABEL_ULASAN.split(teks)
        bagian = [potong[0].strip()] if potong[0].strip() else []
        for label, isi in zip(potong[1::2], potong[2::2]):
            if label.lower() not in _LABEL_BUKAN_PRODUK and isi.strip():
                bagian.append(f"{label.capitalize()}: {isi.strip()}")
        return " · ".join(bagian)

    @staticmethod
    def _blok_kutipan(kutipan):
        baris = []
        for isi, rating in kutipan:
            if len(isi) > PANJANG_KUTIPAN:
                isi = isi[:PANJANG_KUTIPAN].rsplit(" ", 1)[0] + "…"
            bintang = f" (★ {rating:.0f})" if rating is not None else ""
            baris.append(f"> \"{isi}\"{bintang}")
        return "\n>\n".join(baris)

    # ---------- perbandingan produk ----------

    def _cari_nama(self, nama):
        """Cari produk dari nama yang diketik user (boleh sebagian/typo) di
        SELURUH katalog. return: {status: 'ketemu'|'ambigu'|'tidak_ketemu',
        id, kandidat}. Ambigu = pengguna hanya menyebut brand/kata umum ("wardah",
        "wardah toner") dan ada banyak produk yang sama-sama cocok."""
        q = [t for t in nlu.normalisasi_nama(nama) if t not in _ISIAN_NAMA]
        if not q:
            return {"status": "tidak_ketemu"}
        varian = {}
        for t in q:
            cocok = {v for v in self._kosakata_nama if v == t or (len(t) >= 4 and v.startswith(t))}
            if not cocok and len(t) >= 5:
                cocok = {v for v in self._kosakata_nama if nlu._mirip(t, v)}
            varian[t] = cocok
        skor = []
        for pid, token, n_dasar, lengkap, ulasan in self._indeks_nama:
            kena = {i for i, t in enumerate(q) if varian[t] & token}
            kena |= {j for i in range(len(q) - 1) if q[i] + q[i + 1] in token for j in (i, i + 1)}
            if kena:
                skor.append((len(kena) / len(q), len(kena) / n_dasar, lengkap, ulasan, pid))
        if not skor:
            return {"status": "tidak_ketemu"}
        skor.sort(reverse=True)
        terbaik = skor[0]
        if terbaik[0] < 0.6 or (len(q) >= 2 and round(terbaik[0] * len(q)) < 2):
            return {"status": "tidak_ketemu"}
        khas = [t for t in q if t not in _KATA_UMUM_NAMA and t not in self._token_merek and not t.isdigit()]
        seri = [s for s in skor if s[0] == terbaik[0]]
        if not khas and len(seri) > 1:
            kandidat = [s[-1] for s in sorted(seri, key=lambda s: -s[3])[:3]]
            return {"status": "ambigu", "kandidat": kandidat}
        return {"status": "ketemu", "id": terbaik[-1]}

    def _label_banding(self, pid, k):
        nama = self._nama[pid]
        pendek = nama if len(nama) <= 48 else nama[:48].rsplit(" ", 1)[0] + "…"
        return f"#{k['tampil'].index(pid) + 1} {pendek}" if pid in k["tampil"] else pendek

    def _banding(self, a, k):
        r, tampil = a["rujukan"], k["tampil"]
        ids, pesan, ambigu = [], [], []
        for n in r["nomor"]:
            self._id_nomor(n, tampil, ids, pesan)
        for nama in r["nama"]:
            h = self._cari_nama(nama)
            if h["status"] == "ketemu":
                ids.append(h["id"])
            elif h["status"] == "ambigu":
                ambigu.append((nama, h["kandidat"]))
            else:
                pesan.append(f"Produk \"{nama}\" nggak ketemu di data aku, jadi nggak bisa aku bandingkan "
                             "(aku nggak mau mengarang data produk yang nggak ada).")
        if r["semua"] or not (r["nomor"] or r["nama"]):
            ids += k["banding"] if (k["fokus"] == "banding" and k["banding"]) else tampil
        ids = list(dict.fromkeys(ids))
        for nama, kandidat in ambigu:
            daftar = "\n".join(f"- {self._nama[i] if len(self._nama[i]) <= 75 else self._nama[i][:75].rsplit(' ', 1)[0] + '…'}"
                               for i in kandidat)
            pesan.append(f"Ada banyak produk yang cocok dengan \"{nama}\". Maksud kamu yang mana? Misalnya:\n\n"
                         f"{daftar}\n\nSebut nama produknya lebih lengkap ya.")

        if len(ids) < 2:
            if not pesan:
                pesan.append("Minimal 2 produk buat dibandingkan. Sebut nama produknya, atau nomor dari daftar "
                             "rekomendasi (misalnya \"bandingkan nomor 1 sama 2\").")
            return self._respons(k, "klarifikasi", "\n\n".join(pesan))
        if len(ids) > MAKS_BANDING:
            pesan.append(f"Aku bandingkan {MAKS_BANDING} produk pertama dulu ya, biar tabelnya tetap kebaca.")
            ids = ids[:MAKS_BANDING]

        df = self.cbf.bandingkan_produk(ids)
        k["banding"], k["fokus"] = ids, "banding"
        label = [self._label_banding(pid, k) for pid in df["id"]]
        tabel = self._tabel_banding(df, k["profil"], a["atribut"], label)
        kesimpulan = self._kesimpulan_banding(df, k["profil"], a["atribut"], label)
        return self._respons(k, "perbandingan", "\n\n".join(pesan + [kesimpulan]), perbandingan=tabel)

    @staticmethod
    def _kecocokan(row, p):
        """(skor, teks) kecocokan satu produk dengan profil user."""
        skor, bagian = 0, []
        tipe_tag = _tag(row["tipe_kulit_cocok"])
        if not tipe_tag:
            bagian.append("tipe kulit: tidak ada data")
        elif p["tipe_kulit"] in tipe_tag:
            skor += 1
            bagian.append(f"cocok kulit {p['tipe_kulit']} ✓")
        else:
            bagian.append(f"tidak ditandai untuk kulit {p['tipe_kulit']}")
        masalah_tag = _tag(row["masalah_kulit_cocok"])
        irisan = [nlu.LABEL_MASALAH[m] for m in p["masalah_kulit"] if m in masalah_tag]
        skor += len(irisan)
        if not masalah_tag:
            bagian.append("masalah kulit: tidak ada data")
        elif irisan:
            bagian.append(f"menangani {', '.join(irisan)} ✓")
        else:
            bagian.append("tidak menangani masalah kulit kamu")
        return skor, "; ".join(bagian)

    def _tabel_banding(self, df, p, atribut, label):
        def terbaik(nilai, cari_min=False):
            ada = [(v, i) for i, v in enumerate(nilai) if v is not None]
            if len(ada) < 2:
                return None
            pilih = (min if cari_min else max)(ada)[0]
            juara = [i for v, i in ada if v == pilih]
            return juara[0] if len(juara) == 1 else None

        harga = [None if _kosong(v) else float(v) for v in df["harga"]]
        rating = [None if _kosong(v) else float(v) for v in df["rating"]]
        sentimen = [None if _kosong(s) or not n or _kosong(n) else float(s)
                    for s, n in zip(df["skor_sentimen"], df["jml_ulasan"])]
        cocok = [self._kecocokan(row, p) for _, row in df.iterrows()]
        semua = {
            "Kategori": ([nlu.LABEL_KATEGORI.get(v, v) if not _kosong(v) else "tidak ada data" for v in df["kategori"]], None),
            "Brand": (["tidak ada data" if _kosong(v) else v for v in df["brand"]], None),
            "Harga": ([rupiah(v) if v is not None else _harga_kosong(row) for v, (_, row) in zip(harga, df.iterrows())],
                      terbaik(harga, cari_min=True)),
            "Rating": ([f"★ {v:.1f}" if v is not None else "belum ada rating" for v in rating], terbaik(rating)),
            "Ulasan": ([f"{s * 100:.0f}% positif dari {int(n)} ulasan" if s is not None else "belum ada ulasan"
                        for s, n in zip(sentimen, df["jml_ulasan"])], terbaik(sentimen)),
            "Cocok untuk kulit": ([", ".join(_tag(v)) or "tidak ada data" for v in df["tipe_kulit_cocok"]], None),
            "Menangani masalah": ([", ".join(nlu.LABEL_MASALAH.get(m, m) for m in _tag(v)) or "tidak ada data"
                                   for v in df["masalah_kulit_cocok"]], None),
            "Kandungan": (["tidak ada data" if _kosong(v) else self._rapikan_kandungan(v) for v in df["kandungan"]], None),
            "Kecocokan dengan profil kamu": ([t for _, t in cocok], terbaik([s for s, _ in cocok])),
        }
        fokus = {"harga": ["Harga"], "rating": ["Rating", "Ulasan"], "sentimen": ["Ulasan"], "kandungan": ["Kandungan"],
                 "kecocokan": ["Cocok untuk kulit", "Menangani masalah", "Kecocokan dengan profil kamu"]}
        baris = fokus.get(atribut) or list(semua)
        return {"produk": label, "baris": [{"atribut": b, "nilai": semua[b][0], "terbaik": semua[b][1]} for b in baris]}

    @staticmethod
    def _bahan(teks):
        if _kosong(teks):
            return None
        return list(dict.fromkeys(x.strip().lower() for x in re.split(r"[,;|]", str(teks)) if x.strip()))

    def _rapikan_kandungan(self, teks):
        return ", ".join(self._bahan(teks))

    def _kesimpulan_banding(self, df, p, atribut, label):
        """Kalimat kesimpulan disusun langsung dari data (bukan LLM) -- tidak
        pernah mengarang, dan tetap jalan walau LLM tidak tersedia."""
        nama = [f"**{x}**" for x in label]
        kalimat = []

        def urut(nilai, fmt, kata_min, kata_max, kosong):
            ada = [(v, n) for v, n in zip(nilai, nama) if v is not None]
            tidak = [n for v, n in zip(nilai, nama) if v is None]
            if len(ada) >= 2:
                if len({v for v, _ in ada}) == 1:
                    kalimat.append(f"{kata_min.split()[0].capitalize()}nya sama: {fmt(ada[0][0])}.")
                else:
                    lo, hi = min(ada), max(ada)
                    kalimat.append(f"{kata_min.capitalize()}: {lo[1]} ({fmt(lo[0])}); {kata_max}: {hi[1]} ({fmt(hi[0])}).")
            elif ada:
                kalimat.append(f"{kata_min.split()[0].capitalize()} {ada[0][1]}: {fmt(ada[0][0])}.")
            if tidak:
                kalimat.append(f"{', '.join(tidak)}: {kosong}.")

        if atribut in (None, "harga"):
            urut([None if _kosong(v) else float(v) for v in df["harga"]], rupiah,
                 "harga paling murah", "paling mahal", "harga tidak ada di data")
        if atribut in (None, "rating"):
            nilai = [None if _kosong(v) else float(v) for v in df["rating"]]
            ada = [(v, n) for v, n in zip(nilai, nama) if v is not None]
            if len(ada) >= 2:
                hi = max(ada)
                sama = [n for v, n in ada if v == hi[0]]
                kalimat.append(f"Rating tertinggi: {hi[1]} (★ {hi[0]:.1f})." if len(sama) == 1
                               else f"Rating tertinggi sama-sama ★ {hi[0]:.1f}: {', '.join(sama)}.")
            elif ada:
                kalimat.append(f"Rating {ada[0][1]}: ★ {ada[0][0]:.1f}.")
            tidak = [n for v, n in zip(nilai, nama) if v is None]
            if tidak:
                kalimat.append(f"{', '.join(tidak)}: belum ada rating.")
        if atribut in (None, "rating", "sentimen"):
            ada = [(float(s), int(u), n) for s, u, n in zip(df["skor_sentimen"], df["jml_ulasan"], nama)
                   if not _kosong(s) and not _kosong(u) and u]
            if len(ada) >= 2:
                s, u, n = max(ada)
                kalimat.append(f"Ulasan paling positif: {n} ({s * 100:.0f}% positif dari {u} ulasan).")
            tidak = [n for s, u, n in zip(df["skor_sentimen"], df["jml_ulasan"], nama) if _kosong(s) or _kosong(u) or not u]
            if tidak:
                kalimat.append(f"{', '.join(tidak)}: belum ada ulasan.")
        if atribut in (None, "kecocokan"):
            skor = [self._kecocokan(row, p)[0] for _, row in df.iterrows()]
            profil = f"kulit {p['tipe_kulit']}, masalah {', '.join(nlu.LABEL_MASALAH[m] for m in p['masalah_kulit'])}"
            if max(skor) == 0:
                kalimat.append(f"Belum ada yang datanya menunjukkan cocok dengan profil kamu ({profil}).")
            else:
                juara = [n for s, n in zip(skor, nama) if s == max(skor)]
                kalimat.append(f"Paling sesuai dengan profil kamu ({profil}): {', '.join(juara)}."
                               if len(juara) == 1 else f"Sama-sama sesuai dengan profil kamu ({profil}): {', '.join(juara)}.")
        if atribut == "kandungan":
            bahan = [self._bahan(v) for v in df["kandungan"]]
            ada = [set(b) for b in bahan if b]
            for b, n in zip(bahan, nama):
                if not b:
                    kalimat.append(f"{n}: tidak ada data kandungan di sistem.")
            if len(ada) >= 2:
                sama = set.intersection(*ada)
                kalimat.append(f"Bahan yang sama: {', '.join(sorted(sama))}." if sama else "Nggak ada bahan yang sama.")
                for b, n in zip(bahan, nama):
                    if b:
                        khusus = [x for x in b if x not in sama]
                        if khusus:
                            kalimat.append(f"Cuma ada di {n}: {', '.join(khusus)}.")
        return "**Kesimpulan:**\n" + "\n".join(f"- {x}" for x in kalimat)

    # ---------- "yang bagusan mana?" -> 1 pemenang ----------

    def _skor_pemenang(self, row, p, harga_kandidat):
        """Rincian skor 0-100 satu produk: kecocokan profil, kualitas ulasan,
        harga (relatif ke kandidat lain), dan total berbobot BOBOT_PEMENANG."""
        tipe_tag, masalah_tag = _tag(row["tipe_kulit_cocok"]), _tag(row["masalah_kulit_cocok"])
        tipe = 1.0 if p["tipe_kulit"] in tipe_tag else (0.5 if not tipe_tag else 0.0)  # kosong = belum diketahui
        if not masalah_tag:
            masalah = 0.5
        else:
            masalah = sum(m in masalah_tag for m in p["masalah_kulit"]) / max(len(p["masalah_kulit"]), 1)
        n = 0 if _kosong(row["jml_ulasan"]) else int(row["jml_ulasan"])
        s = self._prior_sentimen if (_kosong(row["skor_sentimen"]) or not n) else float(row["skor_sentimen"])
        ulasan = (s * n + self._prior_sentimen * ULASAN_PRIOR_N) / (n + ULASAN_PRIOR_N)
        # harga = rasio ke yang termurah (termurah 100, 12% lebih mahal ~89) -- bukan
        # min-max, yang membuat selisih Rp6rb saja langsung menjadi 100 vs 0
        ada = [h for h in harga_kandidat if h is not None]
        harga = None if _kosong(row["harga"]) else float(row["harga"])
        skor_harga = 0.5 if harga is None else min(ada) / harga
        komponen = {"kecocokan": 100 * (tipe + masalah) / 2, "ulasan": 100 * ulasan, "harga": 100 * skor_harga}
        return {**komponen, "total": round(sum(BOBOT_PEMENANG[x] * v for x, v in komponen.items())),
                "harga_rp": harga, "n_ulasan": n, "sentimen": None if _kosong(row["skor_sentimen"]) or not n else s,
                "teks_cocok": self._kecocokan(row, p)[1]}

    @staticmethod
    def _teks_ulasan(s):
        return f"{s['sentimen'] * 100:.0f}% positif dari {s['n_ulasan']} ulasan" if s["sentimen"] is not None \
            else "belum ada ulasan"

    def _teks_tradeoff(self, a, sa, b, sb):
        """Kenapa a dan b skornya tipis: sebutkan keunggulan masing-masing."""
        def unggul(x, sx, y, sy):
            hasil = []
            if sx["harga_rp"] is not None and sy["harga_rp"] is not None and sx["harga_rp"] < sy["harga_rp"]:
                hasil.append(f"lebih murah ({rupiah(sx['harga_rp'])} vs {rupiah(sy['harga_rp'])})")
            if sx["sentimen"] is not None and sy["sentimen"] is not None and sx["ulasan"] > sy["ulasan"] + 1:
                hasil.append(f"ulasannya lebih positif ({self._teks_ulasan(sx)} vs {self._teks_ulasan(sy)})")
            elif sx["sentimen"] is not None and sy["sentimen"] is None:
                hasil.append(f"sudah punya ulasan nyata ({self._teks_ulasan(sx)})")
            if sx["kecocokan"] > sy["kecocokan"]:
                hasil.append("lebih cocok dengan profil kamu")
            return hasil
        ua, ub = unggul(a, sa, b, sb), unggul(b, sb, a, sa)
        teks = f"Tapi selisihnya tipis dengan **{b}** (skor {sb['total']}/100)."
        if ua:
            teks += f" **{a}** unggul karena {' dan '.join(ua)}"
            teks += f", sedangkan **{b}** {' dan '.join(ub)}." if ub else "."
        elif ub:
            teks += f" **{b}** sebenarnya {' dan '.join(ub)}, tapi total skornya sedikit di bawah."
        return teks

    def _pilih_satu(self, a, k, kandidat=None, catatan=()):
        """"yang bagusan mana?" = top_n 1 implisit: sempitkan ke 1 pemenang dari
        daftar yang SUDAH dibahas (bukan cari ulang), dipilih dari rincian skor,
        bukan otomatis nomor 1."""
        p = k["profil"]
        hilang = []  # nomor yang produknya sudah dinonaktifkan admin
        if kandidat is None:
            nomor = (a.get("rujukan") or {}).get("nomor") or []
            if nomor:
                kandidat = []
                for n in nomor:
                    if 1 <= n <= len(k["tampil"]):
                        self._id_nomor(n, k["tampil"], kandidat, hilang)
                catatan = tuple(catatan) + tuple(hilang)
            else:
                kandidat = k["banding"] if (k["fokus"] == "banding" and k["banding"]) else k["tampil"]
        df = self.cbf.bandingkan_produk(kandidat)
        if df.empty and hilang:  # semua nomor yang disebut sudah tidak tersedia
            return self._respons(k, "klarifikasi", "\n\n".join(catatan))
        if df.empty:
            return self._respons(k, "klarifikasi", "Belum ada daftar produk yang bisa aku pilihkan. Minta "
                                                  "rekomendasi dulu ya, misalnya \"rekomendasiin sunscreen dong\".")
        label = [self._label_banding(pid, k) for pid in df["id"]]
        harga = [None if _kosong(h) else float(h) for h in df["harga"]]
        skor = [self._skor_pemenang(row, p, harga) for _, row in df.iterrows()]
        urut = sorted(range(len(skor)), key=lambda i: (-skor[i]["total"], i))
        j, s = urut[0], skor[urut[0]]

        if len(skor) == 1:
            teks = [f"Cuma ada 1 produk di daftar tadi, jadi pilihannya **{label[j]}** (skor {s['total']}/100)."]
        else:
            teks = [f"Kalau harus pilih satu dari {len(skor)} produk ini, aku pilih **{label[j]}** "
                    f"(skor {s['total']}/100, paling tinggi)."]
        harga_teks = f"harganya {rupiah(s['harga_rp'])}" if s["harga_rp"] is not None else "harga tidak ada di data"
        ulasan_teks = f"ulasannya {self._teks_ulasan(s)}" if s["sentimen"] is not None else "belum ada ulasan"
        teks.append(f"Alasannya: {s['teks_cocok']}; {ulasan_teks}; {harga_teks}.")
        if len(skor) > 1:
            r = urut[1]
            if s["total"] - skor[r]["total"] < SELISIH_TIPIS:
                teks.append(self._teks_tradeoff(label[j], s, label[r], skor[r]))
        teks.append("_Cara hitung skor: kecocokan profil 40% + kualitas ulasan 40% + harga 20% (harga dibandingkan "
                    "dengan yang termurah; produk tanpa ulasan dihitung setara rata-rata katalog)._")

        def baris(nama, kunci, isi):
            nilai = [s_[kunci] for s_ in skor]
            juara = nilai.index(max(nilai)) if nilai.count(max(nilai)) == 1 else None
            return {"atribut": nama, "nilai": [isi(s_) for s_ in skor], "terbaik": juara}
        tabel = {"produk": label, "baris": [
            baris("Kecocokan profil (40%)", "kecocokan", lambda x: f"{x['kecocokan']:.0f}/100 · {x['teks_cocok']}"),
            baris("Kualitas ulasan (40%)", "ulasan", lambda x: f"{x['ulasan']:.0f}/100 · {self._teks_ulasan(x)}"),
            baris("Harga (20%)", "harga", lambda x: f"{x['harga']:.0f}/100 · "
                                                    + (rupiah(x["harga_rp"]) if x["harga_rp"] is not None else "tidak ada data")),
            {"atribut": "Skor akhir", "nilai": [f"{x['total']}/100" for x in skor], "terbaik": j},
        ]}
        produk, _ = self._susun_produk(self.cbf.ambil_produk([df.at[j, "id"]]), k, None)
        return self._respons(k, "pilih_satu", "\n\n".join(list(catatan) + teks), produk, perbandingan=tabel)

    # ---------- penyusun respons ----------

    @staticmethod
    def _alasan_otomatis(row, p):
        """Alasan dari data tag produk vs profil user -- dipakai kalau LLM
        tidak tersedia. Jujur soal data yang kosong."""
        bagian = []
        tipe_tag = _tag(row["tipe_kulit_cocok"])
        if not tipe_tag:
            bagian.append("belum ada data pasti soal kecocokan tipe kulitnya")
        elif p["tipe_kulit"] in tipe_tag:
            bagian.append(f"ditandai cocok untuk kulit {p['tipe_kulit']}")
        masalah_tag = _tag(row["masalah_kulit_cocok"])
        irisan = [nlu.LABEL_MASALAH[m] for m in p["masalah_kulit"] if m in masalah_tag]
        if irisan:
            bagian.append(f"membantu masalah {', '.join(irisan)}")
        elif not masalah_tag:
            bagian.append("belum ada data soal masalah kulit yang ditangani")
        if not _kosong(row["harga"]) and p["budget_max"]:
            masuk = row["harga"] <= p["budget_max"]
            bagian.append(f"harganya {rupiah(row['harga'])}, {'masih masuk budget' if masuk else 'di atas budget kamu'}")
        if not _kosong(row["skor_sentimen"]) and row["jml_ulasan"]:
            bagian.append(f"{row['skor_sentimen'] * 100:.0f}% ulasan positif dari {int(row['jml_ulasan'])} ulasan")
        else:
            bagian.append("belum ada ulasan")
        kalimat = "; ".join(bagian)
        return kalimat[0].upper() + kalimat[1:] + "."

    @staticmethod
    def _teks_profil(p):
        masalah = ", ".join(nlu.LABEL_MASALAH[m] for m in p["masalah_kulit"])
        teks = f"kulit {p['tipe_kulit']}" + (f" dengan masalah {masalah}" if masalah else "")
        return teks + f", budget {teks_budget(p)}"

    def _penjelasan_otomatis(self, n, p, kategori=(), lain=False):
        jenis = " & ".join(nlu.LABEL_KATEGORI[x] for x in kategori) if kategori else "rekomendasi"
        if lain:
            jenis += " lain (yang belum aku tampilkan sebelumnya)"
        return f"Ini {n} {jenis} untuk {self._teks_profil(p)}. Alasan tiap produk ada di kartunya masing-masing."

    @staticmethod
    def _produk(nomor, row, alasan):
        catatan = []
        if not _tag(row["tipe_kulit_cocok"]):
            catatan.append("Belum ada data pasti soal kecocokan tipe kulit untuk produk ini.")
        return {
            "nomor": nomor,
            "id": row["id"],
            "produk": row["nama_produk"],
            "brand": None if _kosong(row["brand"]) else row["brand"],
            "kategori": None if _kosong(row["kategori"]) else row["kategori"],
            "kategori_label": None if _kosong(row["kategori"]) else nlu.LABEL_KATEGORI.get(row["kategori"]),
            "harga": None if _kosong(row["harga"]) else float(row["harga"]),
            "harga_tidak_wajar": bool(row.get("harga_outlier", False)),
            "rating": None if _kosong(row["rating"]) else float(row["rating"]),
            "jml_ulasan": 0 if _kosong(row["jml_ulasan"]) else int(row["jml_ulasan"]),
            "skor_sentimen": None if _kosong(row["skor_sentimen"]) else float(row["skor_sentimen"]),
            "alasan": alasan,
            "catatan": catatan,
            "di_luar_budget": False,
        }

    @staticmethod
    def _respons(k, tipe, teks, produk=None, grup=None, perbandingan=None):
        """grup: [{judul, produk}] kalau hasilnya dipisah per kategori (produk
        tetap juga ada utuh di 'recommendation', nomornya urut lintas grup).
        perbandingan: {produk: [label], baris: [{atribut, nilai, terbaik}]}."""
        return {"tipe": tipe, "explanation": teks, "recommendation": produk or [], "grup": grup,
                "perbandingan": perbandingan, "konteks": copy.deepcopy(k)}
