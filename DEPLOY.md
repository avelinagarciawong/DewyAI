# Deploy ke Azure (VM Ubuntu, Azure for Students)

Panduan menaruh Dew AI online di satu VM Linux Azure, dibiayai kredit **Azure for Students**
($100, tanpa kartu kredit). Semua perintah di laptop ditulis untuk PowerShell dan dijalankan dari
root repo (`C:\chatbot-skincare`).

```
pengunjung ──HTTPS──> Caddy :443 ──> Streamlit 127.0.0.1:8501 ──> FastAPI 127.0.0.1:8000
                      (sertifikat      (frontend/)                 (backend/: CBF + RAG + LLM,
                       otomatis)                                    SQLite /var/lib/dewai)
```

Yang terbuka ke internet hanya Caddy (port 80/443). Backend dan frontend hanya mendengarkan di
localhost; backend hanya dipanggil frontend dari mesin yang sama.

## Isi folder `deploy/`

| File | Fungsi |
|---|---|
| `buat_paket.py` | (laptop) bungkus kode + `data/chroma_db` + `data/products_final.csv` jadi `dewai_paket.tar.gz`. `.env` dan database lokal **tidak** ikut. |
| `setup_server.sh` | (server) pasang semuanya: Python, dependency (torch versi CPU), swap 2 GB, Caddy, service, backup harian. Aman dijalankan ulang, dipakai juga untuk update. |
| `dewai-backend.service`, `dewai-frontend.service` | service systemd: nyala otomatis saat VM boot, restart otomatis kalau crash. |
| `Caddyfile` | HTTPS otomatis (Let's Encrypt) untuk domain VM, diteruskan ke Streamlit. |
| `dewai.env.contoh` | contoh isi `/etc/dewai/dewai.env` (rahasia di server). |
| `set_env.py`, `isi_admin.ps1` | mengisi rahasia server dari laptop lewat SSH tanpa menampilkan nilainya (langkah 7). |
| `dewai-backup` | backup harian database, disimpan 14 hari di `/var/backups/dewai`. |

Susunan di server: kode di `/opt/dewai/app`, virtualenv di `/opt/dewai/venv`, database + cache model
di `/var/lib/dewai`, rahasia di `/etc/dewai/dewai.env`.

## Biaya

| Ukuran VM | RAM | Perkiraan biaya VM/bulan | Kredit $100 cukup |
|---|---|---|---|
| B1ms | 2 GB (+ swap 2 GB) | ± $15 | ± 6 bulan |
| **B2als_v2** (dipakai) | 4 GB | ± $31 (0,0428 USD/jam di Indonesia Central) | ± 3 bulan kalau menyala terus |

B1ms ternyata tidak tersedia untuk langganan Azure for Students ini
(*NotAvailableForSubscription*), jadi dipakai **Standard_B2als_v2** (2 vCPU AMD, x64). Jangan pilih
ukuran ber-RAM 1 GB atau ukuran ARM (nama mengandung "p", mis. B2pls_v2): setup ini hanya diuji di x64.

Selama 12 bulan pertama, **IP publik** (1.500 jam/bulan) dan **disk Premium SSD P6 64 GiB** termasuk
layanan gratis akun ini (Cost Management → *Free services*), jadi yang memakan kredit hanya VM-nya
(asal ukuran disk dipilih 64 GiB/P6, lihat langkah 2). VM gratis di daftar itu (B1s, B2ats v2,
B2pts v2) hanya punya RAM 1 GB -- tidak cukup, backend saja memakai ± 730 MB (model embedding RAG).
Kalau kredit habis, langganan dinonaktifkan (VM berhenti), tidak ditagih. Harga bisa berubah, cek di Azure.

---

## Langkah pertama kali

### 1. Akun Azure for Students

1. Daftar di <https://azure.microsoft.com/free/students> dengan email kampus → kredit $100, 12 bulan.
2. Portal Azure → **Cost Management → Budgets → Add**: budget bulanan **$40** (biaya normal VM ± $31)
   dengan alert di 50%, 80%, 100%, supaya ketahuan kalau kredit terpakai lebih cepat dari perkiraan.

### 2. Buat VM

Portal → **Virtual machines → Create → Azure virtual machine**:

| Bagian | Isian |
|---|---|
| Subscription | Azure for Students |
| Resource group | Create new: `dewai-rg` |
| Virtual machine name | `dewai-vm` |
| Region | **(Asia Pacific) Indonesia Central** (Jakarta; terbukti diizinkan untuk akun pelajar ini & tidak diblokir Groq). Southeast Asia ditolak policy akun pelajar ini. Akun pelajar dibatasi ke beberapa region; kalau ditolak ("RequestDisallowedByAzure"), coba region lain. **Jangan East Asia (Hong Kong)**: API Groq memblokir alamat Hong Kong (403 Forbidden), sehingga chatbot jalan tanpa penjelasan LLM. Cek setelah VM jadi: `curl -s -o /dev/null -w "%{http_code}" https://api.groq.com/openai/v1/models` harus `401` (bukan `403`). |
| Image | **Ubuntu Server 24.04 LTS - x64 Gen2** (wajib 24.04: butuh Python 3.12) |
| Size | **Standard_B2als_v2** (See all sizes → cari B2als; B1ms tidak tersedia untuk akun pelajar ini) |
| Authentication type | **SSH public key**, username `azureuser`, *Generate new key pair*, nama `dewai-key` |
| Public inbound ports | Allow selected ports: **SSH (22), HTTP (80), HTTPS (443)** |
| Disks → OS disk | **Premium SSD (LRS)**, OS disk size **64 GiB (P6)** -- P6 gratis 12 bulan; ukuran bawaan 30 GiB (P4) tidak gratis. Centang *Delete with VM*. |
| Networking | bawaan (VNet & public IP baru); centang *Delete public IP and NIC when VM is deleted* |
| Management → Auto-shutdown | **Off** (kalau on, aplikasi mati tiap malam) |

**Review + create → Create → Download private key and create resource.** Simpan `dewai-key.pem`,
file ini tidak bisa diunduh ulang.

### 3. Nama domain & pengamanan SSH

1. VM → **Overview → DNS name: Not configured** → isi *DNS name label*, mis. `dewai-skincare` → Save.
   Domainmu: `dewai-skincare.<region>.cloudapp.azure.com` (lihat persisnya di Overview). Domain inilah
   yang dipakai untuk HTTPS dan dibagikan ke pengguna.
2. (Disarankan) VM → **Networking → aturan SSH (22) → Source: My IP address** → Save. Kalau nanti
   SSH ditolak karena IP internetmu berubah, perbarui aturan ini.

### 4. Kunci SSH di laptop

```powershell
Move-Item "$HOME\Downloads\dewai-key.pem" "$HOME\.ssh\dewai-key.pem"
# OpenSSH menolak kunci yang bisa dibaca user lain
icacls "$HOME\.ssh\dewai-key.pem" /inheritance:r
icacls "$HOME\.ssh\dewai-key.pem" /grant:r "${env:USERNAME}:R"

$KEY = "$HOME\.ssh\dewai-key.pem"
$SERVER = "azureuser@dewai-skincare.indonesiacentral.cloudapp.azure.com"   # ganti dengan domainmu
ssh -i $KEY $SERVER "lsb_release -d"    # tes: harus menampilkan Ubuntu 24.04
```

### 5. Buat paket & upload

```powershell
.venv\Scripts\python.exe deploy\buat_paket.py      # -> dewai_paket.tar.gz (± 66 MB)
scp -i $KEY dewai_paket.tar.gz "${SERVER}:~"
ssh -i $KEY $SERVER
```

### 6. Pasang di server

Di dalam SSH (ganti domain & email; email opsional, untuk notifikasi sertifikat HTTPS):

```bash
rm -rf ~/dewai && tar xzf ~/dewai_paket.tar.gz -C ~
sudo bash ~/dewai/deploy/setup_server.sh dewai-skincare.indonesiacentral.cloudapp.azure.com emailkamu@contoh.com
```

Pertama kali makan waktu ± 10–15 menit. Di akhir, skrip berhenti dan meminta rahasia diisi dulu.

### 7. Isi rahasia, lalu nyalakan

Rahasia diisi dari laptop lewat pipa SSH ke `deploy/set_env.py` di server, jadi nilainya tidak
pernah tampil di layar atau log (skrip hanya melaporkan panjangnya). `JWT_SECRET` sudah diisi acak
otomatis, jangan diganti.

```powershell
# GROQ_API_KEY: disalin dari .env laptop
.venv\Scripts\python.exe -c "from dotenv import dotenv_values; print('GROQ_API_KEY=' + (dotenv_values('.env').get('GROQ_API_KEY') or ''))" | ssh -i $KEY $SERVER "sudo python3 /opt/dewai/app/deploy/set_env.py"

# akun Admin pertama: email & password ditanyakan, password diketik tersembunyi
powershell -ExecutionPolicy Bypass -File deploy\isi_admin.ps1 -Server $SERVER
```

Password admin: **12–72 karakter dan bukan password laptop**; server ini bisa diakses semua orang.
(Cara manual: `sudo nano /etc/dewai/dewai.env` di server, nilai tanpa tanda kutip.) Lalu di server
jalankan lagi perintah setup yang sama:

```bash
sudo bash ~/dewai/deploy/setup_server.sh dewai-skincare.indonesiacentral.cloudapp.azure.com emailkamu@contoh.com
```

Skrip menunggu backend siap (memuat CBF + model embedding, beberapa menit) lalu menampilkan link-nya.

Database online dimulai **baru**: katalog 961 produk diisi sekali dari `data/products_final.csv`,
akun admin dibuat dari `/etc/dewai/dewai.env`. Akun & riwayat di laptop tidak ikut.

### 8. Uji

- [ ] Di server: `curl -s localhost:8000/health` → `{"status":"ok","cbf_loaded":true,"rag_loaded":true}`
- [ ] Buka `https://<domainmu>` dari laptop (gembok HTTPS tampil)
- [ ] Login admin → Dashboard, User Management, Product Management terbuka
- [ ] Daftar akun baru → isi profil kulit → minta rekomendasi → bandingkan → tanya ulasan
- [ ] Buka dari HP dengan data seluler (bukan WiFi yang sama)

---

## Perawatan

**Update aplikasi** setelah kode berubah di laptop: ulangi langkah 5 dan 6 (buat paket → upload →
jalankan `setup_server.sh` dengan domain yang sama). Database, rahasia, dan cache model tidak
tersentuh; dependency hanya dipasang ulang kalau `requirements-deploy.txt` berubah.

**Status & log** (di server):

```bash
systemctl status dewai-backend dewai-frontend caddy
journalctl -u dewai-backend -f          # log backend langsung (Ctrl+C untuk keluar)
sudo systemctl restart dewai-backend dewai-frontend
```

**Backup database**: otomatis tiap hari ke `/var/backups/dewai/chatbot-YYYY-MM-DD.db` (disimpan 14
hari). Unduh ke laptop:

```powershell
mkdir backup_server -Force
scp -i $KEY "${SERVER}:/var/backups/dewai/chatbot-*.db" backup_server\
```

Backup manual sekarang juga: `sudo /etc/cron.daily/dewai-backup`. Mengembalikan backup:

```bash
sudo systemctl stop dewai-frontend dewai-backend
sudo cp /var/backups/dewai/chatbot-2026-10-20.db /var/lib/dewai/chatbot.db
sudo chown dewai:dewai /var/lib/dewai/chatbot.db
sudo systemctl start dewai-backend dewai-frontend
```

**Hemat kredit**: VM → **Stop** saat tidak dipakai (biaya VM berhenti; disk P6 & IP publik gratis
selama 12 bulan pertama), **Start** lagi saat perlu. Domain tetap sama; aplikasi nyala otomatis setelah VM start.

**Lambat saat banyak pengguna** (mis. sesi kuesioner SUS): VM → **Size → B2as_v2** (8 GB) → Resize (VM restart
beberapa menit, data aman).

**Setelah sidang**: hapus resource group `dewai-rg` supaya tidak ada sisa pemakaian (unduh backup
database dulu).

---

## Catatan teknis

- **Katalog produk ada di database, bukan di CSV.** Saat backend pertama kali nyala dengan database
  baru, tabel `products` diisi dari `data/products_final.csv` (sekali saja). Sesudah itu chatbot
  membaca produk AKTIF dari database, dan perubahan di Product Management langsung dipakai tanpa
  restart. Menjalankan ulang pipeline (CSV baru) TIDAK mengubah katalog database yang sudah terisi,
  supaya perubahan admin tidak tertimpa. Evaluasi CBF tetap memakai CSV.
- **Rate limit per IP asli.** Frontend memanggil backend dari server, jadi tanpa penanganan khusus
  semua pengunjung terlihat ber-IP sama dan berbagi satu jatah (daftar 10×/10 menit). Karena itu
  Caddy mengisi `X-Forwarded-For` dengan IP pengunjung, frontend meneruskannya
  (`frontend/core.py: ip_pengunjung`), dan uvicorn hanya memercayai header itu dari 127.0.0.1
  (`--forwarded-allow-ips`). Pembatas laju disimpan di memori, jadi ter-reset kalau backend restart.
- **Rahasia** hanya ada di `/etc/dewai/dewai.env` (root, chmod 600). `.env` laptop tidak pernah di-upload.
  Kalau `JWT_SECRET` diganti, semua pengguna otomatis ter-logout.
- **Kuota Groq** (tier gratis) dipakai bersama semua pengguna. Kalau kuota harian model utama habis,
  backend pindah ke model cadangan; kalau LLM tidak tersedia sama sekali, chatbot tetap memberi
  rekomendasi dari CBF (skenario uji 7.8).
- **Versi paket** di `requirements-deploy.txt` dikunci sama dengan `.venv` lokal yang lulus seluruh
  skenario uji; kalau paket lokal di-upgrade, samakan juga file itu.
