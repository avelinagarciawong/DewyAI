"""
main.py

Backend FastAPI chatbot Dew AI, mengikuti dokumen Spesifikasi API (endpoint dan
status code harus sesuai dokumen tersebut).

Ringkasan perilaku:
  - /chat dapat dipakai tanpa login. Percakapan tamu tidak disimpan ke riwayat
    (riwayat tamu hanya ada di session state frontend).
  - Autentikasi memakai JWT (Authorization: Bearer <token>). Identitas pengguna
    selalu diambil dari token yang sudah divalidasi, tidak pernah dari user_id
    yang dikirim klien (lihat auth.py).
  - Akun memakai email dan nama, dengan peran User atau Admin.
  - Respons /chat terstruktur {recommendation, explanation} (lihat models/percakapan.py).

Tambahan terhadap spesifikasi:
  1. Request /chat menerima `conversation_id` opsional agar pesan pengguna yang
     login tersambung ke percakapan yang sama. Tanpa field ini pesan dianggap
     percakapan baru, sehingga tetap kompatibel dengan spesifikasi.
  2. Respons /login menyertakan tipe_kulit, masalah_kulit, dan budget pada field
     `user`, karena tidak ada endpoint GET /profile untuk mengisi ulang form
     onboarding. Penambahan ini tidak mengubah field yang sudah didokumentasikan.
  3. Pesan bot yang disimpan ke riwayat hanya teks `explanation`, sesuai contoh
     respons GET /history.
  4. Pengelolaan katalog per produk: GET/POST /admin/products, GET/PUT
     /admin/products/{id}, PUT /admin/products/{id}/status, GET /admin/ringkasan,
     dan GET /admin/opsi-produk. GET /admin/users memakai paginasi (q, halaman,
     per_halaman) dengan field total; key "users" tetap ada.

Cara menjalankan (dari root repo):
    uvicorn backend.main:app --reload --port 8000
"""
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)  # cbf_engine/rag_retrieve pakai path relatif ("data/...")
sys.path.insert(0, str(PROJECT_ROOT / "models"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # supaya "import db"/"import auth" ketemu

from cbf_engine import CBFEngine, TIPE_KULIT_VALID, MASALAH_KULIT_VALID  # noqa: E402
from rag_retrieve import RAGRetriever  # noqa: E402
from generate_jawaban import GeneratorJawaban  # noqa: E402
from percakapan import Percakapan  # noqa: E402

import auth  # noqa: E402
import db  # noqa: E402
import pembatas  # noqa: E402
import produk  # noqa: E402
from email_validator import EmailNotValidError, validate_email  # noqa: E402

mesin = {}  # cbf/rag/generator, dibikin sekali di lifespan startup
PANJANG_PESAN_MAKS = 2000
# dataset hasil pipeline -- dipakai SEKALI untuk mengisi tabel products di database baru
PRODUK_CSV = os.getenv("PRODUK_CSV", "data/products_final.csv")
# perubahan katalog oleh admin dijalankan satu per satu (tulis database + fit ulang index)
_kunci_katalog = threading.Lock()


def _seed_admin_dari_env():
    """Membuat akun Admin saat startup bila ADMIN_EMAIL/ADMIN_PASSWORD/ADMIN_NAMA
    di-set dan email tersebut belum terdaftar, sehingga server tidak perlu diakses
    lewat shell untuk menjalankan backend/seed_admin.py. Aman dipanggil berulang
    (restart/redeploy): tidak melakukan apa-apa bila email sudah ada."""
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    nama = os.getenv("ADMIN_NAMA", "Admin")
    if not email or not password:
        return
    # aturan yang sama dengan form login -- email yang ditolak login (mis. domain
    # ".test") akan menghasilkan akun admin yang tidak pernah bisa dipakai masuk
    try:
        email = cek_email(email)
    except ValueError as e:
        print(f"[startup] ADMIN_EMAIL '{email}' tidak valid ({e}), admin TIDAK dibuat.")
        return
    if db.cari_user_by_email(email):
        return
    if len(password) < 8:
        print(f"[startup] ADMIN_PASSWORD kurang dari 8 karakter, admin '{email}' TIDAK dibuat.")
        return
    db.buat_user(nama, email, auth.hash_password(password), role="Admin")
    print(f"[startup] Akun Admin '{email}' dibuat otomatis dari env var.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[startup] Memuat CBFEngine, RAGRetriever, GeneratorJawaban ...")
    db.init_db()
    _seed_admin_dari_env()
    n = db.seed_produk_dari_csv(PRODUK_CSV)
    if n:
        print(f"[startup] Tabel products diisi {n} produk dari {PRODUK_CSV}.")
    # katalog chatbot = produk AKTIF di database (bukan CSV), supaya perubahan admin ikut terpakai
    mesin["cbf"] = CBFEngine(df=db.produk_df())
    # MODE_RINGAN=1: tanpa RAG & LLM (CBF saja) -- startup cepat & tidak memakai
    # kuota Groq, dipakai tes autentikasi (tests/uji_login_register.py)
    ringan = os.getenv("MODE_RINGAN") == "1"
    # RAG & LLM boleh gagal dimuat -- chat tetap jalan pakai CBF saja
    # (tanpa kutipan ulasan / pakai penjelasan otomatis), bukan ikut mati.
    mesin["rag"] = mesin["generator"] = None
    if ringan:
        print("[startup] MODE_RINGAN aktif: RAG & LLM tidak dimuat.")
    else:
        try:
            mesin["rag"] = RAGRetriever()
        except Exception as e:
            print(f"[startup] RAG tidak tersedia, lanjut tanpa kutipan ulasan: {type(e).__name__}: {e}")
        try:
            mesin["generator"] = GeneratorJawaban(mesin["cbf"], mesin["rag"])
        except Exception as e:
            print(f"[startup] LLM tidak tersedia, lanjut pakai penjelasan otomatis: {type(e).__name__}: {e}")
    mesin["percakapan"] = Percakapan(mesin["cbf"], mesin["generator"], mesin["rag"])
    print("[startup] Selesai, siap menerima request.")
    yield
    mesin.clear()


app = FastAPI(title="Chatbot Skincare API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# WAJIB_HTTPS=1 (di-set saat deploy): request dari luar yang lewat HTTP polos
# ditolak, supaya email/password/token tidak pernah terkirim tanpa enkripsi.
# HTTPS-nya sendiri disediakan reverse proxy (Caddy di server, lihat DEPLOY.md), yang
# meneruskan protokol aslinya lewat header X-Forwarded-Proto. Localhost dikecualikan
# (pengembangan & pengujian lokal, dan frontend yang memanggil backend di mesin yang sama).
WAJIB_HTTPS = os.getenv("WAJIB_HTTPS") == "1"
_HOST_LOKAL = {"localhost", "127.0.0.1", "[::1]"}


@app.middleware("http")
async def paksa_https(request: Request, call_next):
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if WAJIB_HTTPS and proto != "https" and host not in _HOST_LOKAL:
        return JSONResponse(status_code=400, content={"detail": "Koneksi wajib lewat HTTPS."})
    resp = await call_next(request)
    if proto == "https":
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


@app.exception_handler(RequestValidationError)
async def handler_validasi(request: Request, exc: RequestValidationError):
    """Spesifikasi meminta status 400 untuk input tidak valid, sedangkan FastAPI
    mengembalikan 422 untuk error validasi pydantic. Status diseragamkan ke 400,
    dengan pesan dari error pertama."""
    # Semua field yang bermasalah dilaporkan agar form dapat menandai tiap field;
    # "detail" tetap berupa satu string untuk klien lama
    # halaman admin & ganti password (Profile) berbahasa Inggris; login/register/chat berbahasa Indonesia
    en = request.url.path.startswith("/admin") or request.url.path == "/change-password"
    per_field = {}
    for err in exc.errors():
        field = ".".join(str(x) for x in err["loc"][1:]) or "body"  # loc[0] == 'body'
        if err["type"] == "missing":
            msg = "is required" if en else "wajib diisi"
        elif err["type"] in ("string_type", "int_type", "bool_type", "list_type", "dict_type", "model_type",
                             "model_attributes_type", "json_invalid", "int_parsing"):
            msg = "invalid format" if en else "format isiannya tidak sesuai"
        elif err["type"] in ("greater_than_equal", "less_than_equal"):
            msg = "value is out of the allowed range" if en else "nilainya di luar batas yang diizinkan"
        else:
            msg = err["msg"].removeprefix("Value error, ")
        per_field.setdefault(field, msg)
    pesan = "; ".join(f"{f}: {m}" if f != "body" else m for f, m in per_field.items())
    return JSONResponse(status_code=400, content={"detail": pesan, "errors": per_field})


# ---------- skema request ----------

PASSWORD_MIN = 8
PASSWORD_MAKS_BYTE = 72  # batas bcrypt (bcrypt >= 5 menolak password lebih panjang -> dulu jadi error 500)
NAMA_MAKS = 100


def cek_email(v):
    """Format email divalidasi di backend, tidak hanya di form -- "user@",
    "usergmail.com", "user @gmail.com" ditolak. Disimpan huruf kecil supaya
    login tidak peka huruf besar/kecil."""
    v = (v or "").strip()
    if not v:
        raise ValueError("Email wajib diisi.")
    try:
        validate_email(v, check_deliverability=False)
    except EmailNotValidError:
        raise ValueError("Format email tidak valid (contoh: nama@gmail.com).")
    return v.lower()


def cek_password_baru(v):
    if not v:
        raise ValueError("Password wajib diisi.")
    if len(v) < PASSWORD_MIN:
        raise ValueError(f"Password minimal {PASSWORD_MIN} karakter.")
    if len(v.encode("utf-8")) > PASSWORD_MAKS_BYTE:
        raise ValueError(f"Password maksimal {PASSWORD_MAKS_BYTE} karakter.")
    if not v.strip():
        raise ValueError("Password tidak boleh hanya berisi spasi.")
    return v


class RegisterRequest(BaseModel):
    # field lain yang dikirim klien (mis. role="admin") DIABAIKAN pydantic --
    # akun dari /register selalu role User (skenario 1.11)
    nama: str
    email: str
    password: str

    @field_validator("nama")
    @classmethod
    def _cek_nama(cls, v):
        v = " ".join(v.split())
        if not v:
            raise ValueError("Nama wajib diisi.")
        if len(v) > NAMA_MAKS:
            raise ValueError(f"Nama maksimal {NAMA_MAKS} karakter.")
        return v

    @field_validator("email")
    @classmethod
    def _cek_email(cls, v):
        return cek_email(v)

    @field_validator("password")
    @classmethod
    def _cek_password(cls, v):
        return cek_password_baru(v)


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _cek_email(cls, v):
        return cek_email(v)

    @field_validator("password")
    @classmethod
    def _cek_password(cls, v):
        if not v:
            raise ValueError("Password wajib diisi.")
        return v


class ChangePasswordRequest(BaseModel):
    password_lama: str
    password_baru: str

    # pesan bahasa Inggris (halaman Profile); syaratnya sama dengan register
    @field_validator("password_lama")
    @classmethod
    def _cek_lama(cls, v):
        if not v:
            raise ValueError("Current password is required.")
        return v

    @field_validator("password_baru")
    @classmethod
    def _cek_baru(cls, v, info):
        if not v:
            raise ValueError("New password is required.")
        if len(v) < PASSWORD_MIN:
            raise ValueError(f"Password must be at least {PASSWORD_MIN} characters.")
        if len(v.encode("utf-8")) > PASSWORD_MAKS_BYTE:
            raise ValueError(f"Password can be at most {PASSWORD_MAKS_BYTE} characters.")
        if not v.strip():
            raise ValueError("Password can't contain only spaces.")
        if v == info.data.get("password_lama"):
            raise ValueError("New password can't be the same as your current password.")
        return v


class ProfilKulit(BaseModel):
    """Aturan yang sama persis dengan form onboarding: tipe kulit, masalah
    kulit (minimal 1), dan budget SEMUANYA wajib. Divalidasi ulang di backend
    karena request bisa dikirim langsung tanpa lewat form."""
    tipe_kulit: str
    masalah_kulit: List[str]
    budget: Optional[int] = None
    tanpa_batas_budget: bool = False

    @field_validator("tipe_kulit")
    @classmethod
    def _cek_tipe(cls, v):
        if v not in TIPE_KULIT_VALID:
            raise ValueError(f"tipe kulit wajib dipilih salah satu dari {sorted(TIPE_KULIT_VALID)}")
        return v

    @field_validator("masalah_kulit", mode="before")
    @classmethod
    def _cek_masalah(cls, v):
        if isinstance(v, str):
            v = [v] if v else []
        if not v:
            raise ValueError("masalah kulit wajib dipilih minimal 1")
        salah = [m for m in v if m not in MASALAH_KULIT_VALID]
        if salah:
            raise ValueError(f"masalah kulit {salah} tidak dikenal. Pilihan: {sorted(MASALAH_KULIT_VALID)}")
        return list(dict.fromkeys(v))

    @field_validator("budget")
    @classmethod
    def _cek_budget(cls, v):
        if v is not None and v <= 0:
            raise ValueError("budget harus angka lebih dari 0")
        return v

    @model_validator(mode="after")
    def _budget_wajib(self):
        if self.tanpa_batas_budget:
            self.budget = None
        elif self.budget is None:
            raise ValueError("budget wajib diisi (angka lebih dari 0), atau pilih tanpa batas budget")
        return self


class ChatRequest(BaseModel):
    message: str
    onboarding: ProfilKulit
    konteks: Optional[dict] = None  # ingatan percakapan, lihat models/percakapan.py
    conversation_id: Optional[str] = None  # deviasi #1, lihat docstring atas

    @field_validator("message")
    @classmethod
    def _cek_pesan(cls, v):
        # pesan berisi spasi/emoji saja TETAP diterima -- dijawab minta klarifikasi
        # oleh Percakapan, bukan ditolak
        if not v:
            raise ValueError("Pesan tidak boleh kosong.")
        if len(v) > PANJANG_PESAN_MAKS:
            raise ValueError(f"Pesan terlalu panjang (maksimal {PANJANG_PESAN_MAKS} karakter). Coba dipersingkat ya.")
        return v


class AdminSetActiveRequest(BaseModel):
    is_active: bool


# ---------- helper ----------

def _validasi_tipe_masalah(tipe_kulit: Optional[str], masalah_kulit: Optional[str]):
    if tipe_kulit is not None and tipe_kulit not in TIPE_KULIT_VALID:
        raise HTTPException(400, f"tipe_kulit '{tipe_kulit}' tidak dikenal. Pilihan: {sorted(TIPE_KULIT_VALID)}")
    if masalah_kulit is not None and masalah_kulit not in MASALAH_KULIT_VALID:
        raise HTTPException(400, f"masalah_kulit '{masalah_kulit}' tidak dikenal. Pilihan: {sorted(MASALAH_KULIT_VALID)}")


def _bersihkan_nan(v):
    if isinstance(v, float) and v != v:
        return None
    return v


def _produk_ke_json(hasil_df) -> list:
    """Lihat catatan yang sama di versi sebelumnya: df.where(notnull, None)
    TIDAK cukup buat kolom float64 (pandas balikin ke NaN lagi), jadi
    dibersihkan SETELAH to_dict()."""
    return [{k: _bersihkan_nan(v) for k, v in row.items()} for row in hasil_df.to_dict(orient="records")]


# ---------- /register, /login, /change-password ----------

def batasi_register(request: Request):
    """Dijalankan SEBELUM isi request divalidasi, jadi percobaan dengan data
    tidak valid pun ikut dihitung (bot yang asal kirim tetap kena batas)."""
    tunggu = pembatas.BATAS_REGISTER.coba(request.client.host if request.client else "?")
    if tunggu:
        raise HTTPException(429, f"Terlalu banyak percobaan daftar dari perangkat ini. Coba lagi dalam "
                                 f"{pembatas.teks_tunggu(tunggu)}.", headers={"Retry-After": str(tunggu)})


@app.post("/register", status_code=201, dependencies=[Depends(batasi_register)])
def register(req: RegisterRequest):
    try:
        user = db.buat_user(req.nama, req.email, auth.hash_password(req.password))
    except ValueError:
        raise HTTPException(409, "Email sudah terdaftar. Silakan login dengan email ini.")
    except Exception:
        raise HTTPException(500, "Pendaftaran gagal, coba kembali")
    return {"id": user["id"], "nama": user["nama"], "email": user["email"]}


PESAN_LOGIN_GAGAL = "Email atau kata sandi salah."


@app.post("/login")
def login(req: LoginRequest, request: Request):
    # dikunci per (IP, email) setelah beberapa kali gagal -- berlaku sama untuk
    # email yang terdaftar maupun tidak, jadi tidak membocorkan email mana yang ada
    kunci = (request.client.host if request.client else "?", req.email)
    tunggu = pembatas.BATAS_LOGIN_GAGAL.sisa_tunggu(kunci)
    if tunggu:
        raise HTTPException(429, f"Terlalu banyak percobaan login yang gagal. Coba lagi dalam "
                                 f"{pembatas.teks_tunggu(tunggu)}.", headers={"Retry-After": str(tunggu)})
    user = db.cari_user_by_email(req.email)
    # email tidak terdaftar tetap menjalankan bcrypt (hash tiruan), supaya lama
    # respons tidak bisa dipakai menebak email mana yang punya akun
    cocok = auth.verify_password(req.password, user["password_hash"] if user else auth.HASH_TIRUAN)
    if user is None or not cocok:
        pembatas.BATAS_LOGIN_GAGAL.catat(kunci)
        raise HTTPException(401, PESAN_LOGIN_GAGAL)
    pembatas.BATAS_LOGIN_GAGAL.reset(kunci)
    # pesan khusus ini baru muncul SETELAH password terbukti benar -- ditujukan ke
    # pemilik akun, bukan ke orang yang sedang menebak-nebak email
    if not user["is_active"]:
        raise HTTPException(401, auth.PESAN_NONAKTIF)
    try:
        token = auth.buat_token(user)
    except Exception:
        raise HTTPException(500, "Sistem sedang bermasalah, coba lagi")

    profil = db.ambil_profil(user["id"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "nama": user["nama"],
            "role": user["role"],
            # deviasi #2 (aditif) -- lihat docstring atas
            "tipe_kulit": profil["tipe_kulit"],
            "masalah_kulit": profil["masalah_kulit"],
            # budget NULL (atau 0, data lama) di profil yang sudah terisi = user
            # memilih "Tidak ada batas budget"
            "budget": profil["budget_max"] or None,
            "tanpa_batas_budget": bool(profil["tipe_kulit"]) and not profil["budget_max"],
        },
    }


@app.post("/logout")
def logout(authorization: str = Header(default=None)):
    """Mengakhiri sesi INI saja (token ini dicatat sebagai dicabut); sesi di
    device lain tetap jalan -- sesuai kebijakan "boleh login di 2 device"."""
    payload = auth.payload_sesi(authorization)
    db.cabut_sesi(payload["jti"], payload["sub"], payload["exp"])
    return {"message": "Berhasil logout"}


@app.put("/change-password")
def change_password(req: ChangePasswordRequest, user: dict = Depends(auth.get_current_user)):
    if not auth.verify_password(req.password_lama, user["password_hash"]):
        raise HTTPException(401, "Current password is incorrect.")
    # kebijakan: sesi yang sedang dipakai tetap jalan (dapat token baru), sesi di
    # device lain dikeluarkan (token yang dibuat sebelum saat ini ditolak)
    db.ubah_password(user["id"], auth.hash_password(req.password_baru), int(time.time() * 1000))
    return {"message": "Password changed. You've been signed out on your other devices.",
            "access_token": auth.buat_token(user)}


# ---------- /chat ----------

@app.post("/chat")
def chat(req: ChatRequest, user: Optional[dict] = Depends(auth.get_current_user_opsional)):
    # tidak ada lagi 503 kalau LLM gagal -- Percakapan jatuh ke penjelasan otomatis
    hasil = mesin["percakapan"].proses(req.message, req.konteks, req.onboarding.model_dump())

    # guest (tanpa token) -- TIDAK menyentuh conversations/messages sama sekali,
    # sesuai keputusan desain di spek.
    if user is not None:
        conversation_id = req.conversation_id
        if conversation_id is None:
            judul = req.message[:50] + ("..." if len(req.message) > 50 else "")
            conversation_id = db.buat_percakapan(user["id"], judul=judul)
        elif not db.milik_user(conversation_id, user["id"]):
            raise HTTPException(403, "conversation_id itu bukan milik akun ini.")

        db.simpan_pesan(conversation_id, "user", req.message)
        # teks tetap di "content" (sesuai spek), kartu produk/tabel ikut disimpan
        # di "data" supaya riwayat yang dibuka lagi tampil utuh
        db.simpan_pesan(conversation_id, "bot", hasil["explanation"],
                        data={k: hasil.get(k) for k in ("recommendation", "grup", "perbandingan")})
        db.simpan_konteks(conversation_id, hasil["konteks"])
        hasil = {**hasil, "conversation_id": conversation_id}

    return hasil


# ---------- /history, /profile ----------

@app.get("/history")
def history(user: dict = Depends(auth.get_current_user)):
    percakapan = db.ambil_percakapan_lengkap_user(user["id"])
    _tandai_produk_tidak_tersedia(percakapan)
    return {"conversations": percakapan}


def _tandai_produk_tidak_tersedia(percakapan):
    """Riwayat lama tetap menampilkan kartu produk apa adanya (catatan
    historis), tapi produk yang SEKARANG sudah nonaktif/tidak ada di katalog
    diberi tidak_tersedia=True -> frontend memberi label, supaya user tidak
    mengira produk itu masih direkomendasikan (keputusan skenario admin 6.3)."""
    kartu = []
    for c in percakapan:
        for m in c["messages"]:
            data = m.get("data") if isinstance(m.get("data"), dict) else {}
            kartu += data.get("recommendation") or []
            for g in data.get("grup") or []:
                kartu += (g.get("produk") or []) if isinstance(g, dict) else []
    kartu = [p for p in kartu if isinstance(p, dict) and isinstance(p.get("id"), str)]
    aktif = db.id_produk_aktif(p["id"] for p in kartu)
    for p in kartu:
        p["tidak_tersedia"] = p["id"] not in aktif


class PesanImpor(BaseModel):
    sender: str
    content: str
    data: Optional[dict] = None

    @field_validator("sender")
    @classmethod
    def _cek_sender(cls, v):
        if v not in db.PERAN_VALID:
            raise ValueError("sender harus 'user' atau 'bot'.")
        return v

    @field_validator("content")
    @classmethod
    def _cek_isi(cls, v):
        if not v.strip():
            raise ValueError("Isi pesan tidak boleh kosong.")
        if len(v) > 20000:
            raise ValueError("Isi pesan terlalu panjang.")
        return v


class ImporPercakapan(BaseModel):
    messages: List[PesanImpor]
    konteks: Optional[dict] = None

    @field_validator("messages")
    @classmethod
    def _cek_jumlah(cls, v):
        if not 1 <= len(v) <= 200:
            raise ValueError("Jumlah pesan harus 1-200.")
        return v


@app.post("/history/import", status_code=201)
def impor_percakapan(req: ImporPercakapan, user: dict = Depends(auth.get_current_user)):
    """Tamu yang login/daftar di tengah chat: percakapan yang sedang terbuka
    disimpan ke riwayat akunnya (keputusan skenario 6.3), lalu dilanjutkan
    dengan conversation_id yang dikembalikan. Hanya menulis ke akun pemilik token."""
    pertama = next((m.content for m in req.messages if m.sender == "user"), req.messages[0].content)
    judul = pertama[:50] + ("..." if len(pertama) > 50 else "")
    conversation_id = db.buat_percakapan(user["id"], judul=judul)
    for m in req.messages:
        db.simpan_pesan(conversation_id, m.sender, m.content, data=m.data)
    if req.konteks:  # divalidasi ulang oleh Percakapan setiap kali dipakai
        db.simpan_konteks(conversation_id, req.konteks)
    return {"conversation_id": conversation_id}


@app.put("/profile")
def profile(req: ProfilKulit, user: dict = Depends(auth.get_current_user)):
    db.simpan_profil(
        user["id"],
        tipe_kulit=req.tipe_kulit,
        masalah_kulit=req.masalah_kulit,
        budget_max=req.budget,
        tanpa_batas_budget=req.tanpa_batas_budget,
    )
    return {"message": "Profil berhasil diperbarui"}


# ---------- /rekomendasi (CBF saja, tanpa LLM; tambahan di luar spesifikasi untuk
# daftar produk yang cocok tanpa menunggu LLM setiap kali filter diganti) ----------

@app.get("/rekomendasi")
def rekomendasi(tipe_kulit: str, masalah_kulit: str, budget: Optional[int] = None, top_n: int = 10):
    _validasi_tipe_masalah(tipe_kulit, masalah_kulit)
    hasil = mesin["cbf"].recommend(
        tipe_kulit=tipe_kulit, masalah_kulit=[masalah_kulit], budget_max=budget, top_n=top_n,
    )
    return {"jumlah": len(hasil), "produk": _produk_ke_json(hasil)}


# ---------- /admin/* ----------

PER_HALAMAN_MAKS = 100


def _info_halaman(total, halaman, per_halaman):
    return {"total": total, "halaman": halaman, "per_halaman": per_halaman,
            "jumlah_halaman": max(1, -(-total // per_halaman))}


@app.get("/admin/ringkasan")
def admin_ringkasan(_admin: dict = Depends(auth.wajib_admin)):
    """Blok ringkasan di atas tabel User Management (juga dipakai Dashboard)."""
    return db.ringkasan()


@app.get("/admin/users")
def admin_list_users(q: Optional[str] = None, halaman: int = Query(1, ge=1),
                     per_halaman: int = Query(20, ge=1, le=PER_HALAMAN_MAKS),
                     _admin: dict = Depends(auth.wajib_admin)):
    """Per halaman + total, supaya tabel tidak menumpuk semua akun di 1 halaman
    dan tidak ada yang terpotong diam-diam. q: cari nama/email."""
    users, total = db.cari_user(q, halaman, per_halaman)
    return {"users": users, **_info_halaman(total, halaman, per_halaman)}


@app.put("/admin/users/{user_id}")
def admin_set_user_active(user_id: str, req: AdminSetActiveRequest, admin: dict = Depends(auth.wajib_admin)):
    # admin yang menonaktifkan dirinya sendiri langsung terkunci dari aplikasi
    # (semua request berikutnya 401) -- ditolak dengan pesan jelas
    if user_id == admin["id"] and not req.is_active:
        raise HTTPException(400, "You can't deactivate your own account.")
    # admin boleh menonaktifkan admin lain, asal tetap tersisa minimal 1 admin aktif
    hasil = db.set_status_aktif(user_id, req.is_active)
    if hasil == "tidak_ada":
        raise HTTPException(404, "User not found.")
    if hasil == "admin_terakhir":
        raise HTTPException(400, "This is the last active admin — at least one admin must stay active.")
    # akun yang dinonaktifkan langsung terputus sesinya: setiap request dicek
    # is_active-nya (auth.get_current_user), tidak menunggu token kedaluwarsa
    return {"message": "User status updated."}


# ---------- /admin/products (katalog chatbot) ----------

PESAN_PRODUK_HILANG = "Product not found — it may no longer exist. Reload the product list."


class StatusProdukRequest(BaseModel):
    is_active: bool


def _segarkan_katalog():
    """Dipanggil SETELAH setiap perubahan katalog (di dalam _kunci_katalog):
    index TF-IDF di-fit ulang dari produk aktif di database, dan Percakapan
    dibuat ulang (indeks nama produk/merek-nya ikut baru). Chat berikutnya
    langsung memakai katalog baru, tanpa menunggu restart. Chat yang sedang diproses selesai dengan
    versi lama yang utuh."""
    mesin["cbf"].muat_ulang(db.produk_df())
    mesin["percakapan"] = Percakapan(mesin["cbf"], mesin["generator"], mesin["rag"])


@app.get("/admin/opsi-produk")
def admin_opsi_produk(_admin: dict = Depends(auth.wajib_admin)):
    """Pilihan baku untuk dropdown/checkbox form produk -- satu sumber dengan
    validasi backend, jadi form tidak pernah menawarkan nilai yang ditolak."""
    return {"kategori": {k: produk.nlu.LABEL_KATEGORI.get(k, k) for k in produk.KATEGORI_VALID},
            "tipe_kulit": list(produk.URUTAN_TIPE), "masalah_kulit": list(produk.URUTAN_MASALAH)}


@app.get("/admin/products")
def admin_list_products(q: Optional[str] = None, kategori: Optional[str] = None, tipe_kulit: Optional[str] = None,
                        status: str = "semua", halaman: int = Query(1, ge=1),
                        per_halaman: int = Query(20, ge=1, le=PER_HALAMAN_MAKS),
                        _admin: dict = Depends(auth.wajib_admin)):
    """Filter digabung (AND); q: cari di nama/brand, tidak peka huruf besar/kecil."""
    if kategori and kategori not in produk.KATEGORI_VALID:
        raise HTTPException(400, f"Unknown category '{kategori}'. Options: {', '.join(produk.KATEGORI_VALID)}")
    if tipe_kulit and tipe_kulit not in TIPE_KULIT_VALID:
        raise HTTPException(400, f"Unknown skin type '{tipe_kulit}'. Options: {', '.join(produk.URUTAN_TIPE)}")
    if status not in ("semua", "aktif", "nonaktif"):
        raise HTTPException(400, "status must be 'semua', 'aktif', or 'nonaktif'.")
    daftar, total = db.cari_produk(q, kategori or None, tipe_kulit or None, status, halaman, per_halaman)
    return {"produk": [produk.ke_json(p) for p in daftar], **_info_halaman(total, halaman, per_halaman)}


@app.get("/admin/products/{produk_id}")
def admin_detail_produk(produk_id: str, _admin: dict = Depends(auth.wajib_admin)):
    p = db.ambil_produk(produk_id)
    if p is None:
        raise HTTPException(404, PESAN_PRODUK_HILANG)
    return produk.ke_json(p)


@app.post("/admin/products", status_code=201)
def admin_tambah_produk(req: produk.ProdukBaru, _admin: dict = Depends(auth.wajib_admin)):
    with _kunci_katalog:
        p = db.buat_produk(req.ke_baris())
        _segarkan_katalog()
    return {"message": "Product added and is now used by the chatbot.", "produk": produk.ke_json(p)}


@app.put("/admin/products/{produk_id}")
def admin_ubah_produk(produk_id: str, req: produk.ProdukUbah, _admin: dict = Depends(auth.wajib_admin)):
    """Hanya field yang dikirim yang diubah. versi = versi produk waktu form
    edit dibuka: kalau sementara itu produknya sudah diubah/dinonaktifkan
    admin lain, perubahan DITOLAK (409), tidak menimpa diam-diam."""
    with _kunci_katalog:
        lama = db.ambil_produk(produk_id)
        if lama is None:
            raise HTTPException(404, PESAN_PRODUK_HILANG)
        if lama["versi"] != req.versi:
            sebab = "deactivated" if not lama["is_active"] else "changed"
            raise HTTPException(409, f"This product was {sebab} by another admin after you opened it. Your changes "
                                     "were NOT saved so they don't overwrite theirs — reload the product data and try "
                                     "again.")
        ubah, pesan_sinyal = req.perubahan(lama)
        if pesan_sinyal:
            return JSONResponse(status_code=400, content={"detail": pesan_sinyal,
                                                          "errors": {"sinyal_rekomendasi": pesan_sinyal}})
        if not ubah:
            return {"message": "There are no changes to save.", "produk": produk.ke_json(lama), "diubah": []}
        status, p = db.ubah_produk(produk_id, ubah, req.versi)
        if status != "ok":  # tidak terjadi selama semua penulisan lewat _kunci_katalog, tapi tetap dijaga
            raise HTTPException(404 if status == "tidak_ada" else 409,
                                PESAN_PRODUK_HILANG if status == "tidak_ada" else
                                "This product was changed by another admin.")
        _segarkan_katalog()
    return {"message": "Product updated and is now used by the chatbot.", "produk": produk.ke_json(p),
            "diubah": sorted(ubah)}


@app.put("/admin/products/{produk_id}/status")
def admin_status_produk(produk_id: str, req: StatusProdukRequest, _admin: dict = Depends(auth.wajib_admin)):
    """Nonaktifkan = produk tidak pernah direkomendasikan lagi, TAPI datanya
    tetap di database (bisa diaktifkan kembali). Tidak ada hapus permanen."""
    with _kunci_katalog:
        p = db.set_status_produk(produk_id, req.is_active)
        if p is None:
            raise HTTPException(404, PESAN_PRODUK_HILANG)
        _segarkan_katalog()
    pesan = ("Product activated again and can be recommended." if req.is_active else
             "Product deactivated (its data is kept) and will no longer be recommended.")
    return {"message": pesan, "produk": produk.ke_json(p)}


@app.get("/health")
def health():
    return {"status": "ok", "cbf_loaded": "cbf" in mesin, "rag_loaded": "rag" in mesin}
