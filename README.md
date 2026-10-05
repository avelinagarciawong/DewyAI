# Dew AI — Chatbot Rekomendasi Skincare Brand Lokal

Dew AI adalah chatbot hibrida yang merekomendasikan produk skincare brand lokal sesuai tipe kulit,
masalah kulit, dan budget pengguna. Rekomendasinya memakai **Content-Based Filtering (CBF)** dan
**Large Language Model (LLM)** dengan data ulasan **Shopee** dan **X**.

Proyek skripsi: *Pengembangan Chatbot Hibrida Sistem Rekomendasi Skincare Brand Lokal Menggunakan
Content-Based Filtering dan Large Language Model Berdasarkan Ulasan Shopee dan X*.

## Cara kerja

Setiap pesan chat diproses empat tahap (diatur oleh `models/percakapan.py`):

1. **NLU** (`models/nlu.py`) membaca tipe kulit, masalah kulit, budget, dan kategori produk dari
   pesan. Aturan (kamus kata, salah ketik, negasi, perumpamaan) bekerja lebih dulu. LLM hanya
   dipanggil kalau aturan tidak yakin, dan jawabannya hanya diterima kalau nilainya ada di daftar
   baku dan buktinya dikutip persis dari pesan pengguna.
2. **CBF** (`models/cbf_engine.py`) memilih produk paling cocok dari 961 produk dengan TF-IDF dan
   cosine similarity atas lima fitur: tipe kulit, masalah kulit, kategori, kandungan, deskripsi
   (bobot 4/4/4/2/1).
3. **RAG** (`models/rag_retrieve.py`) mengambil potongan ulasan asli Shopee dan X yang relevan dari
   ChromaDB.
4. **LLM** (`models/generate_jawaban.py`, lewat API Groq) menulis jawaban hanya berdasarkan produk dan
   ulasan tadi. Kalau LLM tidak tersedia, penjelasan disusun otomatis dari data produk.

Aplikasinya terdiri dari backend **FastAPI** (`backend/`, database SQLite untuk akun, riwayat chat,
dan katalog produk) dan frontend **Streamlit** (`frontend/`), termasuk panel admin untuk mengelola
pengguna dan produk.

## Menjalankan di komputer sendiri

Kebutuhan: Python 3.12 atau 3.13, dan koneksi internet untuk memasang paket.

```powershell
# Windows (PowerShell), dari root repo
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-deploy.txt
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-deploy.txt
```

Jalankan backend dan frontend di dua terminal, keduanya **dari root repo**:

```
uvicorn backend.main:app --port 8000
streamlit run frontend/app.py --server.port 8501
```

Lalu buka <http://localhost:8501>. Saat pertama jalan, backend membuat database `backend/chatbot.db`
dan mengisi katalog dari `data/products_final.csv`. Frontend perlu dijalankan dari root repo supaya
tema di `.streamlit/config.toml` ikut terpakai.

### Konfigurasi (`.env` di root repo, semuanya opsional)

| Variabel | Fungsi | Kalau tidak diisi |
| --- | --- | --- |
| `GROQ_API_KEY` | LLM untuk menulis jawaban dan NLU cadangan (key gratis di console.groq.com) | Penjelasan disusun otomatis, NLU memakai aturan saja |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAMA` | Membuat akun admin saat backend dinyalakan (password minimal 8 karakter) | Tidak ada akun admin; daftar akun biasa tetap bisa |
| `JWT_SECRET` | Kunci token login | Dibuat otomatis dan disimpan ke `.env` |
| `MODE_RINGAN=1` | Backend tanpa RAG dan LLM (CBF saja), startup cepat | – |

Contoh isi:

```
GROQ_API_KEY=isi_key_groq
ADMIN_EMAIL=admin@contoh.com
ADMIN_PASSWORD=minimal8karakter
ADMIN_NAMA=Admin
```

### Index RAG (kutipan ulasan)

Index ChromaDB (sekitar 100 MB) tidak disertakan, tapi bisa dibangun dari data di repo. Prosesnya
sekitar 10 menit di CPU dan mengunduh model embedding (sekitar 420 MB) sekali:

```
python models/bangun_rag_index.py
```

Tanpa index, chatbot tetap berjalan, hanya tanpa kutipan ulasan.

## Struktur folder

| Folder | Isi |
| --- | --- |
| `backend/` | API FastAPI: autentikasi JWT, chat, riwayat, panel admin, database SQLite |
| `frontend/` | Antarmuka Streamlit: onboarding, chat, login/register, profil, panel admin |
| `models/` | NLU, CBF, RAG, LLM, dan orkestrasi percakapan; juga skrip evaluasi CBF dan NLU serta pembangun index RAG |
| `pipeline/` | Scraping, cleaning, pelabelan, dan penyusunan katalog produk |
| `tests/` | Uji skenario chatbot, login/register, dan panel admin |
| `deploy/` | Konfigurasi server (Caddy, systemd) dan skrip instalasi |
| `data/` | Katalog produk final, ulasan Shopee berlabel sentimen, post X versi anonim |

## Pengujian

```
python tests/uji_skenario_chatbot.py [--bagian N]   # butuh backend lengkap jalan di :8000 (dengan GROQ_API_KEY)
python tests/uji_login_register.py [--bagian N]     # menyalakan backend & frontend sendiri; butuh Google Chrome
python tests/uji_admin.py [--bagian 1..7]           # menyalakan backend sendiri
```

## Evaluasi

- **CBF**: `python models/evaluasi_cbf_split.py`. Pembagian data 60/20/20, diulang dengan seed 42,
  123, dan 2026; metrik Precision, Recall, F1, dan NDCG@10.
- **NLU**: `python models/evaluasi_nlu.py`. Membandingkan empat pendekatan (aturan saja, hibrida
  aturan + LLM, kemiripan embedding, zero-shot NLI) pada set uji kalimat berlabel manual
  `data/uji_nlu.csv`.

## Pipeline data

Data mentah dan hasil antara tidak disertakan. Urutan pembuatannya (semua dijalankan dari root repo,
hasil disimpan di `data/`):

| Langkah | Skrip | Hasil |
| --- | --- | --- |
| 1. Scraping produk & ulasan Shopee | `pipeline/02_scrape_shopee.py` | `raw_shopee_produk.csv`, `raw_shopee_ulasan.csv` |
| 2. Scraping post X | `pipeline/02_scrape_x.py` | `raw_x_ulasan.csv` |
| 3. Cleaning | `pipeline/cleaning_data.py` | `clean_produk.csv`, `clean_merged_produk_ulasan.csv`, `clean_x.csv` |
| 4. Deskripsi produk, lalu cleaning lagi | `pipeline/scrape_deskripsi_produk.py` | `deskripsi_produk.csv` → `clean_produk_full.csv` |
| 5. Label tipe & masalah kulit | `pipeline/label_tipe_kulit.py`, `pipeline/llm_fallback_tipe_kulit.py` | `clean_produk_labelled_tipe_kulit_v2.csv` |
| 6. Label sentimen ulasan | `pipeline/label_sentimen.py`, `pipeline/agregasi_sentimen.py` | `clean_merged_produk_ulasan_labelled_v2.csv`, `agregasi_sentimen_produk.csv` |
| 7. Katalog final | `pipeline/build_products_final.py`, `pipeline/ekstrak_brand_kategori.py` | `products_final.csv` |

Catatan:

- Pipeline memakai `requirements.txt` (berisi paket scraping), bukan `requirements-deploy.txt`.
  Cek lingkungan dengan `python pipeline/01_test_setup.py`.
- Scraper membuka Google Chrome. Login Shopee/X dan captcha diselesaikan manual, dan skrip menunggu
  sampai kamu mengetik `lanjut` di terminal. Profil Chrome disimpan di root repo (`chrome_profile*`,
  tidak ikut di-upload).
- Tampilan Shopee dan X bisa berubah, sehingga pemilih elemen di scraper mungkin perlu disesuaikan.
- Pelabelan (langkah 5 dan 6) memakai LLM Groq, jadi butuh `GROQ_API_KEY`.

## Deploy

Lihat [DEPLOY.md](DEPLOY.md): satu VM Ubuntu dengan Caddy (HTTPS) di depan Streamlit dan FastAPI.
