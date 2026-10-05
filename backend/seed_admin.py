"""
seed_admin.py

Spesifikasi API tidak menyediakan endpoint untuk membuat akun Admin (register
selalu role='User'); admin pertama dibuat manual di awal. Skrip ini menaikkan
pengguna yang sudah terdaftar menjadi Admin, atau membuat akun Admin baru.

CARA PAKAI (dari root repo, venv aktif):
    python backend/seed_admin.py admin@skincare.com "Nama Admin" passwordnya123
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth
import db


def main():
    if len(sys.argv) != 4:
        print("Pakai: python seed_admin.py <email> <nama> <password (min 8 karakter)>")
        sys.exit(1)
    email, nama, password = sys.argv[1].lower(), sys.argv[2], sys.argv[3]
    if len(password) < 8:
        print("Password minimal 8 karakter.")
        sys.exit(1)

    db.init_db()
    ada = db.cari_user_by_email(email)
    if ada:
        conn = db.get_conn()
        conn.execute("UPDATE users SET role='Admin' WHERE id=?", (ada["id"],))
        conn.commit()
        conn.close()
        print(f"User '{email}' (sudah ada) dipromosikan jadi Admin.")
    else:
        db.buat_user(nama, email, auth.hash_password(password), role="Admin")
        print(f"Akun Admin baru '{email}' dibuat.")


if __name__ == "__main__":
    main()
