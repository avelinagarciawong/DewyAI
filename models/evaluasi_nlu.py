"""
evaluasi_nlu.py

Evaluasi NLU secara terukur dengan set uji kalimat informal berlabel manual,
membandingkan 4 pendekatan pada kalimat yang sama:

  A. ATURAN SAJA   -- nlu.analisis() (kamus kata, typo, negasi, perumpamaan), tanpa LLM.
  B. HIBRIDA       -- A, lalu kalau aturan tidak yakin (analisis()['perlu_llm']) LLM
                      dimintai tafsiran lewat GeneratorJawaban.pahami_profil (nilai baku +
                      bukti kutipan persis dari pesan). Persis alur yang dipakai sistem
                      (Percakapan._pahami_dengan_llm): nilai yang sudah terbaca aturan
                      tidak pernah ditimpa LLM.
  C. KEMIRIPAN EMBEDDING -- kalimat & beberapa kalimat deskripsi tiap label diubah jadi
                      vektor (paraphrase-multilingual-MiniLM-L12-v2, model yang sama
                      dengan RAG); skor label = cosine tertinggi ke deskripsinya.
  D. ZERO-SHOT NLI -- kalimat = premis, "Orang ini memiliki kulit berminyak." dst =
                      hipotesis; skor label = peluang entailment
                      (MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7, dilatih
                      NLI 27 bahasa termasuk bahasa Indonesia; Laurer dkk., 2022).

LABEL yang diuji = yang dipakai CBF sebagai filter:
  - tipe_kulit  : SATU dari berminyak/kering/kombinasi/sensitif/normal, atau kosong
  - masalah_kulit: NOL atau lebih dari jerawat/kusam/hiperpigmentasi/penuaan/
                  kemerahan_iritasi/dehidrasi (multi-label)
Budget & kategori produk TIDAK diuji di sini (dibaca aturan/regex di semua pendekatan).

PEMBAGIAN DATA. A & B tidak punya parameter yang disetel. C & D butuh AMBANG skor
(di bawah ambang = label dianggap tidak disebut), dan ambang itu tidak boleh dipilih
pakai data yang sama dengan yang dinilai. Jadi set uji dibagi acak:
  - DEV (30%)  : khusus memilih ambang C & D (grid search, F1 mikro tertinggi)
  - TEST (70%) : SEMUA pendekatan dinilai di sini
Diulang 3 kali dengan seed 42, 123, 2026 (sama dengan evaluasi CBF), lalu dirata-rata
dan dihitung standar deviasinya.

METRIK per field: Precision/Recall/F1 per label, F1 mikro (gabungan semua label) dan
F1 makro (rata-rata label yang muncul di data), plus EXACT MATCH per kalimat (tipe
DAN masalah kulit tepat semua) dan waktu rata-rata per kalimat.

LLM (B) memakai kuota Groq: jawaban LLM per kalimat disimpan di CACHE_LLM, jadi
menjalankan ulang tidak memanggil LLM lagi untuk kalimat yang sama. Panggilan yang
GAGAL (rate limit/jaringan) tidak pernah dicatat sebagai "LLM tidak paham" --
ditunggu lalu diulang.

FORMAT SET UJI (CSV, UTF-8): kolom id, kalimat, tipe_kulit, masalah_kulit
  (masalah_kulit lebih dari satu dipisah titik koma, mis. "jerawat;kusam"; kosong =
  tidak disebut). Kolom lain (penulis, catatan, ...) boleh ada dan diabaikan.

CARA PAKAI (dari root repo):
    python models/evaluasi_nlu.py                 # set uji data/uji_nlu.csv
    python models/evaluasi_nlu.py path/lain.csv
"""
import json
import random
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nlu  # noqa: E402
from generate_jawaban import MASALAH_KULIT_VALID, MODELS, TIPE_KULIT_VALID  # noqa: E402

DATA_FILE = Path("data/uji_nlu.csv")
KATALOG_FILE = Path("data/products_final.csv")  # kosakata merek, sama seperti Percakapan
CACHE_LLM = Path("data/cache_llm_nlu.json")
HASIL_RINGKAS = Path("data/hasil_evaluasi_nlu.csv")
HASIL_PER_LABEL = Path("data/hasil_evaluasi_nlu_per_label.csv")
HASIL_PREDIKSI = Path("data/prediksi_nlu.csv")

DAFTAR_SEED = [42, 123, 2026]
PORSI_DEV = 0.3
MODEL_EMBEDDING = "paraphrase-multilingual-MiniLM-L12-v2"
MODEL_NLI = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
GRID_EMBEDDING = np.round(np.arange(0.20, 0.91, 0.01), 2)
GRID_NLI = np.round(np.arange(0.01, 1.00, 0.01), 2)
JEDA_ANTAR_LLM = 8      # detik; kuota gratis Groq ~8.000 token/menit
JEDA_SETELAH_GAGAL = 65  # detik; rate limit/jaringan -> tunggu lalu ulangi
MAKS_ULANG_LLM = 5

TIPE = list(TIPE_KULIT_VALID)
MASALAH = list(MASALAH_KULIT_VALID)
PENDEKATAN = ["A. Aturan saja", "B. Hibrida (aturan + LLM)", "C. Kemiripan embedding", "D. Zero-shot NLI"]

# Deskripsi label untuk C, ditulis SEBELUM set uji ada (bagian dari desain pendekatan,
# bukan disesuaikan dengan isi set uji).
PROTOTIPE_EMBEDDING = {
    "berminyak": ["kulit saya berminyak", "wajah cepat mengkilap dan berminyak",
                  "muka gampang lengket karena minyak", "minyak berlebih di seluruh wajah"],
    "kering": ["kulit saya kering", "wajah terasa kering dan kasar", "kulit mengelupas dan terasa ketarik",
               "muka kering bersisik"],
    "kombinasi": ["kulit saya kombinasi", "berminyak di dahi dan hidung tapi pipi kering",
                  "area T berminyak, bagian wajah lain kering"],
    "sensitif": ["kulit saya sensitif", "kulit gampang perih dan bereaksi terhadap produk",
                 "wajah mudah iritasi kalau ganti skincare"],
    "normal": ["kulit saya normal", "kulit tidak berminyak dan tidak kering",
               "kondisi kulit wajah seimbang dan jarang bermasalah"],
    "jerawat": ["wajah saya berjerawat", "sering muncul jerawat dan komedo", "jerawat meradang di pipi dan dagu"],
    "kusam": ["kulit saya kusam", "wajah terlihat gelap dan tidak cerah", "muka tidak glowing dan terlihat lelah"],
    "hiperpigmentasi": ["ada flek hitam di wajah", "bekas jerawat menghitam", "noda gelap dan warna kulit tidak merata"],
    "penuaan": ["muncul kerutan di wajah", "kulit mulai kendur dan terlihat tua", "garis halus di sekitar mata"],
    "kemerahan_iritasi": ["wajah saya kemerahan", "kulit merah dan iritasi", "muka gatal, perih, dan kemerahan"],
    "dehidrasi": ["kulit saya dehidrasi", "kulit kurang lembap dan kekurangan air",
                  "wajah terasa kencang dan kurang hidrasi"],
}

# Hipotesis untuk D (template satu kalimat per label, juga ditulis sebelum set uji ada).
HIPOTESIS_NLI = {
    "berminyak": "Orang ini memiliki kulit berminyak.",
    "kering": "Orang ini memiliki kulit kering.",
    "kombinasi": "Orang ini memiliki kulit kombinasi, berminyak di sebagian wajah dan kering di bagian lain.",
    "sensitif": "Orang ini memiliki kulit sensitif yang mudah bereaksi.",
    "normal": "Orang ini memiliki kulit normal.",
    "jerawat": "Orang ini memiliki masalah jerawat.",
    "kusam": "Orang ini memiliki kulit kusam.",
    "hiperpigmentasi": "Orang ini memiliki flek hitam atau bekas jerawat yang menghitam.",
    "penuaan": "Orang ini memiliki tanda penuaan seperti kerutan.",
    "kemerahan_iritasi": "Orang ini memiliki kulit kemerahan atau iritasi.",
    "dehidrasi": "Orang ini memiliki kulit dehidrasi yang kurang lembap.",
}


# ---------------- set uji ----------------

def baca_set_uji(path):
    """CSV -> DataFrame (kalimat, tipe: str|None, masalah: frozenset). Label di luar
    daftar baku langsung dilaporkan per baris (salah ketik label = hasil evaluasi salah)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    kurang = {"id", "kalimat", "tipe_kulit", "masalah_kulit"} - set(df.columns)
    if kurang:
        sys.exit(f"Kolom wajib tidak ada di {path}: {sorted(kurang)}")
    salah = []
    tipe, masalah = [], []
    for _, r in df.iterrows():
        t = r["tipe_kulit"].strip().lower() or None
        m = frozenset(x.strip().lower() for x in r["masalah_kulit"].replace(",", ";").split(";") if x.strip())
        if not r["kalimat"].strip():
            salah.append(f"id {r['id']}: kalimat kosong")
        if t is not None and t not in TIPE:
            salah.append(f"id {r['id']}: tipe_kulit '{t}' bukan salah satu dari {TIPE}")
        if m - set(MASALAH):
            salah.append(f"id {r['id']}: masalah_kulit {sorted(m - set(MASALAH))} bukan salah satu dari {MASALAH}")
        tipe.append(t)
        masalah.append(m)
    if df["id"].duplicated().any():
        salah.append(f"id dobel: {sorted(df.loc[df['id'].duplicated(), 'id'].unique())}")
    if salah:
        sys.exit("Set uji belum valid:\n  " + "\n  ".join(salah))
    return pd.DataFrame({"id": df["id"], "kalimat": df["kalimat"].str.strip(), "tipe": tipe, "masalah": masalah})


def split_dev_test(n, seed):
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    batas = round(n * PORSI_DEV)
    return sorted(idx[:batas]), sorted(idx[batas:])


# ---------------- pendekatan A & B ----------------

def kosakata_merek():
    if not KATALOG_FILE.exists():
        return frozenset()
    brand = pd.read_csv(KATALOG_FILE, usecols=["brand"])["brand"]
    return frozenset(brand.dropna().astype(str).str.lower().str.strip())


def prediksi_aturan(kalimat, merek):
    a = nlu.analisis(kalimat, kosakata_merek=merek)
    return a, a["tipe_kulit"], frozenset(a["masalah_kulit"])


def _muat_cache():
    if CACHE_LLM.exists():
        return json.loads(CACHE_LLM.read_text(encoding="utf-8"))
    return {}


def _simpan_cache(cache):
    CACHE_LLM.parent.mkdir(parents=True, exist_ok=True)
    CACHE_LLM.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def tafsiran_llm(gen, kalimat, cache):
    """pahami_profil dengan cache & ulang otomatis. None yang dicatat = LLM benar-benar
    menjawab tapi tidak ada nilai yang lolos validasi -- bukan karena gagal dipanggil."""
    if kalimat in cache:
        return cache[kalimat]
    for coba in range(1, MAKS_ULANG_LLM + 1):
        gen._model_index, gen._libur_sampai = 0, 0.0  # selalu mulai dari model utama
        mulai = time.perf_counter()
        hasil = gen.pahami_profil(kalimat)
        detik = time.perf_counter() - mulai
        if gen._libur_sampai == 0.0:  # tidak di-set = ada model yang menjawab
            cache[kalimat] = {"hasil": hasil, "model": MODELS[gen._model_index], "detik": round(detik, 2)}
            _simpan_cache(cache)
            time.sleep(JEDA_ANTAR_LLM)
            return cache[kalimat]
        print(f"    LLM gagal dipanggil (percobaan {coba}/{MAKS_ULANG_LLM}), tunggu {JEDA_SETELAH_GAGAL} detik ...")
        time.sleep(JEDA_SETELAH_GAGAL)
    sys.exit("LLM terus gagal dipanggil (kuota habis/jaringan). Jalankan lagi nanti -- "
             "jawaban yang sudah didapat tersimpan di cache.")


def prediksi_semua_aturan_hibrida(data):
    from generate_jawaban import GeneratorJawaban

    merek = kosakata_merek()
    gen, cache = None, _muat_cache()
    hasil = {"A": [], "B": []}
    waktu = {"A": [], "B": []}
    n_llm = 0
    for i, kalimat in enumerate(data["kalimat"], 1):
        mulai = time.perf_counter()
        a, tipe, masalah = prediksi_aturan(kalimat, merek)
        t_aturan = time.perf_counter() - mulai
        hasil["A"].append((tipe, masalah))
        waktu["A"].append(t_aturan)
        # syarat sama dengan Percakapan._jalankan
        if a["perlu_llm"] and a["intent"] in ("rekomendasi", "tidak_jelas", "di_luar_topik"):
            n_llm += 1
            if gen is None:
                gen = GeneratorJawaban(cbf_engine=None)
            if kalimat not in cache:
                print(f"  [{i}/{len(data)}] tanya LLM: {kalimat[:70]!r}")
            catatan = tafsiran_llm(gen, kalimat, cache)
            h = catatan["hasil"]
            if h:
                tipe = tipe or h["tipe_kulit"]
                masalah = masalah or frozenset(h["masalah_kulit"])
            waktu["B"].append(t_aturan + catatan["detik"])
        else:
            waktu["B"].append(t_aturan)
        hasil["B"].append((tipe, masalah))
    return hasil, waktu, n_llm


# ---------------- pendekatan C & D: skor per label ----------------

def skor_embedding(kalimat):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_EMBEDDING)
    mulai = time.perf_counter()
    v_kalimat = model.encode(list(kalimat), normalize_embeddings=True, batch_size=32)
    skor = np.zeros((len(kalimat), len(TIPE) + len(MASALAH)))
    for j, label in enumerate(TIPE + MASALAH):
        v_proto = model.encode(PROTOTIPE_EMBEDDING[label], normalize_embeddings=True)
        skor[:, j] = (v_kalimat @ v_proto.T).max(axis=1)
    return skor, (time.perf_counter() - mulai) / len(kalimat)


def skor_nli(kalimat):
    """Peluang entailment tiap hipotesis, dihitung seperti pipeline zero-shot-classification
    Hugging Face mode multi_label (softmax entailment vs contradiction per hipotesis) -- tapi
    langsung dari model: 11 pasangan sekali jalan, ~6x lebih cepat dari pipeline di CPU."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL_NLI)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NLI).eval()
    id_kontra, id_entail = model.config.label2id["contradiction"], model.config.label2id["entailment"]
    hipotesis = [HIPOTESIS_NLI[x] for x in TIPE + MASALAH]
    mulai = time.perf_counter()
    skor = np.zeros((len(kalimat), len(hipotesis)))
    with torch.inference_mode():
        for i, k in enumerate(kalimat):
            enc = tok([k] * len(hipotesis), hipotesis, return_tensors="pt", padding=True, truncation=True)
            logit = model(**enc).logits[:, [id_kontra, id_entail]]
            skor[i] = logit.softmax(dim=-1)[:, 1].numpy()
    return skor, (time.perf_counter() - mulai) / len(kalimat)


def dari_skor(skor, ambang_tipe, ambang_masalah):
    """Skor -> prediksi: tipe = label tipe berskor tertinggi kalau >= ambang (satu nilai),
    masalah = semua label masalah yang skornya >= ambang."""
    hasil = []
    for baris in skor:
        st, sm = baris[:len(TIPE)], baris[len(TIPE):]
        tipe = TIPE[int(st.argmax())] if st.max() >= ambang_tipe else None
        hasil.append((tipe, frozenset(m for m, s in zip(MASALAH, sm) if s >= ambang_masalah)))
    return hasil


def pilih_ambang(skor, data, idx_dev, grid):
    """Ambang tipe & masalah dipilih TERPISAH di set dev (F1 mikro masing-masing tertinggi;
    kalau seri, ambang terkecil)."""
    emas = [(data["tipe"][i], data["masalah"][i]) for i in idx_dev]
    terbaik_t = max(grid, key=lambda a: (f1_mikro(emas, dari_skor(skor[idx_dev], a, 9), "tipe"), -a))
    terbaik_m = max(grid, key=lambda a: (f1_mikro(emas, dari_skor(skor[idx_dev], 9, a), "masalah"), -a))
    return float(terbaik_t), float(terbaik_m)


# ---------------- metrik ----------------

def _set_label(pasangan, field):
    tipe, masalah = pasangan
    return ({tipe} if tipe else set()) if field == "tipe" else set(masalah)


def hitung_per_label(emas, prediksi, field):
    labels = TIPE if field == "tipe" else MASALAH
    hasil = {}
    for lb in labels:
        tp = sum(lb in _set_label(e, field) and lb in _set_label(p, field) for e, p in zip(emas, prediksi))
        fp = sum(lb not in _set_label(e, field) and lb in _set_label(p, field) for e, p in zip(emas, prediksi))
        fn = sum(lb in _set_label(e, field) and lb not in _set_label(p, field) for e, p in zip(emas, prediksi))
        hasil[lb] = {"tp": tp, "fp": fp, "fn": fn, "support": tp + fn}
    return hasil


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def f1_mikro(emas, prediksi, field):
    per = hitung_per_label(emas, prediksi, field).values()
    return _prf(sum(x["tp"] for x in per), sum(x["fp"] for x in per), sum(x["fn"] for x in per))[2]


def ringkasan_metrik(emas, prediksi):
    m = {}
    for field in ("tipe", "masalah"):
        per = hitung_per_label(emas, prediksi, field)
        p, r, f = _prf(sum(x["tp"] for x in per.values()), sum(x["fp"] for x in per.values()),
                       sum(x["fn"] for x in per.values()))
        ada = [lb for lb, x in per.items() if x["support"] > 0]
        m[f"P_mikro_{field}"], m[f"R_mikro_{field}"], m[f"F1_mikro_{field}"] = p, r, f
        m[f"F1_makro_{field}"] = statistics.mean(_prf(per[lb]["tp"], per[lb]["fp"], per[lb]["fn"])[2]
                                                 for lb in ada) if ada else 0.0
    m["exact_match"] = statistics.mean((e[0] == p[0] and e[1] == p[1]) for e, p in zip(emas, prediksi))
    return m


# ---------------- alur utama ----------------

def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_FILE
    if not path.exists():
        sys.exit(f"Set uji {path} belum ada. Lihat FORMAT SET UJI di docstring skrip ini.")
    data = baca_set_uji(path)
    n = len(data)
    print(f"Set uji: {path} ({n} kalimat)")
    emas_semua = list(zip(data["tipe"], data["masalah"]))

    print("\n[1/3] Aturan & hibrida ...")
    ab, waktu_ab, n_llm = prediksi_semua_aturan_hibrida(data)
    print(f"  LLM dipanggil untuk {n_llm} dari {n} kalimat ({n_llm / n:.0%})")
    print("[2/3] Skor kemiripan embedding ...")
    skor_c, waktu_c = skor_embedding(data["kalimat"])
    print("[3/3] Skor zero-shot NLI (agak lama di CPU) ...")
    skor_d, waktu_d = skor_nli(data["kalimat"])
    waktu = {"A": statistics.mean(waktu_ab["A"]), "B": statistics.mean(waktu_ab["B"]), "C": waktu_c, "D": waktu_d}

    baris_ringkas, baris_label, ambang_seed = [], [], {}
    for seed in DAFTAR_SEED:
        idx_dev, idx_test = split_dev_test(n, seed)
        amb_c = pilih_ambang(skor_c, data, idx_dev, GRID_EMBEDDING)
        amb_d = pilih_ambang(skor_d, data, idx_dev, GRID_NLI)
        ambang_seed[seed] = {"C": amb_c, "D": amb_d}
        prediksi = {"A": ab["A"], "B": ab["B"], "C": dari_skor(skor_c, *amb_c), "D": dari_skor(skor_d, *amb_d)}
        emas = [emas_semua[i] for i in idx_test]
        for kode, nama in zip("ABCD", PENDEKATAN):
            pred = [prediksi[kode][i] for i in idx_test]
            baris_ringkas.append({"seed": seed, "pendekatan": nama, "n_test": len(idx_test),
                                  **ringkasan_metrik(emas, pred), "detik_per_kalimat": waktu[kode]})
            for field in ("tipe", "masalah"):
                for lb, x in hitung_per_label(emas, pred, field).items():
                    p, r, f = _prf(x["tp"], x["fp"], x["fn"])
                    if not x["support"]:  # label tidak muncul di test seed ini -> tidak ikut dirata-rata
                        p = r = f = float("nan")
                    baris_label.append({"seed": seed, "pendekatan": nama, "field": field, "label": lb,
                                        "support": x["support"], "precision": p, "recall": r, "f1": f})
        print(f"\nSeed {seed}: dev {len(idx_dev)}, test {len(idx_test)} kalimat; ambang embedding "
              f"tipe/masalah = {amb_c[0]:.2f}/{amb_c[1]:.2f}, ambang NLI = {amb_d[0]:.2f}/{amb_d[1]:.2f}")

    ringkas = pd.DataFrame(baris_ringkas)
    per_label = pd.DataFrame(baris_label)
    kolom = ["F1_mikro_tipe", "F1_makro_tipe", "F1_mikro_masalah", "F1_makro_masalah", "exact_match"]
    rata = ringkas.groupby("pendekatan", sort=False)[kolom].agg(["mean", "std"])
    print("\n=== HASIL DI SET TEST (rata-rata ± standar deviasi 3 seed) ===")
    for nama in PENDEKATAN:
        isi = "  ".join(f"{k}={rata.loc[nama, (k, 'mean')]:.3f}±{rata.loc[nama, (k, 'std')]:.3f}" for k in kolom)
        kode = nama[0]
        print(f"{nama:<28} {isi}  waktu/kalimat={waktu[kode] * 1000:.0f} ms")
    print("\n=== F1 PER LABEL (rata-rata 3 seed; support = jumlah kalimat berlabel itu di test, rata-rata) ===")
    tabel = per_label.groupby(["field", "label", "pendekatan"], sort=False)[["f1", "support"]].mean().unstack("pendekatan")
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.float_format", "{:.2f}".format):
        print(tabel["f1"].assign(support=tabel["support"].iloc[:, 0]))

    ringkas.to_csv(HASIL_RINGKAS, index=False)
    per_label.to_csv(HASIL_PER_LABEL, index=False)
    # prediksi per kalimat (seluruh set, ambang C & D dari seed pertama) untuk analisis kesalahan
    amb = ambang_seed[DAFTAR_SEED[0]]
    semua = {"A": ab["A"], "B": ab["B"], "C": dari_skor(skor_c, *amb["C"]), "D": dari_skor(skor_d, *amb["D"])}
    teks = lambda p: f"{p[0] or '-'} | {';'.join(sorted(p[1])) or '-'}"  # noqa: E731
    prediksi_df = pd.DataFrame({"id": data["id"], "kalimat": data["kalimat"], "label": [teks(e) for e in emas_semua]})
    for kode in "ABCD":
        prediksi_df[f"prediksi_{kode}"] = [teks(p) for p in semua[kode]]
        prediksi_df[f"benar_{kode}"] = [e == p for e, p in zip(emas_semua, semua[kode])]
    prediksi_df.to_csv(HASIL_PREDIKSI, index=False)
    print(f"\nTersimpan: {HASIL_RINGKAS}, {HASIL_PER_LABEL}, {HASIL_PREDIKSI}")


if __name__ == "__main__":
    main()
