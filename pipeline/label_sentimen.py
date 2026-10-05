import os
import re
import json
import time
import pandas as pd
from dotenv import load_dotenv
from groq import Groq, RateLimitError
from tqdm import tqdm

# 1. Load Environment Variables & Inisialisasi Groq Client
load_dotenv()
api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise ValueError("GROQ_API_KEY tidak ditemukan di file .env. Pastikan Anda sudah mengisinya.")

# timeout eksplisit: tanpa ini, koneksi ke Groq yang macet dapat membuat proses
# menunggu tanpa batas waktu dan tanpa log error.
# max_retries=0: secara default SDK Groq mengulang permintaan sendiri tanpa log
# (bisa memakan waktu beberapa menit). Dimatikan agar error/rate limit langsung
# terlihat dan ditangani logika ulang di skrip ini (termasuk berganti model saat
# kuota harian habis).
client = Groq(api_key=api_key, timeout=60.0, max_retries=0)

# 2. Definisikan Path File
input_file = "data/clean_merged_produk_ulasan.csv"
output_file = "data/clean_merged_produk_ulasan_labelled_v2.csv"

if not os.path.exists(input_file):
    raise FileNotFoundError(f"File {input_file} tidak ditemukan. Pastikan Anda sudah menjalankan `pipeline/cleaning_data.py` terlebih dahulu.")

# 3. Load Data & Cek Checkpoint (Kemampuan Resume dari Batch Sebelumnya)
print(f"Loading data dari {input_file}...")
df_source = pd.read_csv(input_file)

# Hapus baris yang menyebutkan tentang pengiriman/kurir/logistik
delivery_pattern = r"(?i)pengiriman|kirim|kurir|ekspedisi|ongkir|delivery|shipping"
mask_delivery_source = (
    df_source["teks_bebas"].astype(str).str.contains(delivery_pattern, na=False) |
    df_source["teks_ulasan"].astype(str).str.contains(delivery_pattern, na=False)
)
n_delivery_source = mask_delivery_source.sum()
if n_delivery_source > 0:
    print(f"Menghapus {n_delivery_source} baris ulasan dari source yang menyebutkan tentang pengiriman.")
    df_source = df_source[~mask_delivery_source].reset_index(drop=True)

if os.path.exists(output_file):
    print(f"Ditemukan file checkpoint sebelumnya: {output_file}")
    df = pd.read_csv(output_file)

    # Bersihkan juga data pengiriman di checkpoint lama agar sinkron
    mask_delivery_checkpoint = (
        df["teks_bebas"].astype(str).str.contains(delivery_pattern, na=False) |
        df["teks_ulasan"].astype(str).str.contains(delivery_pattern, na=False)
    )
    n_delivery_checkpoint = mask_delivery_checkpoint.sum()
    if n_delivery_checkpoint > 0:
        print(f"Membersihkan {n_delivery_checkpoint} baris ulasan pengiriman dari checkpoint lama.")
        df = df[~mask_delivery_checkpoint].reset_index(drop=True)

    # Pastikan kolom sentimen_prediksi ada
    if "sentimen_prediksi" not in df.columns:
        df["sentimen_prediksi"] = pd.NA

    # Sinkronisasi baris baru jika ada perbedaan ukuran antara input_file dan output_file
    if len(df) < len(df_source):
        print(f"Sinkronisasi data baru... Menambahkan {len(df_source) - len(df)} baris baru ke checkpoint.")
        # Ambil baris baru dari df_source yang belum ada di df
        diff_df = df_source.iloc[len(df):].copy()
        diff_df["sentimen_prediksi"] = pd.NA
        df = pd.concat([df, diff_df], ignore_index=True)
else:
    df = df_source.copy()
    df["sentimen_prediksi"] = pd.NA

# Hitung sisa ulasan yang belum dilabeli
unlabelled_mask = df["sentimen_prediksi"].isna() | (df["sentimen_prediksi"] == "")
df_remaining = df[unlabelled_mask]

total_rows = len(df)
total_remaining = len(df_remaining)

print(f"Total data: {total_rows} baris.")
print(f"Sudah dilabeli: {total_rows - total_remaining} baris.")
print(f"Tersisa untuk dilabeli: {total_remaining} baris.")

if total_remaining == 0:
    print("Semua data sudah berhasil dilabeli! Keluar dari program.")
    exit(0)

# 4. Pengaturan Batching & Rate Limiting
# Model dicoba berurutan; bila kuota harian (TPD) satu model habis, dipakai model
# berikutnya (kuota TPD Groq terpisah per model). llama-3.1-8b-instant dan
# llama-3.3-70b-versatile, yang dipakai di awal pelabelan, dihentikan Groq per
# 2026-08-16. Format jawaban plain text 'ID:SYMBOL' (bukan JSON) membuat
# openai/gpt-oss-20b aman dipakai.
MODELS = ["qwen/qwen3.6-27b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
CURRENT_MODEL_INDEX = 0
# Ukuran batch adalah kompromi: batch terlalu besar lebih sering gagal, batch
# terlalu kecil lambat karena overhead per permintaan.
# Kuota tier gratis Groq: 8000 token/menit (TPM). DELAY_BETWEEN_BATCHES dihitung
# agar mendekati batas itu; jeda yang lebih pendek justru memicu 429 rate limit
# dan penantian 20-60 detik yang lebih lama.
BATCH_SIZE = 40  # Jumlah ulasan per 1 API Call
DELAY_BETWEEN_BATCHES = 9.0  # Jeda (detik) antar batch, disesuaikan dengan batas TPM

LINE_PATTERN = re.compile(r"(\d+)\s*[:\-]\s*([+\-0])")


def process_batch(batch_df: pd.DataFrame, model_name: str) -> dict:
    """
    Mengirimkan satu batch ulasan ke Groq, minta jawaban plain-text baris per
    baris (BUKAN JSON) -- lebih hemat token (tanpa kurung kurawal/tanda kutip)
    dan lebih tahan banting: kalau 1 baris rusak, baris lain tetap kepakai
    (beda dengan JSON yang gagal total kalau ada 1 karakter salah).
    """
    lines = []
    for idx, row in batch_df.iterrows():
        text = str(row["teks_bebas"]).strip()
        # Batasi panjang teks ulasan menjadi 90 karakter agar hemat token
        # (batas TPM 8000 token/menit: makin hemat token per ulasan, makin cepat selesai)
        text_truncated = text[:90] if len(text) > 90 else text
        text_clean = text_truncated.replace("\n", " ").replace("\r", " ")
        lines.append(f"{idx}: {text_clean}")

    system_prompt = (
        "Classify skincare reviews into: Positif (+), Netral (0), or Negatif (-).\n"
        "Assess sentiment regarding PRODUCT quality or skin effect (texture, suitability, results).\n"
        "Netral (0) = the review is ONLY about packaging/shipping/courier/seller arriving safely, "
        "with zero other signal (no repeat-purchase, no product claim, no hope about using it).\n"
        "Reference examples (not part of the batch to classify):\n"
        "- 'Alhamdulillah pesanan sampai selamat, terima kasih' -> Netral "
        "(nothing at all about the product itself).\n"
        "- 'udah langganan disini, semoga cocok juga produk barunya' -> Positif "
        "(repeat customer = trust signal, even though not tried yet).\n"
        "- 'pengiriman cepat, produk original, harganya murah banget' -> Positif "
        "(mentions the product's authenticity/price, not just shipping).\n"
        "Reply with ONE line per review, format exactly 'ID:SYMBOL' (SYMBOL is +, 0, or -), "
        "no JSON, no extra text, no explanation.\n"
        "Example reply:\n"
        "123:+\n124:-\n125:0"
    )

    prompt = "\n".join(lines)

    # PENTING: qwen & gpt-oss adalah "reasoning model" -- defaultnya mereka
    # nulis proses berpikir (reasoning) bercampur di output yang sama sebelum
    # jawaban akhir, yang buang-buang token & waktu. reasoning_format "hidden"
    # buang proses berpikirnya, reasoning_effort diminimalkan supaya model
    # langsung jawab tanpa mikir panjang.
    if "qwen" in model_name:
        reasoning_effort = "none"
    else:  # openai/gpt-oss-*
        reasoning_effort = "low"

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0,
        reasoning_effort=reasoning_effort,
        reasoning_format="hidden",
        # Batasi output secara eksplisit (~6 token per baris "ID:SIMBOL" + buffer)
        # -- tanpa ini, Groq mengira request bisa butuh output sebesar batas
        # maksimum model, lalu nolak duluan dengan 429 OTPM walau output
        # aslinya kecil.
        max_tokens=len(batch_df) * 6 + 40,
    )

    raw_text = response.choices[0].message.content or ""
    results = {}
    for match in LINE_PATTERN.finditer(raw_text):
        results[match.group(1)] = match.group(2)
    return results


# 5. Loop Proses Pelabelan Ulasan
print(f"\nMemulai pelabelan dalam batch (Ukuran batch = {BATCH_SIZE})...")

# Hitung total batch keseluruhan dan batch yang sudah selesai
total_batches = (total_rows + BATCH_SIZE - 1) // BATCH_SIZE
completed_batches = (total_rows - total_remaining) // BATCH_SIZE

pbar = tqdm(
    total=total_batches,
    initial=completed_batches,
    desc="Progress Batch",
    unit="batch"
)

try:
    for i in range(0, len(df_remaining), BATCH_SIZE):
        batch_df = df_remaining.iloc[i:i + BATCH_SIZE]

        # Logika Retry dengan Exponential Backoff jika terkena Rate Limit
        max_retries = 5
        success = False

        for attempt in range(max_retries):
            model_aktif = MODELS[CURRENT_MODEL_INDEX]
            try:
                results_json = process_batch(batch_df, model_aktif)

                # Masukkan hasil ke DataFrame utama
                for key, val in results_json.items():
                    try:
                        idx = int(key)
                    except ValueError:
                        continue

                    sentiment_code = str(val).strip()
                    if sentiment_code == "+":
                        sentiment = "Positif"
                    elif sentiment_code == "-":
                        sentiment = "Negatif"
                    else:
                        sentiment = "Netral"

                    if idx in df.index:
                        df.at[idx, "sentimen_prediksi"] = sentiment

                success = True
                break

            except RateLimitError as e:
                err_msg = str(e).lower()
                if "tpd" in err_msg or "tokens per day" in err_msg:
                    if CURRENT_MODEL_INDEX + 1 < len(MODELS):
                        CURRENT_MODEL_INDEX += 1
                        old_model = model_aktif
                        new_model = MODELS[CURRENT_MODEL_INDEX]
                        print(f"\n[Limit Token Harian] Model {old_model} mencapai TPD limit. Otomatis berpindah ke model cadangan: {new_model}.")
                        continue

                wait_time = (attempt + 1) * 20
                print(f"\n[Rate Limit] Terdeteksi limit API ({model_aktif}). Menunggu {wait_time} detik sebelum mencoba lagi... ({e})")
                time.sleep(wait_time)
            except Exception as e:
                wait_time = (attempt + 1) * 5
                print(f"\n[Error] Terjadi kesalahan: {e}. Mencoba lagi dalam {wait_time} detik...")
                time.sleep(wait_time)

        if not success:
            print(f"\nGagal memproses batch index {batch_df.index[0]} sampai {batch_df.index[-1]}. Dilewati.")

        # Simpan checkpoint ke file setelah setiap batch berhasil selesai
        df.to_csv(output_file, index=False)

        pbar.update(1)

        # Jeda antar batch untuk keamanan rate limit
        time.sleep(DELAY_BETWEEN_BATCHES)

except KeyboardInterrupt:
    print("\nProses dihentikan oleh pengguna. Progress Anda telah tersimpan dengan aman.")
finally:
    pbar.close()

print(f"\nSelesai! Hasil pelabelan akhir disimpan ke: {output_file}")

# Tampilkan statistik hasil pelabelan
df_final = pd.read_csv(output_file)
total_labeled = df_final["sentimen_prediksi"].notna().sum()
print(f"Total data terlabeli saat ini: {total_labeled} / {len(df_final)}")
if total_labeled > 0:
    print("\nDistribusi sentimen hasil prediksi:")
    print(df_final["sentimen_prediksi"].value_counts())