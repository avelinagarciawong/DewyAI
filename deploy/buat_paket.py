"""Bungkus file yang dibutuhkan server menjadi dewai_paket.tar.gz (di root repo).

Jalankan dari root repo:  python deploy/buat_paket.py
Isi: kode backend/frontend/models, aset frontend, tema .streamlit, data/products_final.csv,
data/chroma_db (index RAG), requirements-deploy.txt, dan deploy/. TIDAK ikut: .env (rahasia
diisi langsung di server), database lokal (akun & riwayat di laptop), __pycache__, file cadangan.
Setelah itu upload ke VM -- lihat DEPLOY.md.
"""
import sys
import tarfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HASIL = ROOT / "dewai_paket.tar.gz"
AKAR = "dewai"  # nama folder setelah diekstrak di server: ~/dewai

POLA = [
    "backend/*.py",
    "frontend/*.py",
    "frontend/halaman/*.py",
    "frontend/assets/*",
    "models/*.py",
    ".streamlit/config.toml",
    "data/products_final.csv",
    "data/chroma_db/**/*",
    "requirements-deploy.txt",
    "deploy/*",
]
WAJIB = ["backend/main.py", "frontend/app.py", "data/products_final.csv", "data/chroma_db/chroma.sqlite3",
         "deploy/setup_server.sh"]
# file teks yang dijalankan di Linux: paksa akhir baris LF (git di Windows bisa mengubahnya ke CRLF)
TEKS_LINUX = {".sh", ".service", ".contoh", ""}
BISA_DIEKSEKUSI = {"deploy/setup_server.sh", "deploy/dewai-backup"}


def daftar_file():
    hasil = set()
    for pola in POLA:
        hasil.update(p for p in ROOT.glob(pola) if p.is_file())
    return sorted(p for p in hasil if "__pycache__" not in p.parts and p.suffix not in (".pyc", ".db")
                  and p.name != HASIL.name and "bak" not in p.suffix)


def main():
    kurang = [f for f in WAJIB if not (ROOT / f).exists()]
    if kurang:
        sys.exit(f"File wajib tidak ada: {kurang}")
    files = daftar_file()
    total = 0
    with tarfile.open(HASIL, "w:gz") as tar:
        for p in files:
            rel = p.relative_to(ROOT).as_posix()
            data = p.read_bytes()
            if rel.startswith("deploy/") and (p.suffix in TEKS_LINUX or p.name == "Caddyfile"):
                data = data.replace(b"\r\n", b"\n")
            info = tarfile.TarInfo(f"{AKAR}/{rel}")
            info.size = len(data)
            info.mode = 0o755 if rel in BISA_DIEKSEKUSI else 0o644
            info.mtime = int(p.stat().st_mtime)
            tar.addfile(info, BytesIO(data))
            total += len(data)
    print(f"{HASIL.name}: {len(files)} file, {total / 1e6:.1f} MB sebelum kompresi, "
          f"{HASIL.stat().st_size / 1e6:.1f} MB terkompresi")


if __name__ == "__main__":
    main()
