"""
hitung_akurasi.py

Menghitung akurasi verifikasi manual untuk DUA pipeline pelabelan (tipe
kulit & sentimen) dari file yang sudah diisi manual. Dapat dipakai untuk setiap
ronde verifikasi (misal setelah llm_fallback_tipe_kulit.py): sesuaikan path file
di bawah lalu jalankan ulang.

CARA PAKAI (dari root repo):
    python pipeline/hitung_akurasi.py

TIPE_KULIT_FILE dan SENTIMEN_FILE di bawah diisi sesuai nama file verifikasi
(.csv atau .xlsx, terdeteksi dari ekstensi). Bila salah satu file belum ada atau
belum diisi, bagian itu dilewati tanpa error.

METODE PERHITUNGAN (2 metode beda, karena format kedua file beda):

1) Tipe kulit -- kolom 'setuju_dengan_sistem' diisi verifikator (ya/tidak).
   akurasi = jumlah "ya" / jumlah baris yang sudah diisi (ya + tidak)
   Dipecah juga per status_pelabelan (berbasis_bahan / sinyal_rendah /
   sinyal_campur_rendah / perlu_llm_fallback) untuk melihat kelompok mana yang
   kuat dan mana yang masih lemah.

2) Sentimen -- kolom 'label_manual_sentimen' diisi verifikator (dianggap ground
   truth), dibandingkan dengan 'sentimen_prediksi_llm' (jawaban sistem) baris per
   baris.
   akurasi = jumlah baris yang cocok / total baris terisi
   Ditambah confusion matrix (tabel silang manual vs prediksi) untuk melihat pola
   kesalahan, tidak hanya angka tunggal.

Label sentimen dinormalisasi otomatis (huruf besar/kecil, typo seperti
"Negatig" -> "Negatif") lewat pencocokan awalan kata, bukan tebak-tebakan.
"""
import pandas as pd
from pathlib import Path

DATA_DIR = Path("data")
TIPE_KULIT_FILE = DATA_DIR / "label_verifikasi_tipe_kulit.xlsx"
SENTIMEN_FILE = DATA_DIR / "label_verifikasi_sentimen.xlsx"     


def load_any(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path)


def normalize_sentimen(x) -> str:
    """Cocokkan ke Positif/Netral/Negatif lewat awalan kata -- tahan typo
    seperti 'Negatig' atau beda kapitalisasi, tanpa daftar typo manual."""
    s = str(x).strip().lower()
    if s.startswith("posi"):
        return "Positif"
    if s.startswith("net"):
        return "Netral"
    if s.startswith("neg"):
        return "Negatif"
    return str(x).strip()  # tidak dikenali -- dibiarkan apa adanya, akan kelihatan di confusion matrix


def hitung_akurasi_tipe_kulit(path: Path):
    if not path.exists():
        print(f"[dilewati] {path} tidak ditemukan.\n")
        return
    df = load_any(path)
    if "setuju_dengan_sistem" not in df.columns:
        print(f"[dilewati] {path} tidak punya kolom 'setuju_dengan_sistem'.\n")
        return

    jawaban = df["setuju_dengan_sistem"].astype(str).str.strip().str.lower()
    terisi = jawaban.isin(["ya", "tidak"])
    n_terisi = terisi.sum()

    print("=" * 60)
    print(f"AKURASI TIPE KULIT -- {path.name}")
    print("=" * 60)
    print(f"Baris terisi: {n_terisi} / {len(df)}")
    if n_terisi == 0:
        print("Belum ada baris yang diisi.\n")
        return

    ya = (jawaban == "ya").sum()
    print(f"Akurasi keseluruhan: {ya}/{n_terisi} = {ya/n_terisi*100:.1f}%\n")

    if "status_pelabelan" in df.columns:
        print("Per status_pelabelan:")
        for status in df.loc[terisi, "status_pelabelan"].unique():
            sub = jawaban[terisi & (df["status_pelabelan"] == status)]
            s_ya = (sub == "ya").sum()
            print(f"  {status}: {s_ya}/{len(sub)} = {s_ya/len(sub)*100:.1f}%")
    print()


def hitung_akurasi_sentimen(path: Path):
    if not path.exists():
        print(f"[dilewati] {path} tidak ditemukan.\n")
        return
    df = load_any(path)
    cols_needed = {"label_manual_sentimen", "sentimen_prediksi_llm"}
    if not cols_needed.issubset(df.columns):
        print(f"[dilewati] {path} tidak punya kolom {cols_needed}.\n")
        return

    manual = df["label_manual_sentimen"].dropna()
    if len(manual) == 0:
        print(f"[dilewati] {path}: kolom label_manual_sentimen masih kosong semua.\n")
        return

    sub = df.loc[df["label_manual_sentimen"].notna()].copy()

    # baris yang ditandai '(difilter_pengiriman)' di sentimen_prediksi_llm berarti
    # baris itu sudah tidak diprediksi sama sekali oleh pipeline final (dibuang
    # lebih dulu oleh filter pengiriman di label_sentimen.py sebelum sampai ke LLM)
    # -- bukan salah prediksi, sehingga dikeluarkan dari perhitungan akurasi dan
    # dihitung terpisah agar akurasi tidak tampak lebih rendah dari sebenarnya.
    excluded_mask = sub["sentimen_prediksi_llm"].astype(str).str.strip() == "(difilter_pengiriman)"
    n_excluded = excluded_mask.sum()
    sub = sub.loc[~excluded_mask].copy()

    sub["manual_bersih"] = sub["label_manual_sentimen"].apply(normalize_sentimen)
    sub["prediksi_bersih"] = sub["sentimen_prediksi_llm"].apply(normalize_sentimen)

    cocok = sub["manual_bersih"] == sub["prediksi_bersih"]

    print("=" * 60)
    print(f"AKURASI SENTIMEN -- {path.name}")
    print("=" * 60)
    if n_excluded:
        print(f"Baris dikeluarkan (difilter_pengiriman, tidak diprediksi pipeline final): {n_excluded}")
    print(f"Baris terisi & dinilai: {len(sub)} / {len(df)}")
    print(f"Akurasi keseluruhan: {cocok.sum()}/{len(sub)} = {cocok.mean()*100:.1f}%\n")

    print("Confusion matrix (baris = manual/ground truth, kolom = prediksi sistem):")
    print(pd.crosstab(sub["manual_bersih"], sub["prediksi_bersih"]))
    print()


def main():
    hitung_akurasi_tipe_kulit(TIPE_KULIT_FILE)
    hitung_akurasi_sentimen(SENTIMEN_FILE)


if __name__ == "__main__":
    main()