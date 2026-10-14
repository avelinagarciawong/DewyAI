"""
glosarium.py -- pengetahuan terkurasi tentang bahan aktif skincare untuk menjawab pertanyaan
"niacinamide itu buat apa?" dan menjadi sumber bagi obrolan umum chatbot.

Setiap entri: nama tampilan, alias (huruf kecil, dipakai untuk mendeteksi bahan di pesan dan di
kandungan/nama/deskripsi produk), fungsi, hal yang perlu diperhatikan, dan masalah kulit yang
umumnya dibantu (kunci MASALAH_KULIT_VALID). Isi ditulis umum dan hati-hati -- bukan saran
medis, tanpa angka konsentrasi -- dan sudah dicocokkan dengan sumbernya: "rujukan" berisi (label, tautan)
yang ikut ditampilkan di jawaban chatbot; kutipan lengkapnya ada di data/cek_glosarium.xlsx.
"""
import re

GLOSARIUM = [
    {"kunci": "niacinamide", "nama": "Niacinamide (vitamin B3)",
     "alias": ["niacinamide", "niasinamida", "nicotinamide", "vitamin b3", "vit b3"],
     "fungsi": "Membantu menguatkan lapisan pelindung kulit (skin barrier), mengontrol minyak berlebih, dan membantu "
               "meratakan warna kulit.",
     "perhatian": "Umumnya sangat mudah ditoleransi kulit. Tetap hentikan pemakaian bila muncul iritasi.",
     "masalah": ["jerawat", "kusam", "hiperpigmentasi"],
     "rujukan": [("Marques dkk., Antioxidants 2024", "https://pmc.ncbi.nlm.nih.gov/articles/PMC11047333/")]},
    {"kunci": "salicylic_acid", "nama": "Salicylic acid (BHA)",
     "alias": ["salicylic acid", "salicylic", "asam salisilat", "bha"],
     "fungsi": "Eksfolian yang larut dalam minyak, membantu membersihkan pori, dan sering dipakai untuk komedo serta "
               "jerawat.",
     "perhatian": "Dapat membuat kulit kering atau perih bila dipakai berlebihan; gunakan bertahap dan pakai sunscreen.",
     "masalah": ["jerawat"],
     "rujukan": [("DermNet NZ", "https://dermnetnz.org/topics/salicylic-acid"),
                 ("FDA", "https://www.fda.gov/cosmetics/cosmetic-ingredients/beta-hydroxy-acids")]},
    {"kunci": "aha", "nama": "AHA (glycolic acid, lactic acid)",
     "alias": ["aha", "glycolic acid", "glycolic", "lactic acid", "asam glikolat", "asam laktat", "mandelic acid"],
     "fungsi": "Eksfolian yang membantu mengangkat sel kulit mati sehingga kulit tampak lebih halus dan cerah.",
     "perhatian": "Membuat kulit lebih sensitif terhadap matahari, jadi wajib sunscreen.",
     "masalah": ["kusam", "hiperpigmentasi"],
     "rujukan": [("FDA", "https://www.fda.gov/cosmetics/cosmetic-ingredients/alpha-hydroxy-acids")]},
    {"kunci": "retinol", "nama": "Retinol (turunan vitamin A)",
     "alias": ["retinol", "retinoid", "retinal", "retinyl palmitate"],
     "fungsi": "Umumnya dipakai untuk tanda penuaan seperti garis halus, dan membantu mengatasi jerawat.",
     "perhatian": "Sering menimbulkan kering, kemerahan, atau mengelupas dan membuat kulit lebih sensitif terhadap "
                  "matahari; pakai malam hari, mulai perlahan, dan wajib sunscreen. Hindari saat hamil, dan "
                  "konsultasikan ke dokter bila sedang menyusui.",
     "masalah": ["penuaan", "jerawat"], "rujukan": [("DermNet NZ", "https://dermnetnz.org/topics/topical-retinoids")]},
    {"kunci": "vitamin_c", "nama": "Vitamin C",
     "alias": ["vitamin c", "vit c", "ascorbic acid", "asam askorbat", "ascorbyl", "ethyl ascorbic"],
     "fungsi": "Antioksidan yang umumnya dipakai untuk membantu mencerahkan kulit kusam dan meratakan warna kulit.",
     "perhatian": "Umumnya aman; sesekali bisa terasa perih, kemerahan, atau kering, dan produk yang sudah teroksidasi "
                  "bisa meninggalkan warna kekuningan di kulit.",
     "masalah": ["kusam", "hiperpigmentasi"],
     "rujukan": [("Al-Niaimi & Chiang, JCAD 2017", "https://pmc.ncbi.nlm.nih.gov/articles/PMC5605218/"),
                 ("Telang, Indian Dermatol Online J 2013", "https://pmc.ncbi.nlm.nih.gov/articles/PMC3673383/")]},
    {"kunci": "hyaluronic_acid", "nama": "Hyaluronic acid",
     "alias": ["hyaluronic acid", "hyaluronic", "hyaluron", "asam hialuronat", "sodium hyaluronate"],
     "fungsi": "Pelembap (humektan) yang membantu menarik dan menahan air di kulit sehingga kulit terasa lebih lembap.",
     "perhatian": "Umumnya mudah ditoleransi; tetap lanjutkan dengan pelembap.",
     "masalah": ["dehidrasi"],
     "rujukan": [("Papakonstantinou dkk., 2012", "https://pmc.ncbi.nlm.nih.gov/articles/PMC3583886/")]},
    {"kunci": "ceramide", "nama": "Ceramide",
     "alias": ["ceramide", "ceramides", "seramid"],
     "fungsi": "Lemak alami penyusun lapisan pelindung kulit; membantu menjaga kelembapan dan memperbaiki skin barrier.",
     "perhatian": "Umumnya mudah ditoleransi, termasuk oleh kulit kering dan sensitif.",
     "masalah": ["dehidrasi", "kemerahan_iritasi"],
     "rujukan": [("Ulasan pelembap berceramide, JCAD", "https://pmc.ncbi.nlm.nih.gov/articles/PMC5300724/")]},
    {"kunci": "centella", "nama": "Centella asiatica (cica)",
     "alias": ["centella asiatica", "centella", "cica", "madecassoside", "pegagan"],
     "fungsi": "Ekstrak tanaman yang umumnya dipakai untuk menenangkan kulit dan membantu pemulihannya; bukti "
               "efektivitasnya dalam produk kosmetik masih terbatas.",
     "perhatian": "Efek samping jarang, tetapi bisa terjadi alergi atau rasa terbakar; uji tempel dulu bila kulitmu "
                  "sensitif.",
     "masalah": ["kemerahan_iritasi", "jerawat"],
     "rujukan": [("Bylka dkk., Postepy Dermatol Alergol 2013", "https://pmc.ncbi.nlm.nih.gov/articles/PMC3834700/")]},
    {"kunci": "panthenol", "nama": "Panthenol (pro-vitamin B5)",
     "alias": ["panthenol", "pantenol", "vitamin b5", "vit b5", "provitamin b5", "pro-vitamin b5"],
     "fungsi": "Membantu melembapkan dan menenangkan kulit.",
     "perhatian": "Umumnya mudah ditoleransi.",
     "masalah": ["dehidrasi", "kemerahan_iritasi"],
     "rujukan": [("Proksch dkk., J Dermatolog Treat 2017", "https://pubmed.ncbi.nlm.nih.gov/28503966/")]},
    {"kunci": "azelaic_acid", "nama": "Azelaic acid",
     "alias": ["azelaic acid", "azelaic", "asam azelat"],
     "fungsi": "Umumnya dipakai untuk jerawat, kemerahan, dan noda gelap.",
     "perhatian": "Pada kulit yang sangat sensitif bisa terasa gatal, perih, atau iritasi ringan.",
     "masalah": ["jerawat", "hiperpigmentasi", "kemerahan_iritasi"],
     "rujukan": [("DermNet NZ", "https://dermnetnz.org/topics/azelaic-acid")]},
    {"kunci": "benzoyl_peroxide", "nama": "Benzoyl peroxide",
     "alias": ["benzoyl peroxide", "benzoil peroksida"],
     "fungsi": "Bahan antibakteri yang umum dipakai untuk jerawat meradang.",
     "perhatian": "Dapat membuat kulit kering atau iritasi dan memudarkan warna kain (handuk, sarung bantal); mulai "
                  "perlahan.",
     "masalah": ["jerawat"], "rujukan": [("DermNet NZ", "https://dermnetnz.org/topics/benzoyl-peroxide")]},
    {"kunci": "tea_tree", "nama": "Tea tree oil",
     "alias": ["tea tree oil", "tea tree", "melaleuca"],
     "fungsi": "Minyak esensial yang sering ditambahkan ke produk jerawat sebagai antiseptik, meski bukti "
               "efektivitasnya masih terbatas.",
     "perhatian": "Dapat menimbulkan iritasi atau alergi pada sebagian orang; jangan dipakai murni tanpa diencerkan.",
     "masalah": ["jerawat"],
     "rujukan": [("DermNet NZ", "https://dermnetnz.org/topics/allergic-contact-dermatitis-to-essential-oils")]},
    {"kunci": "zinc", "nama": "Zinc (misalnya zinc PCA)",
     "alias": ["zinc pca", "zinc"],
     "fungsi": "Mineral yang sering dipakai untuk membantu mengontrol minyak dan menenangkan jerawat, meski hasil "
               "penelitiannya masih beragam.",
     "perhatian": "Umumnya mudah ditoleransi.",
     "masalah": ["jerawat"],
     "rujukan": [("Gupta dkk., Dermatol Res Pract 2014", "https://pmc.ncbi.nlm.nih.gov/articles/PMC4120804/")]},
    {"kunci": "alpha_arbutin", "nama": "Alpha arbutin",
     "alias": ["alpha arbutin", "arbutin"],
     "fungsi": "Bahan pencerah yang umumnya dipakai untuk membantu menyamarkan noda gelap dan bekas jerawat kehitaman.",
     "perhatian": "Jarang menimbulkan iritasi; tetap pakai sunscreen.",
     "masalah": ["hiperpigmentasi", "kusam"],
     "rujukan": [("Boo, Antioxidants 2021", "https://pmc.ncbi.nlm.nih.gov/articles/PMC8301119/")]},
    {"kunci": "tranexamic_acid", "nama": "Tranexamic acid",
     "alias": ["tranexamic acid", "tranexamic", "asam traneksamat"],
     "fungsi": "Umumnya dipakai untuk membantu menyamarkan noda gelap dan warna kulit yang tidak merata.",
     "perhatian": "Umumnya mudah ditoleransi dalam produk perawatan kulit.",
     "masalah": ["hiperpigmentasi"],
     "rujukan": [("Ulasan asam traneksamat", "https://pmc.ncbi.nlm.nih.gov/articles/PMC12848551/")]},
    {"kunci": "kojic_acid", "nama": "Kojic acid",
     "alias": ["kojic acid", "kojic", "asam kojat"],
     "fungsi": "Bahan pencerah yang umumnya dipakai untuk noda gelap.",
     "perhatian": "Dapat menimbulkan iritasi atau alergi kontak, terutama pada kulit sensitif.",
     "masalah": ["hiperpigmentasi", "kusam"],
     "rujukan": [("Saeedi dkk., Biomed Pharmacother 2019", "https://pubmed.ncbi.nlm.nih.gov/30537675/")]},
    {"kunci": "peptide", "nama": "Peptide",
     "alias": ["peptide", "peptides", "peptida"],
     "fungsi": "Rangkaian asam amino yang umumnya dipakai dalam produk untuk membantu menjaga kekenyalan kulit.",
     "perhatian": "Umumnya mudah ditoleransi.",
     "masalah": ["penuaan"], "rujukan": [("Schagen, Cosmetics 2017", "https://www.mdpi.com/2079-9284/4/2/16")]},
    {"kunci": "aloe_vera", "nama": "Aloe vera (lidah buaya)",
     "alias": ["aloe vera", "aloe", "lidah buaya"],
     "fungsi": "Umumnya dipakai untuk melembapkan dan menenangkan kulit.",
     "perhatian": "Bisa menimbulkan kemerahan atau rasa perih, dan pada sebagian kecil orang alergi.",
     "masalah": ["dehidrasi", "kemerahan_iritasi"],
     "rujukan": [("Surjushe dkk., Indian J Dermatol 2008", "https://pmc.ncbi.nlm.nih.gov/articles/PMC2763764/")]},
    {"kunci": "filter_mineral", "nama": "Zinc oxide & titanium dioxide (filter UV mineral)",
     "alias": ["zinc oxide", "titanium dioxide", "physical sunscreen", "sunscreen fisik", "mineral sunscreen"],
     "fungsi": "Filter UV pada sunscreen mineral yang melindungi kulit dari sinar UV.",
     "perhatian": "Kadang meninggalkan bekas putih (white cast) di kulit.",
     "masalah": [], "rujukan": [("American Academy of Dermatology", "https://www.aad.org/media/stats-sunscreen")]},
    {"kunci": "alkohol", "nama": "Alkohol (alcohol denat, ethanol)",
     "alias": ["alcohol denat", "alkohol", "alcohol", "ethanol", "etanol"],
     "fungsi": "Sering dipakai agar produk cepat kering dan terasa ringan di kulit.",
     "perhatian": "Pada kulit kering atau sensitif dapat menimbulkan rasa kering atau perih, jadi perhatikan reaksi "
                  "kulitmu. Alkohol berlemak seperti cetyl atau cetearyl alcohol berbeda: dipakai sebagai pelembut "
                  "(emolien) yang membantu mencegah kulit kering.",
     "masalah": [],
     "rujukan": [("DermNet NZ", "https://dermnetnz.org/topics/soaps-and-cleansers"),
                 ("Cosmetic Ingredient Review, 1988", "https://journals.sagepub.com/doi/10.3109/10915818809023137")]},
    {"kunci": "pewangi", "nama": "Pewangi (fragrance/parfum)",
     "alias": ["fragrance", "parfum", "pewangi", "wewangian", "perfume"],
     "fungsi": "Ditambahkan agar produk beraroma wangi.",
     "perhatian": "Salah satu pemicu iritasi yang cukup sering pada kulit sensitif; pilih produk tanpa pewangi bila "
                  "kulitmu mudah bereaksi.",
     "masalah": [], "rujukan": [("DermNet NZ", "https://dermnetnz.org/topics/contact-reactions-to-cosmetics")]},
]

CATATAN_UMUM = ("_Ini info umum, bukan pengganti saran dokter kulit. Cek dulu kecocokannya dengan kondisi kulitmu, "
                "misalnya lewat uji tempel, sebelum dipakai rutin._")

_INDEKS = sorted(((alias, e) for e in GLOSARIUM for alias in e["alias"]), key=lambda x: -len(x[0]))
_POLA = [(re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?:nya)?(?![a-z0-9])"), e) for alias, e in _INDEKS]
# alkohol berlemak (pelembap) bukan "alkohol" yang dimaksud entri alkohol -> dibuang sebelum dicocokkan
_ABAIKAN = re.compile(r"\b(cetyl|cetearyl|stearyl|behenyl|lanolin|myristyl|lauryl)\s+alcohol\b")


def semua(teks):
    """Kunci entri glosarium yang disebut di teks, urut kemunculan. Alias terpanjang dicocokkan dulu
    dan bagiannya dihapus, jadi "zinc oxide" tidak ikut terhitung sebagai "zinc"."""
    teks, ketemu = _ABAIKAN.sub(" ", teks.lower()), []
    for pola, entri in _POLA:
        m = pola.search(teks)
        if m:
            ketemu.append((m.start(), entri["kunci"]))
            teks = pola.sub(lambda x: " " * len(x.group()), teks)
    return list(dict.fromkeys(k for _, k in sorted(ketemu)))


# salah ketik nama bahan di PESAN pengguna ("niacenimide"): hanya alias satu kata yang cukup panjang supaya tidak
# tertukar dengan kata sehari-hari. Tidak dipakai untuk kandungan produk (retinal vs retinol harus persis).
_ALIAS_TEBAK = sorted({a for e in GLOSARIUM for a in e["alias"] if " " not in a and len(a) >= 7})
_PER_ALIAS = {a: e["kunci"] for e in GLOSARIUM for a in e["alias"]}


def _jarak(a, b):
    """Jarak edit Levenshtein."""
    baris = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        lalu, baris[0] = baris[0], i
        for j, cb in enumerate(b, 1):
            lalu, baris[j] = baris[j], min(baris[j] + 1, baris[j - 1] + 1, lalu + (ca != cb))
    return baris[-1]


def tebak_salah_ketik(teks):
    """[(kata di pesan, kunci entri, alias)] untuk kata yang bukan nama bahan persis tapi hanya beda sedikit
    ("niacenimide" -> niacinamide): beda 1 huruf untuk nama < 9 huruf, 2 huruf untuk yang lebih panjang."""
    hasil = []
    for kata in dict.fromkeys(re.findall(r"[a-z]+", teks.lower())):
        dasar = kata[:-3] if kata.endswith("nya") and len(kata) >= 9 else kata
        if len(dasar) < 6:
            continue
        jarak, alias = min((_jarak(dasar, a), a) for a in _ALIAS_TEBAK)
        if 0 < jarak <= (1 if max(len(dasar), len(alias)) < 9 else 2):
            hasil.append((kata, _PER_ALIAS[alias], alias))
    return hasil


def cari(teks):
    """Entri glosarium untuk bahan pertama yang disebut di teks, atau None."""
    kunci = semua(teks)
    return per_kunci(kunci[0]) if kunci else None


def per_kunci(kunci):
    return next((e for e in GLOSARIUM if e["kunci"] == kunci), None)
