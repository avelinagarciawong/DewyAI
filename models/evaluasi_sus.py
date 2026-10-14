"""
evaluasi_sus.py

Menghitung skor System Usability Scale (SUS) dari hasil kuesioner (CSV ekspor Google
Form). SUS terdiri dari 10 pernyataan berskala 1 (sangat tidak setuju) sampai 5
(sangat setuju); pernyataan bernomor ganjil bernada positif, genap bernada negatif.

PERHITUNGAN (Brooke, 1996), per responden:
  - pernyataan ganjil : skor - 1
  - pernyataan genap  : 5 - skor
  - jumlah kesepuluh kontribusi x 2,5 -> skor SUS 0-100

INTERPRETASI rata-rata skor:
  - Rata-rata SUS dari banyak studi sekitar 68 (Sauro & Lewis, 2016).
  - Grade (curved grading scale, Sauro & Lewis, 2016): A+ >= 84,1; A >= 80,8; A- >= 78,9;
    B+ >= 77,2; B >= 74,1; B- >= 72,6; C+ >= 71,1; C >= 65,0; C- >= 62,7; D >= 51,7; F < 51,7.
  - Acceptability (Bangor dkk., 2008): > 70 acceptable, 50-70 marginal, < 50 not acceptable.

FORMAT CSV: kolom pernyataan SUS diberi awalan nomor, mis. "SUS 1 - Saya berpikir akan
menggunakan sistem ini lagi." sampai "SUS 10 - ...", berisi angka 1-5 (skala linear Google
Form). Kolom lain (waktu, perangkat, saran, ...) diabaikan.

PENILAIAN KUALITAS JAWABAN (human evaluation, opsional di CSV): kolom "Kualitas 1 - ..." sampai
"Kualitas 5 - ...", berskala 1-5, satu pernyataan per komponen sistem (CBF, NLU, LLM, RAG,
keseluruhan). Dirangkum terpisah (rata-rata, simpangan baku, persen setuju = nilai 4-5) dan TIDAK
ikut dihitung dalam skor SUS.

CARA PAKAI (dari root repo):
    python models/evaluasi_sus.py                    # data/sus_responden.csv
    python models/evaluasi_sus.py path/lain.csv
Hasil per responden disimpan ke data/hasil_sus.csv.
"""
import re
import sys
from pathlib import Path

import pandas as pd
from scipy import stats

DATA_FILE = Path("data/sus_responden.csv")
HASIL_FILE = Path("data/hasil_sus.csv")
GRADE = [(84.1, "A+"), (80.8, "A"), (78.9, "A-"), (77.2, "B+"), (74.1, "B"), (72.6, "B-"),
         (71.1, "C+"), (65.0, "C"), (62.7, "C-"), (51.7, "D"), (0.0, "F")]
JUMLAH_KUALITAS = 5


def grade(skor):
    return next(g for batas, g in GRADE if skor >= batas)


def acceptability(skor):
    return "acceptable" if skor > 70 else "marginal" if skor >= 50 else "not acceptable"


def skor_dari_jawaban(jawaban):
    """[jawaban SUS 1..10, masing-masing 1-5] -> skor SUS 0-100 (dipakai juga backend)."""
    return sum((n - 1) if i % 2 == 1 else (5 - n) for i, n in enumerate(jawaban, 1)) * 2.5


def ringkas(skor):
    """Daftar skor SUS -> ringkasan statistik (dipakai juga panel admin)."""
    s = pd.Series(list(skor), dtype=float)
    n = len(s)
    if not n:
        return {"n": 0}
    rata = float(s.mean())
    sd = float(s.std(ddof=1)) if n > 1 else 0.0
    if n > 1 and sd > 0:
        bawah, atas = stats.t.interval(0.95, n - 1, loc=rata, scale=sd / n ** 0.5)
        bawah, atas = max(0.0, float(bawah)), min(100.0, float(atas))  # skor SUS selalu di rentang 0-100
    else:  # satu responden, atau semua skor sama
        bawah = atas = rata
    return {"n": n, "rata": rata, "sd": sd, "median": float(s.median()), "min": float(s.min()),
            "maks": float(s.max()), "ik_bawah": bawah, "ik_atas": atas, "grade": grade(rata),
            "acceptability": acceptability(rata)}


def kolom_sus(df):
    """Nomor pernyataan (1-10) -> nama kolom, dari awalan "SUS <n>" pada judul kolom."""
    peta = {}
    for c in df.columns:
        m = re.match(r"\s*SUS\s*(\d+)\b", str(c), re.I)
        if m and 1 <= int(m.group(1)) <= 10:
            peta[int(m.group(1))] = c
    kurang = sorted(set(range(1, 11)) - set(peta))
    if kurang:
        sys.exit(f"Kolom SUS nomor {kurang} tidak ditemukan. Judul kolom harus diawali 'SUS 1', 'SUS 2', dst.")
    return peta


def ringkas_kualitas(daftar):
    """[[5 jawaban 1-5] per responden] -> per pernyataan: n, rata-rata, simpangan baku, dan persen
    setuju (nilai 4-5). Dipakai juga panel admin."""
    hasil = []
    for i in range(JUMLAH_KUALITAS):
        s = pd.Series([j[i] for j in daftar], dtype=float)
        n = len(s)
        hasil.append({"n": n, "rata": float(s.mean()) if n else None,
                      "sd": (float(s.std(ddof=1)) if n > 1 else 0.0) if n else None,
                      "setuju": float((s >= 4).mean()) if n else None})
    return hasil


def kolom_kualitas(df):
    """Nomor pernyataan kualitas (1-5) -> nama kolom dari awalan "Kualitas <n>"; kosong kalau CSV tidak memuatnya."""
    peta = {}
    for c in df.columns:
        m = re.match(r"\s*Kualitas\s*(\d+)\b", str(c), re.I)
        if m and 1 <= int(m.group(1)) <= JUMLAH_KUALITAS:
            peta[int(m.group(1))] = c
    return peta if len(peta) == JUMLAH_KUALITAS else {}


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_FILE
    if not path.exists():
        sys.exit(f"File {path} belum ada. Unduh respons Google Form sebagai CSV ke lokasi ini.")
    df = pd.read_csv(path)
    peta = kolom_sus(df)
    jawaban = df[[peta[n] for n in range(1, 11)]].apply(pd.to_numeric, errors="coerce")
    tidak_lengkap = jawaban.isna().any(axis=1) | ~jawaban.isin([1, 2, 3, 4, 5]).all(axis=1)
    if tidak_lengkap.any():
        print(f"Dilewati {int(tidak_lengkap.sum())} responden yang jawabannya tidak lengkap/di luar 1-5 "
              f"(baris CSV: {[i + 2 for i in df.index[tidak_lengkap]]}).")
    df = df.loc[~tidak_lengkap].reset_index(drop=True)
    if df.empty:
        sys.exit("Tidak ada responden dengan jawaban lengkap.")

    df["skor_sus"] = df.apply(lambda b: skor_dari_jawaban([int(b[peta[n]]) for n in range(1, 11)]), axis=1)
    r = ringkas(df["skor_sus"])

    print(f"Responden valid : {r['n']}")
    print(f"Skor SUS        : rata-rata {r['rata']:.1f} (SD {r['sd']:.1f}), median {r['median']:.1f}, "
          f"min {r['min']:.1f}, maks {r['maks']:.1f}")
    print(f"IK 95%          : {r['ik_bawah']:.1f} - {r['ik_atas']:.1f}")
    print(f"Grade           : {r['grade']} (Sauro & Lewis, 2016); {r['acceptability']} (Bangor dkk., 2008)")
    print("\nRata-rata jawaban per pernyataan (1-5):")
    for k in range(1, 11):
        arah = "positif" if k % 2 else "negatif"
        print(f"  SUS {k:>2} ({arah}): {pd.to_numeric(df[peta[k]]).mean():.2f}")
    print("\nSebaran grade responden:", df["skor_sus"].map(grade).value_counts().to_dict())

    peta_k = kolom_kualitas(df)
    if peta_k:
        nilai = df[[peta_k[n] for n in range(1, JUMLAH_KUALITAS + 1)]].apply(pd.to_numeric, errors="coerce")
        lengkap = nilai.isin([1, 2, 3, 4, 5]).all(axis=1)
        print(f"\nPenilaian kualitas jawaban ({int(lengkap.sum())} responden; terpisah dari skor SUS):")
        for n, r in enumerate(ringkas_kualitas(nilai[lengkap].astype(int).values.tolist()) if lengkap.any() else [], 1):
            print(f"  Kualitas {n}: rata-rata {r['rata']:.2f} (SD {r['sd']:.2f}), setuju {r['setuju']:.0%}"
                  f" -- {peta_k[n].split(' - ', 1)[-1]}")

    df.to_csv(HASIL_FILE, index=False)
    print(f"\nTersimpan: {HASIL_FILE}")


if __name__ == "__main__":
    main()
