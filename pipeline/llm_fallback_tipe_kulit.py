"""
llm_fallback_tipe_kulit.py

Melengkapi tipe_kulit_cocok & masalah_kulit_cocok untuk produk yang GAGAL
mendapat label dari keyword matching (label_tipe_kulit.py): berstatus
'perlu_llm_fallback' (0 bahan referensi terdeteksi) MAUPUN
'sinyal_rendah'/'sinyal_campur_rendah' (bahan terdeteksi tetapi tidak lolos
threshold voting >=2; satu bahan saja tidak mungkin menghasilkan label, sehingga
tetap kosong tanpa LLM).

METODOLOGI (pendekatan hibrida): bahan bersitasi (referensi_tipe_kulit.csv)
tetap PRIORITAS UTAMA -- produk berstatus 'berbasis_bahan' TIDAK disentuh LLM,
nilainya disalin apa adanya ke kolom _final. LLM hanya melengkapi produk yang
hasil keyword matching-nya kurang yakin, dengan membaca teks deskripsi/nama/
komposisi.

Sumber : data/clean_produk_labelled_tipe_kulit.csv
Output : data/clean_produk_labelled_tipe_kulit_v2.csv
  Kolom baru: tipe_kulit_cocok_final, masalah_kulit_cocok_final,
  sumber_label_tipe_kulit ('bahan'/'llm'), sumber_label_masalah_kulit ('bahan'/'llm')

CARA PAKAI (dari root repo):
    python pipeline/llm_fallback_tipe_kulit.py
Dapat dilanjutkan: file output dibaca ulang sebagai checkpoint bila sudah ada,
dan hanya baris yang kolom _final-nya masih kosong yang diproses.
"""
import os
import re
import time
import pandas as pd
from dotenv import load_dotenv
from groq import Groq, RateLimitError
from tqdm import tqdm

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise ValueError("GROQ_API_KEY tidak ditemukan di file .env. Pastikan Anda sudah mengisinya.")

# timeout & max_retries=0 -- pelajaran dari label_sentimen.py: tanpa ini,
# SDK bisa nyangkut lama tanpa log kalau koneksi/rate-limit bermasalah.
client = Groq(api_key=api_key, timeout=60.0, max_retries=0)

INPUT_FILE = "data/clean_produk_labelled_tipe_kulit.csv"
OUTPUT_FILE = "data/clean_produk_labelled_tipe_kulit_v2.csv"

TIPE_KATEGORI = ["berminyak", "kering", "sensitif", "normal"]
MASALAH_KATEGORI = ["jerawat", "kusam", "hiperpigmentasi", "penuaan", "kemerahan_iritasi", "dehidrasi"]

# Fallback berlapis model -- pelajaran dari label_sentimen.py: 1 model
# TPD-nya kepakai sendiri per model ID, jadi kalau 1 mentok, otomatis
# pindah ke yang lain sebelum bener-bener berhenti total.
MODELS = ["qwen/qwen3.6-27b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
CURRENT_MODEL_INDEX = 0
BATCH_SIZE = 20  # teks produk lebih panjang drpd 1 baris ulasan, batch dikecilkan
DELAY_BETWEEN_BATCHES = 9.0
BLOB_MAX_CHARS = 700  # skala produk jauh lebih kecil (537) drpd ulasan (26rb), bisa lebih longgar

LINE_PATTERN = re.compile(r"(\d+)\s*:\s*([^|]*)\|\s*(.*)")


def build_blob(row) -> str:
    parts = [
        row.get("nama_produk", ""),
        row.get("deskripsi", ""),
        row.get("raw_komposisi", ""),
        row.get("raw_ingredient_komposisi", ""),
        row.get("raw_zat_aktif", ""),
        row.get("raw_manfaat_perawatan_kulit", ""),
    ]
    blob = " ".join(str(p) for p in parts if pd.notna(p))
    blob = re.sub(r"\s+", " ", blob).strip()
    return blob[:BLOB_MAX_CHARS] if len(blob) > BLOB_MAX_CHARS else blob


def parse_labels(raw: str, valid_categories: list) -> list:
    if not raw or raw.strip() in ("-", ""):
        return []
    tokens = [t.strip().lower() for t in raw.split(",") if t.strip()]
    return [t for t in tokens if t in valid_categories]


def process_batch(batch_df: pd.DataFrame, model_name: str) -> dict:
    lines = [f"{idx}: {build_blob(row)}" for idx, row in batch_df.iterrows()]
    prompt = "\n".join(lines)

    system_prompt = (
        "You are labelling Indonesian skincare products by skin type suitability and skin "
        "problem it addresses, based on the product's name/description/ingredients text.\n"
        f"Skin type categories (pick 0 or more that apply): {', '.join(TIPE_KATEGORI)}.\n"
        f"Skin problem categories (pick 0 or more that apply): {', '.join(MASALAH_KATEGORI)}.\n"
        "Only pick a category if the text gives a genuine signal (explicit claim, or a "
        "well-known ingredient with that function) -- if the text is too vague or generic, "
        "leave it empty ('-') rather than guessing.\n"
        "IMPORTANT: if the text explicitly claims the product suits ALL/ANY skin type "
        "(e.g. 'untuk semua jenis kulit', 'segala jenis kulit', 'all skin type/types', "
        "'cocok untuk semua kulit'), that IS a genuine explicit signal -- select ALL FOUR "
        "skin type categories for it, do NOT leave it empty.\n"
        "Reply with ONE line per product, format exactly:\n"
        "ID: tipe1,tipe2 | masalah1,masalah2\n"
        "(use '-' on either side if none apply). No JSON, no extra text, no explanation.\n"
        "Example reply:\n"
        "12: berminyak,sensitif | jerawat,kusam\n"
        "13: - | -\n"
        "14: kering,normal | dehidrasi"
    )

    reasoning_effort = "none" if "qwen" in model_name else "low"

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        reasoning_effort=reasoning_effort,
        reasoning_format="hidden",
        max_tokens=len(batch_df) * 30 + 60,
    )

    raw_text = response.choices[0].message.content or ""
    results = {}
    for match in LINE_PATTERN.finditer(raw_text):
        idx_str, tipe_str, masalah_str = match.groups()
        results[idx_str] = (tipe_str.strip(), masalah_str.strip())
    return results


def main():
    global CURRENT_MODEL_INDEX

    print(f"Loading {INPUT_FILE}...")
    produk = pd.read_csv(INPUT_FILE)

    if os.path.exists(OUTPUT_FILE):
        print(f"Ditemukan checkpoint sebelumnya: {OUTPUT_FILE}")
        df = pd.read_csv(OUTPUT_FILE)
        if len(df) < len(produk):
            print(f"Sinkronisasi {len(produk) - len(df)} baris baru dari source...")
            diff = produk.iloc[len(df):].copy()
            for col in ["tipe_kulit_cocok_final", "masalah_kulit_cocok_final",
                        "sumber_label_tipe_kulit", "sumber_label_masalah_kulit"]:
                diff[col] = pd.NA
            df = pd.concat([df, diff], ignore_index=True)
    else:
        df = produk.copy()
        df["tipe_kulit_cocok_final"] = pd.NA
        df["masalah_kulit_cocok_final"] = pd.NA
        df["sumber_label_tipe_kulit"] = pd.NA
        df["sumber_label_masalah_kulit"] = pd.NA

    # produk yang statusnya sudah confident dari keyword matching -> copy
    # langsung, JANGAN disentuh LLM (bahan bersitasi = prioritas utama).
    mask_copy_tipe = (df["status_pelabelan"] == "berbasis_bahan") & df["tipe_kulit_cocok_final"].isna()
    df.loc[mask_copy_tipe, "tipe_kulit_cocok_final"] = df.loc[mask_copy_tipe, "tipe_kulit_cocok"]
    df.loc[mask_copy_tipe, "sumber_label_tipe_kulit"] = "bahan"

    mask_copy_masalah = (df["status_masalah_kulit"] == "berbasis_bahan") & df["masalah_kulit_cocok_final"].isna()
    df.loc[mask_copy_masalah, "masalah_kulit_cocok_final"] = df.loc[mask_copy_masalah, "masalah_kulit_cocok"]
    df.loc[mask_copy_masalah, "sumber_label_masalah_kulit"] = "bahan"

    perlu_llm_mask = df["tipe_kulit_cocok_final"].isna() | df["masalah_kulit_cocok_final"].isna()
    df_remaining = df[perlu_llm_mask]

    total_rows = len(df)
    total_remaining = len(df_remaining)
    print(f"Total produk: {total_rows}")
    print(f"Sudah confident dari keyword matching (di-copy, tidak disentuh LLM): {total_rows - total_remaining}")
    print(f"Perlu diproses LLM: {total_remaining}")

    if total_remaining == 0:
        print("Semua produk sudah selesai dilabel! Keluar dari program.")
        return

    total_batches = (total_remaining + BATCH_SIZE - 1) // BATCH_SIZE
    pbar = tqdm(total=total_batches, desc="Progress Batch", unit="batch")

    try:
        for i in range(0, len(df_remaining), BATCH_SIZE):
            batch_df = df_remaining.iloc[i:i + BATCH_SIZE]
            max_retries = 5
            success = False

            for attempt in range(max_retries):
                model_aktif = MODELS[CURRENT_MODEL_INDEX]
                try:
                    results = process_batch(batch_df, model_aktif)

                    for key, (tipe_str, masalah_str) in results.items():
                        try:
                            idx = int(key)
                        except ValueError:
                            continue
                        if idx not in df.index:
                            continue

                        # jangan override label yang sudah confident dari bahan --
                        # dicek lewat sumber_label, bukan hanya isna(), karena baris ini
                        # bisa memerlukan LLM untuk SATU dimensi saja (tipe ATAU
                        # masalah), sedangkan dimensi lainnya sudah yakin dari bahan.
                        if str(df.at[idx, "sumber_label_tipe_kulit"]) != "bahan":
                            tipe_labels = parse_labels(tipe_str, TIPE_KATEGORI)
                            if "berminyak" in tipe_labels and "kering" in tipe_labels:
                                tipe_labels.append("kombinasi")
                            df.at[idx, "tipe_kulit_cocok_final"] = "; ".join(tipe_labels)
                            df.at[idx, "sumber_label_tipe_kulit"] = "llm"

                        if str(df.at[idx, "sumber_label_masalah_kulit"]) != "bahan":
                            masalah_labels = parse_labels(masalah_str, MASALAH_KATEGORI)
                            df.at[idx, "masalah_kulit_cocok_final"] = "; ".join(masalah_labels)
                            df.at[idx, "sumber_label_masalah_kulit"] = "llm"

                    success = True
                    break

                except RateLimitError as e:
                    err_msg = str(e).lower()
                    if "tpd" in err_msg or "tokens per day" in err_msg:
                        if CURRENT_MODEL_INDEX + 1 < len(MODELS):
                            CURRENT_MODEL_INDEX += 1
                            print(f"\n[Limit Token Harian] Model {model_aktif} mencapai TPD limit. "
                                  f"Pindah ke: {MODELS[CURRENT_MODEL_INDEX]}.")
                            continue
                    wait_time = (attempt + 1) * 20
                    print(f"\n[Rate Limit] Terdeteksi limit API ({model_aktif}). "
                          f"Menunggu {wait_time} detik... ({e})")
                    time.sleep(wait_time)
                except Exception as e:
                    wait_time = (attempt + 1) * 5
                    print(f"\n[Error] Terjadi kesalahan: {e}. Mencoba lagi dalam {wait_time} detik...")
                    time.sleep(wait_time)

            if not success:
                print(f"\nGagal memproses batch index {batch_df.index[0]} sampai {batch_df.index[-1]}. Dilewati.")

            df.to_csv(OUTPUT_FILE, index=False)
            pbar.update(1)
            time.sleep(DELAY_BETWEEN_BATCHES)

    except KeyboardInterrupt:
        print("\nProses dihentikan oleh pengguna. Progress Anda telah tersimpan dengan aman.")
    finally:
        pbar.close()

    print(f"\nSelesai! Hasil disimpan ke: {OUTPUT_FILE}")
    final = pd.read_csv(OUTPUT_FILE)
    print(f"tipe_kulit_cocok_final terisi: {final['tipe_kulit_cocok_final'].notna().sum()} / {len(final)}")
    print(f"masalah_kulit_cocok_final terisi: {final['masalah_kulit_cocok_final'].notna().sum()} / {len(final)}")

    print("\nSumber label tipe kulit:")
    print(final["sumber_label_tipe_kulit"].value_counts())
    print("\nSumber label masalah kulit:")
    print(final["sumber_label_masalah_kulit"].value_counts())

    print("\nDistribusi tipe_kulit_cocok_final:")
    exploded = final["tipe_kulit_cocok_final"].dropna().str.split("; ").explode()
    exploded = exploded[exploded != ""]
    print(exploded.value_counts())

    print("\nDistribusi masalah_kulit_cocok_final:")
    exploded_m = final["masalah_kulit_cocok_final"].dropna().str.split("; ").explode()
    exploded_m = exploded_m[exploded_m != ""]
    print(exploded_m.value_counts())


if __name__ == "__main__":
    main()
