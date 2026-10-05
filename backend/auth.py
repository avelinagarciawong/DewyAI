"""
auth.py

Hashing password (bcrypt) + JWT (login opsional/wajib) buat backend
chatbot, sesuai "Spesifikasi API": endpoint yang butuh login pakai
header `Authorization: Bearer <jwt_token>`, dan backend TIDAK BOLEH
percaya user_id yang dikirim dari body/query -- selalu ambil dari token
yang sudah diverifikasi tanda tangannya.

SECRET KEY: dibaca dari .env (JWT_SECRET). Kalau belum ada, di-generate
sekali (os.urandom) dan ditulis balik ke .env supaya token yang sudah
diterbitkan tetap valid setelah server di-restart. Tanpa itu, setiap restart
akan membuat semua pengguna ter-logout (401).

CARA PAKAI:
    from auth import hash_password, verify_password, buat_token, get_current_user, get_current_user_opsional, wajib_admin

    # register: hash_password(password) -> disimpan ke DB
    # login: verify_password(password, hash) -> True/False, lalu buat_token(user)
    # endpoint butuh login: def f(user: dict = Depends(get_current_user)): ...
    # endpoint /chat (login opsional): def f(user: dict | None = Depends(get_current_user_opsional)): ...
    # endpoint admin: def f(user: dict = Depends(wajib_admin)): ...
"""
import os
import time
import uuid
from pathlib import Path

import bcrypt
import jwt
from dotenv import load_dotenv, set_key
from fastapi import Depends, Header, HTTPException

import db

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

ALGORITMA = "HS256"
EXPIRE_DETIK = 7 * 24 * 3600  # token berlaku 7 hari
PESAN_NONAKTIF = "Akun kamu dinonaktifkan. Hubungi admin untuk mengaktifkan kembali."
PESAN_SESI_HABIS = "Sesi login kamu sudah berakhir. Silakan login lagi."
PESAN_SESI_TIDAK_VALID = "Sesi login tidak valid. Silakan login lagi."
PESAN_PASSWORD_DIGANTI = ("Sesi login ini sudah diakhiri karena password akun diganti atau akun sempat dinonaktifkan. "
                          "Silakan login lagi.")


def _muat_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        secret = os.urandom(32).hex()
        # ditulis balik ke .env agar tetap sama setelah restart; set_key membuat
        # file .env bila belum ada
        set_key(str(ENV_PATH), "JWT_SECRET", secret)
        os.environ["JWT_SECRET"] = secret
    return secret


SECRET_KEY = _muat_secret()


# ---------- password hashing ----------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # hash rusak/format tidak dikenal, atau password > 72 byte (bcrypt >= 5
        # menolaknya) -- anggap gagal, bukan crash 500
        return False


# dipakai /login untuk email yang tidak terdaftar: bcrypt tetap dijalankan
# supaya lama respons sama dengan email terdaftar (anti user enumeration)
HASH_TIRUAN = hash_password(os.urandom(16).hex())


# ---------- JWT ----------

def buat_token(user: dict) -> str:
    payload = {
        "sub": user["id"],
        "role": user["role"],
        "iat": int(time.time()),
        "exp": int(time.time()) + EXPIRE_DETIK,
        # id unik per sesi: 2 login di detik yang sama (mis. laptop & HP) tetap
        # dapat token berbeda, jadi tiap sesi bisa diakhiri sendiri-sendiri
        "jti": uuid.uuid4().hex,
        # waktu dibuat dalam milidetik -- dibandingkan dengan users.sesi_berlaku_sejak
        # (ganti password mengeluarkan sesi lain, termasuk yang dibuat di detik yang sama)
        "iat_ms": int(time.time() * 1000),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITMA)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITMA])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, PESAN_SESI_HABIS)
    except jwt.InvalidTokenError:
        raise HTTPException(401, PESAN_SESI_TIDAK_VALID)


def _ambil_token_dari_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    bagian = authorization.split()
    if len(bagian) != 2 or bagian[0].lower() != "bearer":
        return None
    return bagian[1]


def payload_sesi(authorization: str | None) -> dict:
    """Isi token yang sah & belum diakhiri (logout). 401 kalau tidak."""
    token = _ambil_token_dari_header(authorization)
    if not token:
        raise HTTPException(401, "Belum login (header Authorization: Bearer <token> tidak ada)")
    payload = _decode_token(token)
    # token lama tanpa jti tidak bisa diakhiri satu per satu -> tidak diterima lagi
    if not payload.get("jti") or db.sesi_dicabut(payload["jti"]):
        raise HTTPException(401, PESAN_SESI_HABIS)
    return payload


def get_current_user(authorization: str = Header(default=None)) -> dict:
    """Dependency buat endpoint yang WAJIB login -- 401 kalau token
    tidak ada/tidak valid/sudah logout/user-nya sudah dihapus/dinonaktifkan."""
    payload = payload_sesi(authorization)
    user = db.cari_user_by_id(payload["sub"])
    if user is None:
        raise HTTPException(401, PESAN_SESI_TIDAK_VALID)
    if not user["is_active"]:
        raise HTTPException(401, PESAN_NONAKTIF)
    if payload.get("iat_ms", payload["iat"] * 1000) < (user.get("sesi_berlaku_sejak") or 0):
        raise HTTPException(401, PESAN_PASSWORD_DIGANTI)
    return user


def get_current_user_opsional(authorization: str = Header(default=None)) -> dict | None:
    """Dependency buat /chat -- login OPSIONAL: tanpa header Authorization =
    tamu (None). TAPI kalau token dikirim dan ternyata kedaluwarsa/tidak valid/
    akunnya dinonaktifkan -> 401, BUKAN diam-diam dijadikan tamu (dulu begitu:
    user mengira masih login padahal riwayatnya tidak tersimpan)."""
    if not _ambil_token_dari_header(authorization):
        return None
    return get_current_user(authorization)


def wajib_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependency buat endpoint /admin/* -- login WAJIB (chaining ke
    get_current_user, jadi 401 duluan kalau belum login sama sekali),
    lalu role harus 'Admin' (403 kalau login tapi bukan admin)."""
    if user["role"] != "Admin":
        raise HTTPException(403, "Akses ditolak")
    return user
