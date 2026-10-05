"""
nlu.py -- baca maksud & parameter dari pesan chat user (bahasa natural).

Sengaja rule-based, BUKAN LLM:
  - deterministik -> pengujian skenario bisa diulang persis sama,
  - cepat dan tidak memakai kuota Groq,
  - tetap jalan waktu API LLM lagi down.
Toleran typo lewat jarak edit: 1 huruf salah untuk kata 5-8 huruf, 2 huruf
untuk kata >= 9 huruf ("berminyk" -> berminyak, "kombinsi" -> kombinasi).
"""
import re

# ungkapan sehari-hari ("kayak gorengan", "ketarik", "kulit kendur", "bekas item") ditambahkan
# 1 Okt 2026 setelah uji manual -- ungkapan yang tidak terdaftar ditangani LLM (lihat perlu_llm)
TIPE_KULIT = {
    "berminyak": ("berminyak", "minyakan", "oily", "minyak", "mengkilap", "mengkilat", "kayak gorengan",
                  "seperti gorengan", "kaya gorengan"),
    "kering": ("kering", "dry", "ketarik", "bersisik", "mengelupas", "pecah pecah", "pecah-pecah"),
    "kombinasi": ("kombinasi", "campuran", "combination", "combo", "kombi"),
    "sensitif": ("sensitif", "sensitive", "sensi"),
    "normal": ("normal",),
}
MASALAH_KULIT = {
    "hiperpigmentasi": ("hiperpigmentasi", "hyperpigmentation", "pigmentasi", "flek hitam", "flek",
                        "noda hitam", "bekas jerawat", "dark spot", "dark spots", "bintik hitam", "bekas item",
                        "bekas hitam", "noda item", "bintik item", "flek item", "melasma"),
    "jerawat": ("jerawat", "jerawatan", "berjerawat", "acne", "komedo", "bruntusan", "pimple", "pimples",
                "breakout", "breakouts", "blackhead", "blackheads", "whitehead", "whiteheads"),
    "kusam": ("kusam", "dull", "glowing", "cerah", "mencerahkan", "brightening", "kusem", "butek"),
    "penuaan": ("penuaan", "keriput", "kerutan", "garis halus", "anti aging", "anti-aging", "antiaging",
                "aging", "wrinkle", "wrinkles", "fine lines", "kulit tua", "terlihat tua", "keliatan tua",
                "kelihatan tua", "cepat tua", "menua", "kendur", "kendor", "kurang kencang", "tidak kencang",
                "kerut", "sagging"),
    "kemerahan_iritasi": ("kemerahan", "iritasi", "redness", "irritation", "irritated", "gatal", "perih", "ruam",
                          "merah merah", "merah-merah", "kulit merah", "muka merah", "wajah merah"),
    "dehidrasi": ("dehidrasi", "dehydrated", "dehydration", "kurang lembab", "kurang lembap"),
}
LABEL_MASALAH = {"jerawat": "jerawat", "kusam": "kusam", "hiperpigmentasi": "hiperpigmentasi",
                 "penuaan": "penuaan", "kemerahan_iritasi": "kemerahan & iritasi", "dehidrasi": "dehidrasi"}
KATEGORI = {
    "sunscreen": ("sunscreen", "sunblock", "tabir surya", "sun screen", "sun block", "spf"),
    "facial_wash": ("facial wash", "facewash", "face wash", "facial foam", "sabun muka", "sabun cuci muka",
                    "sabun wajah", "cuci muka", "pembersih wajah", "pembersih muka", "cleanser", "facial_wash",
                    "foam", "micellar water", "micelar water", "micellar", "micelar"),
    "moisturizer": ("moisturizer", "moisturiser", "pelembab", "pelembap", "moisturizing", "krim", "cream"),
    "eksfoliator": ("eksfoliator", "exfoliator", "eksfoliasi", "exfoliant", "exfoliating", "peeling", "scrub"),
    "serum": ("serum", "ampoule", "ampul"),
    "toner": ("toner",),
    "masker": ("masker", "sheet mask", "clay mask", "mask"),
    "acne_patch": ("acne patch", "pimple patch", "patch jerawat", "stiker jerawat", "plester jerawat",
                   "acne_patch", "patch"),
    "essence": ("essence",),
    "mist": ("face mist", "facial mist", "setting spray", "mist"),
    # obat totol jerawat (spot gel) -- kategori dari review manual user (26 Sep 2026)
    "acne_gel": ("acne gel", "acne spot gel", "spot gel", "gel jerawat", "gel totol", "obat totol", "totol jerawat",
                 "sealing gel", "acne_gel"),
}
LABEL_KATEGORI = {"sunscreen": "sunscreen", "facial_wash": "facial wash", "moisturizer": "moisturizer",
                  "eksfoliator": "eksfoliator", "serum": "serum", "toner": "toner", "masker": "masker",
                  "acne_patch": "acne patch", "essence": "essence", "mist": "face mist", "acne_gel": "acne gel"}
# sinonim "lemah": dipakai hanya kalau tidak ada sebutan kategori yang lebih jelas
# di pesan yang sama ("sunscreen cream" -> sunscreen saja, bukan + moisturizer)
KATEGORI_LEMAH = {"cream", "krim", "foam", "patch", "spf", "mask"}

NEGASI = {"bukan", "tidak", "nggak", "ngga", "gak", "ga", "enggak", "engga", "not", "non", "no",
          "tanpa", "jangan"}
STOP = {
    "yang", "yg", "dan", "atau", "dengan", "sama", "buat", "untuk", "utk", "di", "ke", "dari", "aku", "saya",
    "gue", "gw", "kamu", "ini", "itu", "ada", "apa", "aja", "saja", "dong", "deh", "ya", "nih", "sih", "kok",
    "juga", "lagi", "mau", "kasih", "rekomendasi", "rekomendasiin", "produk", "skincare", "kulit", "kulitku",
    "kulitnya", "wajah", "wajahku", "muka", "masalah", "masalahnya", "tipe", "jenis", "budget", "budgetnya",
    "harga", "harganya", "rp", "rb", "ribu", "jt", "juta", "tapi", "kalau", "kalo", "gimana", "cocok", "eh",
    "deng", "udah", "sudah", "pakai", "pake", "nya", "banget", "agak", "tuh", "ternyata", "sebenernya",
    "sebenarnya", "cenderung", "termasuk", "kayaknya", "sepertinya", "mungkin", "lebih", "skin", "my", "is",
    "tidak", "bukan", "gak", "ga", "nggak", "ngga", "naikin", "turunin", "jadi", "sekarang",
}
# kata umum yang boleh muncul di "carikan X aja" tanpa dianggap nama kategori
# yang tidak dikenal (lihat kategori_tidak_dikenal di analisis())
_KATA_UMUM = STOP | {
    "carikan", "cariin", "cari", "pengen", "minta", "rekomendasikan", "rekom", "bagus", "murah", "mahal",
    "terbaik", "best", "aman", "ori", "original", "lokal", "korea", "viral", "terlaris", "populer", "baru",
    "lain", "lainnya", "dulu", "semua", "semuanya", "beberapa", "sedikit", "dikit", "banyak", "satu", "dua",
    "tiga", "empat", "lima", "rekomendasinya", "produknya", "skincarenya", "yang", "please", "tolong", "coba",
}

# kata umum yang kebetulan hanya berbeda 1 huruf dari kosakata skincare -- jangan
# pernah dianggap typo ("keringat" bukan "kering", "serem" bukan "serum")
_JANGAN_FUZZY = {"formal", "keringat", "kerang", "keren", "sering", "masih", "harus", "halus", "kasar",
                 "kusut", "teman", "tanya", "sampai", "cerita", "ceria", "normalnya", "minyaknya", "gatel",
                 "serem", "tonen", "sensor", "tomat", "masak", "maksud", "patah", "pasti", "ampuh",
                 "berisik", "keruh", "merah", "marah"}

_KAMUS = [("tipe", TIPE_KULIT), ("masalah", MASALAH_KULIT), ("kategori", KATEGORI)]
_FRASA = sorted(((sin, jenis, kunci) for jenis, kamus in _KAMUS for kunci, daftar in kamus.items()
                 for sin in daftar if " " in sin or "-" in sin), key=lambda x: -len(x[0]))
_KATA = {sin: (jenis, kunci) for jenis, kamus in _KAMUS for kunci, daftar in kamus.items()
         for sin in daftar if " " not in sin and "-" not in sin}


def normalisasi(teks):
    teks = (teks or "").lower().replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", teks).strip()


def _jarak_edit(a, b):
    """Levenshtein + transposisi huruf bersebelahan, cukup buat typo 1-2 huruf."""
    if abs(len(a) - len(b)) > 2:
        return 3
    d = [[max(i, j) if i == 0 or j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _mirip(token, kata):
    if len(token) < 5 or len(kata) < 5:
        return False
    return _jarak_edit(token, kata) <= (1 if max(len(token), len(kata)) < 9 else 2)


def _token_dasar(tok):
    for akhiran in ("nya", "ku", "mu"):
        if tok.endswith(akhiran) and tok[:-len(akhiran)] in _KATA:
            return tok[:-len(akhiran)]
    return tok


def _cari_sebutan(teks):
    """Semua sebutan tipe kulit / masalah kulit / kategori di teks, urut
    posisi: list of dict {jenis, kunci, kata, awal, dinegasi}. Frasa multi-kata
    diproses lebih dulu lalu dihapus dari teks, supaya katanya tidak terhitung dua kali
    ("bekas jerawat" -> hiperpigmentasi saja, bukan + jerawat)."""
    sisa = list(teks)
    hasil = []
    for frasa, jenis, kunci in _FRASA:
        for m in re.finditer(r"(?<![a-z])" + re.escape(frasa) + r"(?![a-z])", "".join(sisa)):
            hasil.append({"jenis": jenis, "kunci": kunci, "kata": frasa, "awal": m.start()})
            sisa[m.start():m.end()] = " " * (m.end() - m.start())
    for m in re.finditer(r"[a-z_]+", "".join(sisa)):
        tok = _token_dasar(m.group())
        if tok in _KATA:
            cocok = tok
        elif tok in STOP or tok in _JANGAN_FUZZY:
            continue
        else:
            kandidat = sorted((_jarak_edit(tok, k), k) for k in _KATA if _mirip(tok, k))
            if not kandidat:
                continue
            cocok = kandidat[0][1]
        jenis, kunci = _KATA[cocok]
        hasil.append({"jenis": jenis, "kunci": kunci, "kata": cocok, "awal": m.start()})
    for h in hasil:
        # "bukan kering" / "ga bikin berminyak" -> sebutan ini diabaikan
        sebelum = re.findall(r"[a-z]+", teks[:h["awal"]])[-2:]
        h["dinegasi"] = any(t in NEGASI for t in sebelum)
    return sorted(hasil, key=lambda h: h["awal"])


# ---------- budget ----------

_SATUAN = r"(rb|ribu|k|jt|juta)"
_ANGKA = r"(\d+(?:[.,]\d+)*)"
_POLA_RENTANG = re.compile(
    rf"(?:rp\.?\s*)?{_ANGKA}\s*{_SATUAN}?\s*(?:-|sampai|sampe|s/d|hingga|to)\s*(?:rp\.?\s*)?{_ANGKA}\s*{_SATUAN}?"
    r"(?:\s*-?\s*an)?(?![a-z])")
# "antara 50rb dan 100rb" / "between 50k and 100k" -- "dan"/"and" hanya dianggap
# pemisah rentang kalau diawali antara/between ("2 serum dan 3 toner" bukan harga)
_POLA_RENTANG_ANTARA = re.compile(
    rf"\b(?:antara|between)\s+(?:rp\.?\s*)?{_ANGKA}\s*{_SATUAN}?\s*(?:dan|and|sampai|sampe|to|-)\s*"
    rf"(?:rp\.?\s*)?{_ANGKA}\s*{_SATUAN}?(?![a-z])")
_POLA_HARGA = re.compile(rf"(?<![\w.,])(rp\.?\s*)?{_ANGKA}\s*{_SATUAN}?(?:\s*-\s*an|an)?(?![a-z0-9])")
_POLA_BUKAN_HARGA = re.compile(r"\bspf\s*\d+\+*|\bpa\s*\++|\d+\s*(ml|gr|gram|g|%|persen|pcs)\b")
_CUE_MIN = re.compile(r"\b(di atas|diatas|diats|lebih dari|minimal|min|over|above|mulai dari|lebih mahal dari)\b")
_CUE_MAX_NEGASI = re.compile(r"\b(ga|gak|nggak|ngga|tidak|enggak)\s+lebih\s+dari\b")
_CUE_HARGA = re.compile(r"\b(di bawah|dibawah|dibawh|kurang dari|maksimal|maks|max|under|below|budget\w*|"
                        r"harga\w*|sekitar|kisaran|seharga|ke|jadi)\b")
_POLA_RESET_BUDGET = re.compile(
    r"\b(ga ?ada|gak ada|nggak ada|ngga ada|tidak ada|tanpa|no)\s*(batas|batasan|limit)\b|\bunlimited\b|"
    r"\bno budget\b|\bbudget(nya)?\s*(bebas|terserah|berapa\s*(aja|saja|pun)|ga masalah|gak masalah)\b|"
    r"\b(bebas|terserah)\s*(budget|harga)(nya)?\b|\bberapapun\b")


def _ke_rupiah(angka_str, satuan):
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", angka_str):  # 50.000 / 1.500.000 = pemisah ribuan
        nilai = float(re.sub(r"[.,]", "", angka_str))
    else:
        nilai = float(angka_str.replace(",", "."))
    kali = {"rb": 1e3, "ribu": 1e3, "k": 1e3, "jt": 1e6, "juta": 1e6}.get((satuan or "").lower(), 1)
    return int(round(nilai * kali))


def ekstrak_budget(teks):
    """return (hasil, teks_tanpa_harga). hasil kosong ({}) kalau tidak ada
    sebutan budget; selain itu berisi sebagian dari: budget_max, budget_min,
    reset (= tanpa batas), asumsi_ribu ("budget 50" dianggap 50rb)."""
    teks = _POLA_BUKAN_HARGA.sub(lambda m: " " * len(m.group()), teks)
    if _POLA_RESET_BUDGET.search(teks):
        return {"reset": True}, teks

    hasil = {}
    sisa = list(teks)

    def _hapus(m):
        sisa[m.start():m.end()] = " " * (m.end() - m.start())

    for m in [*_POLA_RENTANG_ANTARA.finditer(teks), *_POLA_RENTANG.finditer(teks)]:
        a, sa, b, sb = m.groups()
        sebelum = " ".join(re.findall(r"[a-z]+", teks[:m.start()])[-3:])
        if sa or sb or "rp" in m.group() or _CUE_HARGA.search(sebelum):
            hasil["budget_max"] = _ke_rupiah(b, sb or sa)  # rentang -> batas atas dipakai
            _hapus(m)
            break

    teks_sisa = "".join(sisa)
    for m in _POLA_HARGA.finditer(teks_sisa):
        rp, angka, satuan = m.groups()
        sebelum = " ".join(re.findall(r"[a-z]+", teks_sisa[:m.start()])[-4:])
        nilai = _ke_rupiah(angka, satuan)
        ada_cue = bool(_CUE_HARGA.search(sebelum) or _CUE_MIN.search(sebelum))
        if not (satuan or rp or nilai >= 1000 or ada_cue):
            continue
        if not satuan and not rp and nilai < 1000:
            nilai *= 1000  # "budget 50" hampir selalu maksudnya 50rb
            hasil["asumsi_ribu"] = True
        if _CUE_MAX_NEGASI.search(sebelum):
            kunci = "budget_max"
        elif _CUE_MIN.search(sebelum):
            kunci = "budget_min"
        else:
            kunci = "budget_max"
        hasil.setdefault(kunci, nilai)
        _hapus(m)
    return hasil, "".join(sisa)


# ---------- jumlah produk ----------

JUMLAH_SEMUA = 15   # "kasih semua yang cocok" -> batas wajar, bukan seluruh katalog
JUMLAH_BANYAK = 10  # "banyakin" -> lebih banyak dari default 3
JUMLAH_SEDIKIT = 2  # "beberapa"/"sedikit" -> sengaja beda dari default 3
JUMLAH_MAKS = 20

ANGKA_KATA = {"satu": 1, "sebuah": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6, "tujuh": 7,
              "delapan": 8, "sembilan": 9, "sepuluh": 10, "sebelas": 11, "one": 1, "two": 2, "three": 3,
              "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_NUM = r"(\d+|" + "|".join(sorted(ANGKA_KATA, key=len, reverse=True)) + r")"
_POLA_JUMLAH_DEPAN = re.compile(
    r"\b(?:kasih|kasi|beri|berikan|kasihkan|rekomendasiin|rekomendasikan|carikan|cariin|tampilkan|tunjukin|"
    r"tunjukkan|sebutin|sebutkan|give me|show me|recommend|top|minta|pilihin|just|only|cuma|hanya)\s+"
    r"(?:aku\s+|saya\s+|me\s+)?"
    + _NUM + r"(?![a-z0-9])")
_SINONIM_KATEGORI = {s: k for k, daftar in KATEGORI.items() for s in daftar}
_POLA_KATA_KATEGORI = "|".join(re.escape(s) for s in sorted(_SINONIM_KATEGORI, key=len, reverse=True))
_POLA_JUMLAH_BELAKANG = re.compile(
    r"(?<![a-z0-9#])" + _NUM + r"\s+(?:aja|saja|doang|produk|item|biji|buah|pilihan|rekomendasi|rekom|"
    r"recommendations?|products?|options?|macam|cukup|dulu|deh|" + _POLA_KATA_KATEGORI + r")(?![a-z])")
_POLA_JUMLAH_KATEGORI = re.compile(r"(?<![a-z0-9#])" + _NUM + r"\s+(" + _POLA_KATA_KATEGORI + r")(?![a-z])")
_POLA_JUMLAH_NEGATIF = re.compile(r"(?<![a-z0-9])-\s*\d+\s*(?:produk|item|aja|saja|biji|buah)\b")
_POLA_NOMOR = re.compile(r"\b(?:nomor|nmr|no\.?|number|num|#|produk ke-?|yang ke-?|ke-)\s*\d+\b")


def ekstrak_jumlah(teks):
    """return (jumlah, flag). flag: None | 'semua' | 'banyak' | 'sedikit' |
    'tidak_valid' (0/negatif) | 'dibatasi' (> JUMLAH_MAKS, dipotong)."""
    teks = _POLA_NOMOR.sub(" ", teks)  # "nomor 2" itu rujukan produk, bukan jumlah
    if _POLA_JUMLAH_NEGATIF.search(teks):
        return None, "tidak_valid"
    for pola in (_POLA_JUMLAH_DEPAN, _POLA_JUMLAH_BELAKANG):
        m = pola.search(teks)
        if m:
            n = int(m.group(1)) if m.group(1).isdigit() else ANGKA_KATA[m.group(1)]
            if n <= 0:
                return None, "tidak_valid"
            if n > JUMLAH_MAKS:
                return JUMLAH_MAKS, "dibatasi"
            return n, None
    if re.search(r"\b(semua|semuanya|all)\b(?! kategori| jenis)", teks):
        return JUMLAH_SEMUA, "semua"
    if re.search(r"\b(banyakin|perbanyak|lebih banyak|yang banyak|banyak aja|kasih banyak|tambahin|more)\b", teks):
        return JUMLAH_BANYAK, "banyak"
    if re.search(r"\b(beberapa|several|a few)\b|\b(sedikit|dikit)\s+(aja|saja|dulu|produk)\b|"
                 r"\b(kasih|kasi)\s+(sedikit|dikit)\b|\ba couple\b", teks):
        return JUMLAH_SEDIKIT, "sedikit"
    return None, None


def ekstrak_multi(teks):
    """"kasih 2 serum sama 3 toner" -> [("serum", 2), ("toner", 3)]."""
    pasangan = {}
    for m in _POLA_JUMLAH_KATEGORI.finditer(teks):
        n = int(m.group(1)) if m.group(1).isdigit() else ANGKA_KATA[m.group(1)]
        pasangan.setdefault(_SINONIM_KATEGORI[m.group(2)], min(max(n, 1), JUMLAH_MAKS))
    return list(pasangan.items())


# ---------- "yang bagusan mana?" -> pilih 1 pemenang ----------

# frasa perbandingan/superlatif yang secara implisit minta SATU pemenang
# (setara top_n=1), padahal tidak ada angka sama sekali
_POLA_PILIH_SATU = re.compile(
    r"\b(bagusan|bagusnya|lebih bagus|paling bagus|paling (oke|ok|mantap|worth|recommended|rekomen|top)|terbaik|"
    r"pilih(in|kan)? (satu|1)|(satu|1) (aja|saja) yang|finalnya|mending(an)?|better|worth (dibeli|beli|it)|"
    r"the best|juara(nya)?|pemenang(nya)?|which one|yang paling cocok)\b")
_POLA_NOMOR_RUJUK = re.compile(r"(?:\b(?:nomor|nmr|no\.?|number|num)|#)\s*(\d+)\b")


# ---------- perbandingan produk ----------

_POLA_BANDING = re.compile(r"\b(bandingkan|bandingin|banding|dibandingkan|perbandingan|bandingkannya|compare|"
                           r"comparison|versus|vs)\b")
_POLA_BEDA = re.compile(r"\b(beda|bedanya|perbedaan|perbedaannya|difference)\b")
_POLA_MANA = re.compile(r"\b(mana|which)\b")
ATRIBUT = [
    ("harga", re.compile(r"\b(murah\w*|mahal\w*|harga\w*|price|cheaper|hemat|how much|cost)\b")),
    ("rating", re.compile(r"\b(rating\w*|bintang\w*|rate)\b")),
    ("sentimen", re.compile(r"\b(review\w*|ulasan\w*|sentimen\w*|testimoni\w*|disukai)\b")),
    ("kandungan", re.compile(r"\b(kandungan\w*|bahan\w*|ingredients?|komposisi\w*)\b")),
    ("kecocokan", re.compile(r"\b(cocok\w*|sesuai)\b")),
]
URUTAN_KATA = {"pertama": 1, "kedua": 2, "ketiga": 3, "keempat": 4, "kelima": 5, "terakhir": -1,
               "first": 1, "second": 2, "third": 3, "last": -1}
_PEMISAH_BANDING = re.compile(r"\s*(?:,|&|\bdengan\b|\bdgn\b|\bsama\b|\bvs\.?|\bversus\b|\bdan\b|\band\b|\bwith\b"
                              r"|\batau\b)\s*")
# partikel percakapan + variasi ejaan/huruf berulang (dong/donk/dongg/dunk,
# deh/dehh, sih/sich, ya/yaa/yah, aja/ajah, ...) -- WAJIB dibuang dari potongan
# nama produk SEBELUM dicari, jangan diharapkan fuzzy-match yang menanganinya
# ("donk wardah" gagal ketemu, "wardah" ketemu)
_PARTIKEL = re.compile(
    r"\b(?:d[ou]+n+[gk]+|de+h+|si+c?h+|ni+h+|ko+k+|y[ae]+h*|yak|a+ja+h*|sa+ja+|ka+n+|lo+h+|lho+|la+h+|tu+h+|"
    r"to+h+|na+h+|du+lu+|plea+se|pl[iez]+s?|plz|tolong|coba|gan|kak|min|sis|bro|bang|dah|udah|apa|gimana|antara|"
    r"si|produk|yang|yg|nya|mana|lebih)\b")


def bersihkan_nama(teks):
    """Potongan kalimat user -> kandidat nama produk tanpa partikel percakapan."""
    return re.sub(r"\s+", " ", _PARTIKEL.sub(" ", teks)).strip(" .,!?")


def normalisasi_nama(teks):
    """Normalisasi yang dipakai di KEDUA SISI pencarian nama (query user &
    nama produk di data): huruf kecil, tanda baca jadi spasi, spasi antara
    huruf dan angka dihapus ("skin 1004" & "SKIN1004" -> "skin1004").
    return: list token."""
    teks = re.sub(r"[^a-z0-9]+", " ", str(teks).lower())
    return re.sub(r"(?<=[a-z])\s+(?=\d)", "", teks).split()
_POLA_SEMUA_PRODUK = re.compile(r"^(semua|semuanya|keduanya|ketiganya|keempatnya|kelimanya|all|mereka|"
                                r"(yang|produk)\s+(tadi|itu|ini))$")


# "dari produk A dengan produk B, bagusan yg mana" / "mending A atau B?" -- 2+ nama
# produk + pertanyaan pilihan TANPA kata "bandingkan" = perbandingan juga (skenario
# 4.1b). Beda dengan "yang bagusan mana?" TANPA nama (= pilih 1 dari daftar yang
# sudah tampil, skenario 2.9) -- dua maksud itu sengaja tidak digabung.
_AWALAN_BANDING_IMPLISIT = re.compile(r"^(?:(?:dari|antara|diantara|menurut(?:mu| kamu)?|kira kira|kira2)\s+)+")


def ekstrak_nama_banding_implisit(teks):
    """Potongan yang tampak seperti nama produk (minimal 2 kata) di pesan yang
    berisi pertanyaan pilihan ("bagusan mana", "mending", "mana yang lebih ...").
    return [] kalau bukan pola itu / kurang dari 2 nama. Apakah potongan itu
    benar-benar produk di katalog dipastikan di Percakapan (NLU tidak tahu isi
    katalog)."""
    if not (_POLA_PILIH_SATU.search(teks) or _POLA_MANA.search(teks)):
        return []
    potong = re.sub(r"\b(mana|which)\b|\?", " | ", _POLA_PILIH_SATU.sub(" | ", teks))
    nama = []
    for bagian in potong.split("|"):
        for seg in _PEMISAH_BANDING.split(bagian):
            seg = _AWALAN_BANDING_IMPLISIT.sub("", bersihkan_nama(seg)).strip()
            if len(seg.split()) >= 2:
                nama.append(seg)
    return nama if len(nama) >= 2 else []


def ekstrak_rujukan_banding(teks):
    """"bandingkan nomor 1 sama nomor 3" / "bandingkan 1, 2, sama 3" /
    "bandingkan wardah x dengan azarine y" -> {nomor: [..], nama: [..],
    semua: bool}. nomor -1 = yang terakhir di daftar."""
    m = _POLA_BANDING.search(teks) or _POLA_BEDA.search(teks)
    ekor = teks[m.end():] if m else teks
    ekor = re.split(r"\?|\bmana\b|\bwhich\b", ekor)[0]  # buang pertanyaan atribut di belakang
    hasil = {"nomor": [], "nama": [], "semua": False}
    for seg in _PEMISAH_BANDING.split(ekor):
        seg = bersihkan_nama(seg)
        if not seg:
            continue
        if _POLA_SEMUA_PRODUK.match(seg):
            hasil["semua"] = True
            continue
        angka = re.fullmatch(r"(?:nomor|nmr|no\.?|number|num|#|yang)?\s*(?:ke-?\s*)?(\d+)", seg)
        urutan = next((n for kata, n in URUTAN_KATA.items() if re.fullmatch(rf"(yang\s+)?{kata}", seg)), None)
        if angka:
            hasil["nomor"].append(int(angka.group(1)))
        elif urutan:
            hasil["nomor"].append(urutan)
        elif re.fullmatch(r"(yang\s+)?(ini|itu|tadi)", seg):
            hasil["semua"] = True
        else:
            hasil["nama"].append(seg)
    return hasil


# ---------- percakapan lanjutan: alasan, ulasan, urutkan, alternatif, lebih murah ----------

_POLA_ALASAN = re.compile(r"\b(kenapa|mengapa|alasan|alasannya|why)\b")
_POLA_RUJUK_PRODUK = re.compile(r"\b(produk\w*|ini|itu|tersebut|nomor|no|#|direkomendasi\w*|rekomendasi\w*|dipilih|"
                                r"cocok|pertama|kedua|ketiga|terakhir|products?|this|that|these|number|recommended|"
                                r"first|second|third|last)\b|#\d")
_POLA_ULASAN = re.compile(r"\b(review\w*|ulasan\w*|testimoni\w*|testi|kata orang|pendapat orang|"
                          r"pengalaman (orang|pakai)|keluhan\w*|komplain\w*)\b")
_POLA_MINTA_BARU = re.compile(r"\b(carikan|cariin|cari|rekomendasiin|rekomendasikan|kasih|mau|pengen|butuh)\b")
_POLA_ALTERNATIF = re.compile(r"\b(yang lain|yg lain|lainnya|selain (ini|itu|yang tadi|yg tadi|tadi)|produk lain|"
                              r"pilihan lain|opsi lain|rekomendasi lain|ada lagi (ga|gak|nggak|ngga|nggak sih)|"
                              r"yang beda|others?|another( one)?|something else|different ones?)\b")
_POLA_LEBIH_MURAH = re.compile(r"\b(lebih murah|yang murah|yang murahan|murahan|lebih hemat|lebih terjangkau|cheaper)\b")
_POLA_URUT = re.compile(r"\b(urut\w*|sort\w*|susun\w*)\b")
_POLA_URUT_POSISI = re.compile(r"\b(dulu|duluan|paling atas|di atas|first)\b")
KRITERIA_URUT = [
    ("harga_asc", re.compile(r"\b(termurah|paling murah|murah ke mahal|harga terendah|dari (yang )?murah|cheapest|"
                             r"lowest price|low to high)\b")),
    ("harga_desc", re.compile(r"\b(termahal|paling mahal|mahal ke murah|harga tertinggi|dari (yang )?mahal|"
                              r"most expensive|highest price|high to low)\b")),
    ("ulasan", re.compile(r"\b(ulasan\w* terbanyak|paling banyak (diulas|ulasan\w*|review\w*)|terlaris|paling laris|"
                          r"terpopuler|populer|most review\w*|most popular)\b")),
    ("sentimen", re.compile(r"\b(review\w*|ulasan\w*) (paling )?(positif|bagus|terbaik)\b|\bsentimen\w*\b")),
    ("rating", re.compile(r"\b(rating\w*|bintang\w*)\b")),
]
_URUTAN_RUJUK = re.compile(r"\b(?:yang |produk )?(pertama|kedua|ketiga|keempat|kelima|terakhir)\b")
_KATA_BUKAN_NAMA = {
    "kenapa", "mengapa", "alasan", "alasannya", "why", "direkomendasiin", "direkomendasikan", "direkomendasi",
    "dipilih", "cocok", "buat", "untuk", "aku", "saya", "kamu", "review", "reviewnya", "reviews", "ulasan",
    "ulasannya", "testimoni", "testi", "kata", "orang", "pendapat", "pengalaman", "pakai", "bagus", "jelek",
    "buruk", "positif", "negatif", "ada", "soal", "tentang", "ini", "itu", "tersebut", "tadi", "ga", "gak",
    "nggak", "ngga", "gimana", "bisa", "produknya", "kalau", "kalo", "menurut", "lihat", "liat", "dong", "deh",
    "sih", "ya", "nih", "apa", "yang", "nya", "keluhan", "komplain", "banget", "yg", "the", "of", "about",
    # pertanyaan info produk (harga/kandungan/"bagus ga")
    "harga", "harganya", "berapa", "brp", "info", "infonya", "informasi", "detail", "detailnya", "detil",
    "spesifikasi", "spek", "kandungan", "kandungannya", "bahan", "bahannya", "aktif", "aktifnya", "komposisi",
    "komposisinya", "ingredient", "ingredients", "oke", "ok", "worth", "recommended", "rekomen", "ampuh", "aman",
    "kah", "enggak", "tidak", "tau", "tahu",
    # bahasa Inggris
    "why", "this", "that", "these", "those", "product", "products", "one", "ones", "number", "for", "is", "are",
    "what", "how", "much", "a", "an", "it", "any", "good", "bad", "me", "show", "tell", "does", "do", "have",
    "has", "price", "cost", "reviews", "complaints", "people", "say", "said", "think", "ingredients", "please",
}


def ekstrak_rujukan_produk(teks):
    """Rujukan produk di pertanyaan lanjutan ("kenapa nomor 2 direkomendasiin",
    "review hada labo gokujyun dong", "ada review soal produk ini ga?") ->
    {nomor: [..], nama: [..], semua: bool}. semua=True kalau tidak menyebut
    nomor/nama sama sekali (= produk yang sedang dibahas)."""
    nomor = [int(n) for n in _POLA_NOMOR_RUJUK.findall(teks)]
    nomor += [URUTAN_KATA[k] for k in _URUTAN_RUJUK.findall(teks)]
    sisa = _URUTAN_RUJUK.sub(" ", _POLA_NOMOR_RUJUK.sub(" ", teks))
    token = [t for t in bersihkan_nama(sisa).split()
             if t not in _KATA_BUKAN_NAMA and t not in STOP and t not in _KATA_UMUM]
    # dianggap menyebut nama kalau ada kata SELAIN kata kategori/angka ("kenapa
    # sunscreen nomor 2" bukan nama), tapi kata kategori & angka tetap ikut di
    # nama yang dicari ("glowy magic serum xyz", "skin 1004")
    khas = [t for t in token if t not in _KATA and not t.isdigit()]
    nama = [" ".join(token)] if khas else []
    return {"nomor": nomor, "nama": nama, "semua": not nomor and not nama}


# ---------- di luar rekomendasi: medis, basa-basi, di luar topik, info produk ----------

# pertanyaan medis yang TIDAK boleh dijawab chatbot -> arahkan ke dokter.
# (jenis, pola): jenis dipakai untuk menyebut kenapa harus ke dokter
MEDIS_KERAS = [
    ("obat resep", re.compile(r"\b(resep dokter|obat resep|diresepkan|diresepin|obat dokter|antibiotik\w*|"
                              r"antibiotic\w*|prescription)\b")),
    ("obat minum & dosis", re.compile(r"\b(dosis\w*|takaran\w*|obat minum|minum obat|diminum|tablet|kapsul|"
                                      r"obat oral|dosage)\b|\bminum\b.*\bobat\b|\bobat\b.*\bminum\b")),
    ("konsentrasi bahan aktif", re.compile(r"\bberapa\s*(persen|%)|\b(kadar|konsentrasi)\w*\b|"
                                           r"\bwhat percent\w*|\bhow many percent\b")),
    ("obat keras", re.compile(r"\b(tretinoin|isotretinoin|accutane|roaccutane|clindamycin|klindamisin|doxycycline|"
                              r"doksisiklin|minocycline|hidrokuinon|hydroquinone|kortikosteroid|steroid|"
                              r"hydrocortisone|hidrokortison|spironolacton\w*)\b")),
    ("kehamilan", re.compile(r"\b(hamil|kehamilan|menyusui|busui|bumil|pregnan\w*|breastfeed\w*)\b")),
    ("kondisi kulit yang perlu diperiksa", re.compile(
        r"\b(jerawat batu|kistik|cystic|bernanah|nanah|meradang parah|bengkak|melepuh|infeksi|eksim|eczema|"
        r"psoriasis|dermatitis|rosacea|biduran|reaksi alergi|alergi parah|diagnos\w*|penyakit kulit)\b")),
]
# nyerempet medis tapi masih wajar dijawab dengan produk skincare umum -> produk
# tetap diberikan, plus pengingat bahwa ini bukan obat / pengganti dokter
_POLA_MEDIS_LUNAK = re.compile(r"\b(obat|salep|sembuh\w*|menyembuhkan|mengobati|pengobatan|terapi|dokter)\b")

_POLA_SAPAAN = re.compile(r"^(hai+|hay|halo+|hallo+|helo+|hello+|hi+|hei+|hey+|pagi|siang|sore|malam|selamat "
                          r"(pagi|siang|sore|malam)|assalamu\w* ?(alaikum)?|permisi|apa kabar|good (morning|afternoon|"
                          r"evening))\b")
_POLA_TERIMA_KASIH = re.compile(r"^(makasih\w*|makasi|terima ?kasih|trims|tengkyu|thanks?( you)?|thx|tq|tks|ty|"
                                r"mksh)\b")
_POLA_KONFIRMASI = re.compile(r"^(ok(e|ey|ay)?|sip+|siap|baik(lah)?|noted|oh+ (gitu|begitu|oke)|mantap\w*|"
                              r"good|nice|cool|great|alright|oke deh|ok deh|paham|ngerti|got it)$")
_POLA_BANTUAN = re.compile(r"\b(kamu siapa|siapa kamu|kamu (itu )?apa|kamu bisa apa|bisa (bantu )?apa( aja| saja)?|"
                           r"fitur(nya)? apa|what can you do|who are you)\b|^(help|bantuan|tolong|menu)$")
# isian percakapan yang boleh ada di sekitar sapaan/terima kasih ("halo kak", "makasih ya min")
_ISIAN_BASA_BASI = re.compile(r"\b(kak|kakak|min|mimin|sis|gan|bro|dewy|dew|ya+|yah|yaa+|deh|dong|nih|juga|"
                              r"banyak|banget|bgt|ya ampun|semua|all|so much|a lot|very much|lagi|dulu|udah)\b")

# kata "minta rekomendasi" yang khas skincare -> pasti dalam cakupan
_POLA_MINTA_SKINCARE = re.compile(
    r"\b(rekomendasi\w*|rekomen\w*|rekom|saran\w*|sarankan|suggest\w*|recommend\w*|skincare\w*|skin ?care|"
    r"skinker|produk\w*|products?|cocok\w*|suitable|pakai apa|pake apa|beli apa|bagusnya apa|apa ya)\b")
# kata permintaan umum -- sendirian ("kasih dong") tetap dianggap minta
# rekomendasi, tapi "mau nanya cuaca" bukan
_KATA_MINTA_UMUM = {"cari", "carikan", "cariin", "kasih", "kasi", "mau", "pengen", "pingin", "ingin", "butuh",
                    "perlu", "minta", "lagi", "give", "show", "need", "want", "find", "tolong", "coba", "please",
                    "help", "something", "recommend"}
# kosakata dunia skincare di luar kamus tipe/masalah/kategori (bahan aktif,
# tekstur, klaim produk) -- pesan yang memuat salah satunya dianggap dalam cakupan
KOSAKATA_SKINCARE = {
    "kulit", "kulitku", "kulitnya", "wajah", "wajahku", "muka", "mukaku", "face", "skin", "pori", "pores",
    "dagu", "dahi", "jidat", "pipi", "hidung", "benjolan", "bintik", "lengket", "licin", "porinya",
    "komedo", "bruntus", "flek", "noda", "kerut", "keriput", "kenyal", "halus", "kusam", "cerah", "glowing", "glow",
    "lembab", "lembap", "melembabkan", "kering", "minyak", "berminyak", "jerawat", "jerawatan", "bekas",
    "spf", "uv", "matahari", "sunburn", "niacinamide", "retinol", "retinoid", "aha", "bha", "pha", "salicylic",
    "salisilat", "hyaluronic", "hyaluronat", "ceramide", "ceramid", "centella", "cica", "vitamin", "vit",
    "collagen", "kolagen", "peptide", "peptida", "azelaic", "kojic", "tranexamic", "arbutin", "bakuchiol", "snail",
    "mugwort", "zinc", "sulfur", "benzoyl", "glycolic", "glikolat", "lactic", "mandelic",
    "squalane", "panthenol", "allantoin", "madecassoside", "propolis", "galactomyces", "alkohol", "alcohol",
    "fragrance", "parfum", "pewangi", "paraben", "bpom", "halal", "tekstur", "texture", "ringan", "lightweight",
    "lengket", "sticky", "meresap", "wangi", "aroma", "busa", "gel", "cream", "krim", "lotion", "oil", "minyaknya",
    "routine", "rutinitas", "kandungan", "bahan", "ingredients",
    "ingredient", "harga", "murah", "mahal", "budget", "cheap", "affordable", "brand", "merek", "merk", "lokal",
    "korea", "korean", "jepang", "sensitif", "iritasi", "kemerahan", "perih", "gatal", "breakout", "bopeng",
    "pigmentasi", "melasma", "dehidrasi", "dehydrated", "barrier", "aging", "penuaan", "pemutih", "whitening",
    "brightening", "mencerahkan", "acne", "oily", "dry", "combination", "moist", "moisture", "hydrating",
}
_KOSAKATA_UMUM_BELANJA = {"harga", "murah", "mahal", "budget", "cheap", "affordable", "brand", "merek", "merk",
                          "lokal", "korea", "korean", "jepang", "halal", "bpom", "aroma", "wangi"}
# topik yang jelas bukan skincare -- dipakai kalau pesannya berisi kata minta
# rekomendasi ("rekomendasi film dong") tapi objeknya bukan skincare
_KATA_DI_LUAR_TOPIK = {
    "film", "movie", "lagu", "song", "musik", "music", "buku", "book", "novel", "game", "games", "makanan", "makan",
    "minuman", "restoran", "cafe", "kafe", "resep", "masak", "masakan", "wisata", "liburan", "hotel", "tiket",
    "hp", "handphone", "laptop", "komputer", "baju", "sepatu", "tas", "mobil", "motor", "saham", "crypto",
    "kripto", "investasi", "bola", "sepakbola", "politik", "presiden", "cuaca", "weather", "berita", "news",
    "kuliah", "jurusan", "kampus", "kerja", "pekerjaan", "loker", "pacar", "jodoh", "coding", "program",
    "matematika", "fisika", "kimia", "sejarah", "anime", "drakor", "netflix", "youtube", "tiktok", "shampo",
    "shampoo", "rambut",
}
_KATA_TANYA = {"apa", "apakah", "siapa", "gimana", "bagaimana", "kapan", "dimana", "mana", "berapa", "kenapa",
               "mengapa", "what", "who", "how", "when", "where", "why", "which", "whats", "is", "are", "do", "does"}

# pertanyaan info produk: yang "kuat" boleh merujuk ke daftar yang sedang tampil
# tanpa menyebut produknya ("harganya berapa?", "bahan aktifnya apa?"); yang
# "umum" (info/tentang) wajib menyebut produknya
_POLA_INFO_KUAT = re.compile(
    r"\b(harga\w*|price|cost)\b.*\b(berapa|brp)\b|\b(berapa|brp)\b.*\bharga\w*|\bhow much\b|"
    r"\b(kandungan\w*|bahan\w*|komposisi\w*|ingredients?)\b|"
    r"\b(bagus|oke|ok|worth it|recommended|rekomen|ampuh|aman|good|cocok\w*)\s*(ga|gak|nggak|ngga|enggak|engga|"
    r"tidak|kah|nggak sih|ga sih|gak sih|atau (ga|gak|nggak|tidak))\b|"
    r"\bis (it|this|that|number \d+) (any )?(good|worth|safe|suitable)")
_POLA_INFO_UMUM = re.compile(r"\b(info\w*|informasi|detail\w*|detil\w*|spesifikasi|spek|tentang|tell me about)\b")
_KATA_FUNGSI_EN = {"i", "im", "my", "me", "you", "your", "can", "could", "would", "will", "the", "a", "an", "to",
                   "for", "of", "in", "on", "with", "and", "or", "is", "are", "am", "be", "it", "this", "that",
                   "there", "some", "any", "just", "so", "do", "does", "s"}


def _cakupan(teks, kosakata_merek=frozenset()):
    """Pesan tanpa filter apa pun (tipe/masalah/kategori/budget/jumlah) ->
    None kalau tetap permintaan rekomendasi skincare ("rekomendasiin dong",
    "yang bagus buat mukaku"), 'di_luar_topik' ("siapa presiden indonesia"),
    atau 'tidak_jelas' ("hmm", "asdfgh")."""
    token = re.findall(r"[a-z0-9]+", teks)
    luar = any(t in _KATA_DI_LUAR_TOPIK for t in token)
    # "rekomendasi hp murah": kata harga/asal produk saja tidak cukup untuk
    # dianggap skincare kalau objeknya jelas di luar topik
    kosakata = KOSAKATA_SKINCARE - _KOSAKATA_UMUM_BELANJA if luar else KOSAKATA_SKINCARE
    if any(t in kosakata or t in kosakata_merek or t in _KATA for t in token) \
            or any(len(t) >= 5 and t not in _JANGAN_FUZZY and any(_mirip(t, k) for k in kosakata)
                   for t in token) \
            or any(len(m) >= 4 and re.search(rf"\b{re.escape(m)}\b", teks) for m in kosakata_merek if " " in m):
        return None
    konten = [t for t in token if not t.isdigit() and len(t) > 1 and t not in STOP and t not in _KATA_UMUM
              and t not in _KATA_MINTA_UMUM and t not in _KATA_TANYA and t not in _KATA_FUNGSI_EN
              and not _PARTIKEL.fullmatch(t)]
    if _POLA_MINTA_SKINCARE.search(teks):
        return "di_luar_topik" if luar else None
    if not konten:
        return None if any(t in _KATA_MINTA_UMUM for t in token) else "tidak_jelas"
    if luar or len(konten) >= 2 or any(t in _KATA_TANYA for t in token):
        return "di_luar_topik"
    return "tidak_jelas"


def pecah_klausa(pesan):
    """1 pesan berisi beberapa permintaan berurutan ("rekomendasiin sunscreen,
    terus bandingin nomor 1 sama 2") -> list potongan. Dipisah di kata
    penghubung urutan dan di akhir kalimat (".", "?", "!" yang diikuti huruf),
    BUKAN di "dan"/"sama" (itu dipakai di dalam 1 permintaan: "serum dan toner",
    "bandingkan A sama B")."""
    potong = re.split(r"(?i)\s*(?:[,;]?\s*\b(?:terus|trus|trs|lalu|habis itu|abis itu|setelah itu|kemudian|"
                      r"and then|after that|then)\b|[?!;]+|\.(?=\s+[a-zA-Z]))\s*|\n+", str(pesan))
    return [p.strip(" ,.") for p in potong if re.search(r"[a-zA-Z0-9]", p or "")]


# ---------- analisis utama ----------

_ISIAN_SETELAH_KULIT = STOP | {"aku", "saya", "gue", "sih", "tuh", "itu", "kayak", "tipe", "jenis", "mana", "apa", "gimana"}
_POLA_TAMBAH = re.compile(r"\b(tambah\w*|juga|plus|selain itu)\b")
_POLA_RESET_KATEGORI = re.compile(
    r"\b(semua kategori|kategori apa (aja|saja|pun)|bebas kategori|kategori(nya)? bebas|semua jenis( produk)?|"
    r"jenis apa (aja|saja)|any category|all categories)\b")
_POLA_KATEGORI_DIMINTA = re.compile(
    r"\b(?:carikan|cariin|cari|mau|pengen|kasih|rekomendasiin|minta)\s+(?:yang\s+|yg\s+)?([a-z]+)\s+"
    r"(?:aja|saja|dong|doang|deh)\b|\bkategori\s+([a-z]+)")


# user menyebut nama field-nya sendiri: "tipe kulit saya X" / "masalah kulit saya X".
# Label ini mengalahkan pertanyaan yang sedang ditunggu bot (skenario tipe<->masalah).
_POLA_LABEL_TIPE = re.compile(r"\b(?:tipe|jenis)\s+(?:kulit|wajah|muka)(?:ku|nya|mu)?\b")
_POLA_LABEL_MASALAH = re.compile(
    r"\b(?:masalah|keluhan|problem|permasalahan)\s+(?:kulit|wajah|muka)(?:ku|nya|mu)?\b|\bmasalahku\b")
_POLA_KULIT_X = re.compile(r"\b(?:tipe |jenis )?kulit(?:ku|nya| aku| saya| gue| gw)?\s+((?:[a-z]+\s*){1,4})")
# perumpamaan: "kulit saya SEPERTI orang 70 tahun" -- kata sesudahnya pembanding, bukan nama tipe kulit
_PEMBANDING = r"(?:seperti|kayak|kaya|kek|mirip|bagai|bagaikan|layaknya)"
_POLA_KULIT_BANDING = re.compile(
    rf"\b(?:kulit|wajah|muka)\w*(?:\s+(?:aku|saya|gue|gw|sekarang|udah|sudah|jadi|tuh|tu|ga|gak|nggak|ngga|tidak|"
    rf"bukan|enggak|engga))*\s+{_PEMBANDING}\b")
# "kayak orang 70 tahun" / "seperti nenek-nenek" -> penuaan (umur pembanding minimal 40)
_POLA_BANDING_TUA = re.compile(
    rf"\b{_PEMBANDING}\s+(?:(?:orang|umur|usia|kulit|punya)\s+)?(?:yang\s+)?(?:udah\s+|sudah\s+)?"
    r"(?:(tua|nenek|kakek|lansia|manula|oma|opa)\w*|(\d{2})\s*(?:tahun|thn|th)\b)")
# cerita soal kulit/wajah (termasuk bagian wajah: "di dagu sering muncul benjolan merah")
_POLA_KATA_KULIT = re.compile(r"\b(?:kulit|wajah|muka|pipi|dahi|jidat|dagu|hidung|pori)\w*")
_KATA_KULIT = {"kulit", "kulitku", "kulitnya", "wajah", "wajahku", "wajahnya", "muka", "mukaku", "mukanya",
               "pipi", "pipiku", "dahi", "dahiku", "jidat", "jidatku", "dagu", "daguku", "hidung", "hidungku",
               "pori", "porinya"}
# kata pengisi di jawaban soal kulit yang bukan nilai tipe/masalah ("aku ga tau", "pokoknya ...")
_ISIAN_JAWABAN = {"tau", "tahu", "yakin", "bingung", "ngerti", "paham", "lumayan", "cukup", "sangat", "sekali",
                  "bgt", "kayak", "seperti", "adalah", "ialah", "yaitu", "yakni", "cuma", "hanya", "kan", "lah",
                  "ganti", "ubah", "diganti", "diubah", "pokoknya", "intinya", "maksudnya", "maksud", "kayanya",
                  "masih", "tetap", "tetep", "emang", "memang", "beneran", "bener", "benar"}
# jawaban atas pertanyaan bot "mau ganti tipe kulit atau masalah kulit?"
_ISIAN_PILIH_FIELD = {"yang", "yg", "ganti", "ubah", "mau", "aku", "saya", "kulit", "kulitnya", "kulitku", "aja",
                      "saja", "dong", "deh", "ya", "sih", "itu", "dulu", "tolong", "pengen", "pengin", "kak", "nya",
                      "skin", "type", "the"}


def _kata_asing(potongan, batas=4):
    """Kata di potongan teks (maks. `batas` kata pertama) yang BUKAN kosakata apa pun
    (tipe/masalah/kategori, termasuk typo yang masih mirip) dan bukan kata pengisi --
    calon nilai yang tidak dikenali. Kosakata dicek dulu SEBELUM menentukan field: kata
    yang dikenali tidak pernah dianggap nilai asing, jadi "kusam" tidak mungkin jadi
    tipe kulit tak dikenal dan "berminyak" tidak mungkin jadi masalah kulit tak dikenal."""
    hasil = []
    for t in re.findall(r"[a-z]+", potongan)[:batas]:
        if len(t) < 3 or t in _ISIAN_SETELAH_KULIT or t in _ISIAN_JAWABAN or t in NEGASI or _cari_sebutan(t):
            continue
        hasil.append(t)
    return hasil


def _jawaban_pilih_field(inti):
    """'tipe' / 'yang masalah kulit aja' -> field yang dipilih (atau None)."""
    kata = set(re.findall(r"[a-z]+", inti)) - _ISIAN_PILIH_FIELD
    if kata and kata <= {"tipe", "jenis"}:
        return "tipe_kulit"
    if kata and kata <= {"masalah", "keluhan", "problem"}:
        return "masalah_kulit"
    return None


def analisis(pesan, menunggu=None, ada_hasil=False, ada_banding=False, kosakata_merek=frozenset()):
    """Pesan user -> dict berisi 'intent' + parameter yang terbaca.

    menunggu: pertanyaan profil yang sedang ditunggu jawabannya oleh bot --
        'tipe_kulit' / 'masalah_kulit' (bot tanya ulang nilai yang tidak
        dikenali) atau 'pilih_field' (bot tanya "tipe atau masalah?") --
        supaya jawaban pendek dibaca sesuai pertanyaannya.
    ada_hasil: percakapan ini sudah pernah menampilkan daftar produk --
        menentukan apakah "2 aja deh" berarti potong hasil yang sama
        (intent 'ubah_jumlah') atau permintaan rekomendasi baru.
    ada_banding: percakapan ini sudah pernah menampilkan tabel perbandingan
        (untuk "yang mana yang lebih murah?").
    kosakata_merek: nama brand di data (huruf kecil) -- "carikan wardah aja"
        bukan kategori yang tidak dikenal.
    """
    teks = normalisasi(pesan)
    a = {"intent": "rekomendasi", "teks": teks, "tipe_kulit": None, "tipe_tidak_dikenal": None,
         "masalah_tidak_dikenal": None, "salah_field": [], "pilih_field": None, "pilih_field_gagal": False,
         "perlu_llm": False,
         "masalah_kulit": [], "masalah_tambah": False, "budget": {}, "jumlah": None, "jumlah_flag": None,
         "kategori": [], "kategori_reset": False, "kategori_tidak_dikenal": None, "multi": [],
         "rujukan": None, "atribut": None, "pilih_satu": False, "urut": None, "preferensi_ulasan": None,
         "medis": [], "medis_lunak": bool(_POLA_MEDIS_LUNAK.search(teks)), "banding_implisit": None}
    if not re.search(r"[a-z0-9]", teks):
        a["intent"] = "kosong"
        return a

    # pertanyaan medis dicek paling awal: walau menyebut masalah kulit ("obat
    # jerawat resep dokter"), jangan dijawab dengan rekomendasi seolah pengganti dokter
    a["medis"] = [jenis for jenis, pola in MEDIS_KERAS if pola.search(teks)]
    if a["medis"]:
        a["intent"] = "medis"
        return a
    # basa-basi: hanya bila pesannya MEMANG hanya itu ("halo kak", "makasih ya") --
    # "halo, rekomendasiin sunscreen dong" tetap permintaan rekomendasi
    inti = re.sub(r"\s+", " ", _ISIAN_BASA_BASI.sub(" ", re.sub(r"[^a-z ]", " ", teks))).strip()
    for nama, pola in (("terima_kasih", _POLA_TERIMA_KASIH), ("sapaan", _POLA_SAPAAN)):
        m = pola.match(inti)
        if m and not inti[m.end():].strip():
            a["intent"] = nama
            return a
    if _POLA_KONFIRMASI.fullmatch(inti):
        a["intent"] = "konfirmasi"
        return a
    if _POLA_BANTUAN.search(inti):
        a["intent"] = "bantuan"
        return a
    if menunggu == "pilih_field":
        a["pilih_field"] = _jawaban_pilih_field(inti)
        if a["pilih_field"]:
            a["intent"] = "ubah_profil"
            return a

    # perbandingan dicek duluan: nama produk yang dibandingkan sering memuat kata
    # kategori/tipe kulit ("wardah lightening toner") yang BUKAN permintaan ganti filter
    a["atribut"] = next((nama for nama, pola in ATRIBUT if pola.search(teks)), None)
    # "yang bagusan mana" (tanpa atribut spesifik) -> pilih 1 pemenang; kalau
    # atributnya disebut ("yang ratingnya paling bagus") itu pertanyaan atribut
    a["pilih_satu"] = bool(_POLA_PILIH_SATU.search(teks)) and a["atribut"] in (None, "kecocokan")
    if _POLA_BANDING.search(teks) or (_POLA_BEDA.search(teks) and re.search(r"\b(sama|dengan|dan|vs)\b", teks)):
        a["intent"] = "banding"
        a["rujukan"] = ekstrak_rujukan_banding(teks)
        return a
    # kandidat perbandingan tanpa kata "bandingkan" -- analisis tetap dilanjutkan;
    # Percakapan memakainya hanya kalau nama-namanya memang produk di katalog
    nama_implisit = ekstrak_nama_banding_implisit(teks)
    if nama_implisit:
        a["banding_implisit"] = {"nomor": [], "nama": nama_implisit, "semua": False}
    if (ada_banding or ada_hasil) and a["atribut"] and not a["pilih_satu"] \
            and (_POLA_MANA.search(teks) or _POLA_BEDA.search(teks)):
        a["intent"] = "banding_atribut"
        a["rujukan"] = {"nomor": [], "nama": [], "semua": True}
        return a

    # pertanyaan lanjutan soal produk yang sedang dibahas -- dicek sebelum
    # filter, karena nama produk yang ditanya bisa memuat kata kategori/kulit
    a["urut"] = next((nama for nama, pola in KRITERIA_URUT if pola.search(teks)), None)
    if ada_hasil and (_POLA_URUT.search(teks) or (a["urut"] and _POLA_URUT_POSISI.search(teks))):
        a["intent"] = "urutkan"
        return a
    rujukan = ekstrak_rujukan_produk(teks)
    # tanpa daftar sebelumnya pun "kenapa produk ini direkomendasiin?" tetap
    # pertanyaan alasan (dijawab "belum ada rekomendasi"), bukan minta rekomendasi baru
    merujuk = re.search(r"\b(ini|itu|tersebut|tadi)\b", teks)
    if _POLA_ALASAN.search(teks) and (
            ((ada_hasil or ada_banding or rujukan["nama"]) and (_POLA_RUJUK_PRODUK.search(teks) or rujukan["nama"]))
            or re.search(r"\b(direkomendasi\w*|dipilih)\b", teks)):
        a["intent"], a["rujukan"] = "alasan", rujukan
        return a
    if _POLA_ULASAN.search(teks) and (rujukan["nama"] or (merujuk and not _POLA_MINTA_BARU.search(teks))
                                      or ((ada_hasil or ada_banding) and not _POLA_MINTA_BARU.search(teks))):
        a["intent"], a["rujukan"] = "ulasan", rujukan
        if re.search(r"\b(jelek|buruk|negatif|keluhan|komplain|minus|kurang)\w*", teks):
            a["preferensi_ulasan"] = "Negatif"
        elif re.search(r"\b(bagus|positif|baik|oke|puas)\w*", teks):
            a["preferensi_ulasan"] = "Positif"
        return a
    # info satu/beberapa produk ("harga nomor 2 berapa?", "bahan aktifnya apa?",
    # "wardah lightening face mist bagus ga?") -- bukan minta rekomendasi baru
    if (_POLA_INFO_KUAT.search(teks) or _POLA_INFO_UMUM.search(teks)) and not _POLA_MINTA_BARU.search(teks):
        # kata di dalam nama produk ("wardah LIGHTENING face mist") bukan
        # sebutan masalah kulit user -> dibuang dulu sebelum dicari
        tanpa_nama = teks
        for t in (" ".join(rujukan["nama"])).split():
            tanpa_nama = re.sub(rf"\b{re.escape(t)}\b", " ", tanpa_nama)
        sebut = [s for s in _cari_sebutan(tanpa_nama) if not s["dinegasi"]]
        eksplisit = rujukan["nomor"] or rujukan["nama"] or merujuk
        if eksplisit or ((ada_hasil or ada_banding) and _POLA_INFO_KUAT.search(teks) and
                         not any(s["jenis"] in ("tipe", "masalah") for s in sebut)):
            a["intent"], a["rujukan"] = "info_produk", rujukan
            # "nomor 2 cocok ga buat kulit sensitif?" -> dinilai terhadap kulit
            # sensitif, TANPA mengubah profil
            a["tipe_kulit"] = next((s["kunci"] for s in sebut if s["jenis"] == "tipe"), None)
            a["masalah_kulit"] = list(dict.fromkeys(s["kunci"] for s in sebut if s["jenis"] == "masalah"))
            return a

    a["budget"], teks_tanpa_harga = ekstrak_budget(teks)
    sebutan = [s for s in _cari_sebutan(teks_tanpa_harga) if not s["dinegasi"]]
    tipe = [s["kunci"] for s in sebutan if s["jenis"] == "tipe"]
    a["tipe_kulit"] = tipe[0] if tipe else None
    a["masalah_kulit"] = list(dict.fromkeys(s["kunci"] for s in sebutan if s["jenis"] == "masalah"))
    m_tua = _POLA_BANDING_TUA.search(teks)
    if m_tua and (not m_tua.group(2) or int(m_tua.group(2)) >= 40) and "penuaan" not in a["masalah_kulit"] \
            and not any(t in NEGASI for t in re.findall(r"[a-z]+", teks[:m_tua.start()])[-2:]):
        a["masalah_kulit"].append("penuaan")
    a["masalah_tambah"] = bool(a["masalah_kulit"] and _POLA_TAMBAH.search(teks))

    kategori = [s for s in sebutan if s["jenis"] == "kategori"]
    kuat = [s for s in kategori if s["kata"] not in KATEGORI_LEMAH]
    a["kategori"] = list(dict.fromkeys(s["kunci"] for s in (kuat or kategori)))
    a["kategori_reset"] = bool(_POLA_RESET_KATEGORI.search(teks))
    if not a["kategori"] and not a["kategori_reset"]:
        m = _POLA_KATEGORI_DIMINTA.search(teks_tanpa_harga)
        kata = (m.group(1) or m.group(2)) if m else None
        if kata and len(kata) >= 4 and kata not in _KATA_UMUM and kata not in _KATA and kata not in kosakata_merek \
                and not any(_mirip(kata, k) for k in _KATA):
            a["kategori_tidak_dikenal"] = kata  # jangan diam-diam diabaikan -> bilang tidak ada di data

    a["jumlah"], a["jumlah_flag"] = ekstrak_jumlah(teks_tanpa_harga)
    pasangan = ekstrak_multi(teks_tanpa_harga)
    if len(pasangan) >= 2:
        a["multi"] = pasangan
    elif len(a["kategori"]) >= 2:
        a["multi"] = [(k, a["jumlah"]) for k in a["kategori"]]

    lain = a["masalah_kulit"] or a["budget"] or a["kategori"] or a["kategori_reset"] \
        or a["kategori_tidak_dikenal"] or a["jumlah"] or a["jumlah_flag"]
    _baca_field_profil(a, teks_tanpa_harga, menunggu, lain)

    ada_slot = a["tipe_kulit"] or a["tipe_tidak_dikenal"] or a["masalah_kulit"] or a["masalah_tidak_dikenal"] \
        or a["budget"] or a["kategori"] or a["kategori_reset"] or a["kategori_tidak_dikenal"] or a["multi"]
    if ada_hasil and _POLA_ALTERNATIF.search(teks):
        a["intent"] = "alternatif"  # filter yang disebut di pesan yang sama tetap diterapkan
        a["tipe_tidak_dikenal"] = a["masalah_tidak_dikenal"] = None
    elif ada_hasil and _POLA_LEBIH_MURAH.search(teks) and not a["budget"]:
        a["intent"] = "lebih_murah"
        a["tipe_tidak_dikenal"] = a["masalah_tidak_dikenal"] = None
    elif a["pilih_satu"] and (ada_hasil or ada_banding) and not ada_slot:
        a["intent"] = "pilih_satu"
        a["tipe_tidak_dikenal"] = a["masalah_tidak_dikenal"] = None
        a["rujukan"] = {"nomor": [int(n) for n in _POLA_NOMOR_RUJUK.findall(teks)], "nama": [], "semua": False}
    elif ada_hasil and (a["jumlah"] or a["jumlah_flag"]) and not ada_slot:
        a["intent"] = "ubah_jumlah"
    elif menunggu == "pilih_field" and not ada_slot and not (a["jumlah"] or a["jumlah_flag"]) \
            and not (_POLA_MINTA_SKINCARE.search(teks) or _POLA_MINTA_BARU.search(teks)):
        # jawaban atas "tipe atau masalah?" yang tetap tidak bisa dipahami -- tapi permintaan
        # rekomendasi yang eksplisit ("rekomendasi agar bisa cantik") tetap dilayani, bukan dianggap gagal
        a["intent"], a["pilih_field_gagal"] = "ubah_profil", True
    elif a["intent"] == "rekomendasi" and not ada_slot and not (a["jumlah"] or a["jumlah_flag"]):
        # tanpa filter apa pun: masih minta rekomendasi skincare, atau di luar topik / tidak jelas?
        a["intent"] = _cakupan(teks_tanpa_harga, kosakata_merek) or "rekomendasi"
    return a


def _baca_field_profil(a, teks, menunggu, lain):
    """Tentukan field profil (tipe_kulit / masalah_kulit) untuk nilai yang disebut user.

    1. Kosakata dulu: nilai yang DIKENALI (sudah terisi di a['tipe_kulit'] /
       a['masalah_kulit'] oleh _cari_sebutan) selalu masuk ke field kosakatanya,
       apa pun label atau pertanyaan yang sedang ditunggu. Kalau label/pertanyaan
       menunjuk field lain, dicatat di a['salah_field'] supaya Percakapan memberi
       tahu ("kusam itu masalah kulit, bukan tipe kulit").
    2. Nilai yang TIDAK dikenali: field-nya mengikuti label eksplisit ("masalah kulit
       saya X" -> masalah_kulit), yang mengalahkan pertanyaan yang sedang ditunggu;
       tanpa label mengikuti pertanyaan yang ditunggu (jawaban singkat); tanpa
       keduanya "kulitku xyz" dianggap tipe kulit -- tapi hanya kalau pesannya memang
       sekadar pernyataan soal kulit ("kulitku butuh serum" itu permintaan serum).
    """
    m_tipe, m_masalah = _POLA_LABEL_TIPE.search(teks), _POLA_LABEL_MASALAH.search(teks)
    jawaban_singkat = not (a["budget"] or a["kategori"] or a["kategori_reset"] or a["kategori_tidak_dikenal"]
                           or a["jumlah"] or a["jumlah_flag"])
    if m_tipe and not m_masalah:
        tunjuk = "tipe_kulit"
    elif m_masalah and not m_tipe:
        tunjuk = "masalah_kulit"
    else:
        tunjuk = menunggu if menunggu in ("tipe_kulit", "masalah_kulit") and jawaban_singkat else None
    if tunjuk == "tipe_kulit" and not a["tipe_kulit"] and a["masalah_kulit"]:
        a["salah_field"] = [("masalah_kulit", m) for m in a["masalah_kulit"]]
    elif tunjuk == "masalah_kulit" and not a["masalah_kulit"] and a["tipe_kulit"]:
        a["salah_field"] = [("tipe_kulit", a["tipe_kulit"])]

    if m_tipe and not a["tipe_kulit"]:
        asing = _kata_asing(teks[m_tipe.end():])
        a["tipe_tidak_dikenal"] = asing[0] if asing else None
    if m_masalah and not a["masalah_kulit"]:
        asing = _kata_asing(teks[m_masalah.end():])
        a["masalah_tidak_dikenal"] = asing[0] if asing else None
    banding = _POLA_KULIT_BANDING.search(teks)
    if not (m_tipe or m_masalah or a["tipe_kulit"] or lain) and not banding:
        # (perumpamaan "kulit saya kayak X" tidak pernah dianggap nama tipe kulit X)
        m = _POLA_KULIT_X.search(teks)
        if menunggu in ("tipe_kulit", "masalah_kulit"):
            asing = _kata_asing(m.group(1) if m else teks)  # jawaban singkat atas pertanyaan bot
            if asing:
                a["tipe_tidak_dikenal" if menunggu == "tipe_kulit" else "masalah_tidak_dikenal"] = asing[0]
        elif m and not (_POLA_MINTA_SKINCARE.search(teks) or _POLA_MINTA_BARU.search(teks)):
            # "kulit avelina jelek, rekomendasi dong" -> kata sesudah "kulit" di permintaan bisa nama
            # pemiliknya, bukan tipe kulit; tebakan ini hanya untuk pernyataan soal kulit saja
            asing = _kata_asing(m.group(1))
            if asing:
                a["tipe_tidak_dikenal"] = asing[0]

    # 3. Aturan tidak yakin -> Percakapan boleh minta tafsiran LLM (NLU hybrid): ada nilai yang
    #    tidak dikenali, perumpamaan yang tidak menghasilkan apa pun, atau cerita soal kulit/wajah
    #    tanpa satu pun tipe/masalah yang terbaca ("pori-pori gede, siang dikit udah lengket").
    tanpa_nilai = not (a["tipe_kulit"] or a["masalah_kulit"])
    cerita_kulit = jawaban_singkat and tanpa_nilai and _POLA_KATA_KULIT.search(teks) and any(
        len(t) > 2 and t not in STOP and t not in _KATA_UMUM and t not in _ISIAN_JAWABAN and t not in _KATA_KULIT
        for t in re.findall(r"[a-z]+", teks))
    a["perlu_llm"] = bool(a["tipe_tidak_dikenal"] or a["masalah_tidak_dikenal"] or (banding and tanpa_nilai)
                          or cerita_kulit)
