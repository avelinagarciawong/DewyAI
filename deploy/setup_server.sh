#!/usr/bin/env bash
# setup_server.sh -- pasang / perbarui Dew AI di VM Ubuntu 24.04 (Azure).
#
# Dijalankan DI SERVER dari folder paket yang sudah diekstrak (lihat DEPLOY.md):
#   sudo bash ~/dewai/deploy/setup_server.sh <domain> [email]
#   contoh: sudo bash ~/dewai/deploy/setup_server.sh dewai-skincare.southeastasia.cloudapp.azure.com
#
# Aman dijalankan berulang kali: dipakai juga untuk UPDATE (upload paket baru ->
# jalankan lagi). Database, rahasia (/etc/dewai/dewai.env), dan cache model tidak
# pernah ditimpa.
#
# Susunan di server:
#   /opt/dewai/app         kode + data/chroma_db + data/products_final.csv (milik root)
#   /opt/dewai/venv        virtualenv Python
#   /var/lib/dewai         database SQLite + cache model embedding (milik user "dewai")
#   /var/backups/dewai     backup harian database (grup adm, bisa diunduh admin VM)
#   /etc/dewai/dewai.env   GROQ_API_KEY, JWT_SECRET, akun admin awal (root, chmod 600)
# Backend (127.0.0.1:8000) dan frontend (127.0.0.1:8501) hanya mendengarkan di
# localhost; yang terbuka ke internet hanya Caddy (80/443, HTTPS otomatis).
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP=/opt/dewai/app
VENV=/opt/dewai/venv
DATA=/var/lib/dewai
BACKUP=/var/backups/dewai
ENVF=/etc/dewai/dewai.env
TORCH="torch==2.12.0"
MODEL_EMBED="paraphrase-multilingual-MiniLM-L12-v2"

langkah() { echo; echo "==> $*"; }
gagal() { echo; echo "GAGAL: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || gagal "jalankan dengan sudo: sudo bash $0 <domain> [email]"
[ -n "$DOMAIN" ] || gagal "domain belum diisi. Contoh: sudo bash $0 dewai-skincare.southeastasia.cloudapp.azure.com"
for f in backend/main.py frontend/app.py data/products_final.csv data/chroma_db requirements-deploy.txt; do
    [ -e "$SRC/$f" ] || gagal "$SRC/$f tidak ada -- paket tidak lengkap, buat ulang dengan deploy/buat_paket.py"
done

langkah "Paket sistem (Python, SQLite, Caddy)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -q
apt-get install -y -q python3-venv python3-pip sqlite3 rsync curl gnupg \
    debian-keyring debian-archive-keyring apt-transport-https
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
    || gagal "butuh Python >= 3.12 -- buat VM dengan image Ubuntu Server 24.04 LTS"
if ! command -v caddy >/dev/null; then
    # repo resmi Caddy (https://caddyserver.com/docs/install#debian-ubuntu-raspbian)
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y -q
    apt-get install -y -q caddy
fi

langkah "Swap 2 GB (cadangan kalau RAM penuh saat memuat model)"
if ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
    [ -f /swapfile ] || { fallocate -l 2G /swapfile; chmod 600 /swapfile; mkswap /swapfile >/dev/null; }
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
swapon --show

langkah "User & folder"
id dewai >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --create-home --shell /usr/sbin/nologin dewai
install -d -o dewai -g dewai -m 750 "$DATA" "$DATA/hf"
install -d -o root -g adm -m 750 "$BACKUP"
install -d -o root -g root -m 755 /opt/dewai "$APP"
install -d -o root -g root -m 700 /etc/dewai

langkah "Salin kode & data ke $APP"
systemctl stop dewai-frontend dewai-backend 2>/dev/null || true
rsync -a --delete --chown=root:root "$SRC/" "$APP/"
# chromadb membuka database vektornya dengan mode tulis
chown -R dewai:dewai "$APP/data/chroma_db"

langkah "Virtualenv & dependency Python"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
HASH_REQ="$(sha256sum "$APP/requirements-deploy.txt" | cut -d' ' -f1)"
if [ "$(cat "$VENV/.req.sha256" 2>/dev/null || true)" != "$HASH_REQ" ]; then
    "$VENV/bin/pip" install -q --upgrade pip
    # build CPU dulu: torch dari PyPI di Linux membawa CUDA (~2 GB) yang tidak berguna tanpa GPU
    "$VENV/bin/pip" install -q "$TORCH" --index-url https://download.pytorch.org/whl/cpu
    "$VENV/bin/pip" install -q -r "$APP/requirements-deploy.txt"
    echo "$HASH_REQ" > "$VENV/.req.sha256"
else
    echo "requirements-deploy.txt tidak berubah -- lewati pip install"
fi

langkah "Unduh model embedding RAG ($MODEL_EMBED) ke $DATA/hf"
(cd /tmp && sudo -H -u dewai env HF_HOME="$DATA/hf" "$VENV/bin/python" -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('$MODEL_EMBED')" >/dev/null)

langkah "File rahasia $ENVF"
if [ ! -f "$ENVF" ]; then
    sed "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" "$APP/deploy/dewai.env.contoh" > "$ENVF"
    echo "dibuat baru (JWT_SECRET sudah diisi acak otomatis)"
fi
chown root:root "$ENVF"
chmod 600 "$ENVF"

langkah "Service systemd, Caddy (HTTPS), backup harian"
install -m 644 "$APP/deploy/dewai-backend.service" "$APP/deploy/dewai-frontend.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable dewai-backend dewai-frontend >/dev/null
GLOBAL=""
[ -n "$EMAIL" ] && GLOBAL="{
	email $EMAIL
}
"
{ printf '%s' "$GLOBAL"; sed "s/__DOMAIN__/$DOMAIN/" "$APP/deploy/Caddyfile"; } > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
systemctl enable caddy >/dev/null
systemctl reload-or-restart caddy
install -m 755 "$APP/deploy/dewai-backup" /etc/cron.daily/dewai-backup

# --- isi rahasia wajib sebelum aplikasi dinyalakan ---
nilai() { sed -n "s/^$1=//p" "$ENVF" | tail -n1; }
KURANG=()
[ -n "$(nilai GROQ_API_KEY)" ] || KURANG+=(GROQ_API_KEY)
[ -n "$(nilai ADMIN_EMAIL)" ] || KURANG+=(ADMIN_EMAIL)
PW="$(nilai ADMIN_PASSWORD)"
[ "${#PW}" -ge 8 ] || KURANG+=("ADMIN_PASSWORD (minimal 8 karakter)")
if [ "${#KURANG[@]}" -gt 0 ]; then
    echo
    echo "------------------------------------------------------------------"
    echo "Instalasi selesai, TAPI aplikasi belum dinyalakan karena isian ini"
    echo "masih kosong di $ENVF:"
    printf '  - %s\n' "${KURANG[@]}"
    echo
    echo "Isi dengan:   sudo nano $ENVF"
    echo "Lalu jalankan lagi:   sudo bash $0 $DOMAIN${EMAIL:+ $EMAIL}"
    echo "------------------------------------------------------------------"
    exit 0
fi
[ "${#PW}" -ge 12 ] || echo "PERINGATAN: ADMIN_PASSWORD kurang dari 12 karakter -- server ini bisa diakses semua orang."

langkah "Menyalakan aplikasi"
systemctl restart dewai-backend
echo -n "menunggu backend siap (memuat CBF + model embedding, bisa beberapa menit)"
for _ in $(seq 1 120); do
    if curl -fsS -m 3 http://127.0.0.1:8000/health >/dev/null 2>&1; then break; fi
    systemctl is-active --quiet dewai-backend || { echo; journalctl -u dewai-backend -n 40 --no-pager; gagal "backend mati saat startup (log di atas)"; }
    echo -n "."; sleep 5
done
echo
curl -fsS -m 3 http://127.0.0.1:8000/health || { journalctl -u dewai-backend -n 40 --no-pager; gagal "backend belum siap dalam 10 menit"; }
echo
systemctl restart dewai-frontend
sleep 5
systemctl is-active --quiet dewai-frontend || { journalctl -u dewai-frontend -n 40 --no-pager; gagal "frontend gagal menyala"; }

echo
echo "=================================================================="
echo " Dew AI jalan:  https://$DOMAIN"
echo " (sertifikat HTTPS diambil otomatis oleh Caddy; kalau baru pertama"
echo "  kali, tunggu ~1 menit. Pastikan port 80 & 443 dibuka di Azure.)"
echo " Status:  systemctl status dewai-backend dewai-frontend caddy"
echo " Log:     journalctl -u dewai-backend -f"
echo "=================================================================="
