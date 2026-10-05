"""
uji_login_register.py -- pengujian otomatis dokumen "Skenario Pengujian
Login & Registrasi Chatbot Rekomendasi Skincare". Tiap skenario dicetak
PASS/FAIL beserta buktinya (untuk Bab IV).

Skrip ini menyalakan BACKEND SENDIRI (port 8010) dengan database sementara
dan MODE_RINGAN (tanpa RAG/LLM): akun-akun uji tidak mengotori
backend/chatbot.db, state rate limit selalu mulai dari nol, dan tidak
memakai kuota Groq. Konfigurasi rate limit = default produksi.
Form Streamlit diuji pakai streamlit.testing (AppTest) yang diarahkan ke
backend uji ini.

CARA PAKAI (dari root project):
    python tests/uji_login_register.py            # semua bagian
    python tests/uji_login_register.py --bagian 1  # bagian tertentu
"""
import argparse
import atexit
import http.client
import itertools
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8010
BACKEND_URL = f"http://127.0.0.1:{PORT}"
os.environ["BACKEND_URL"] = BACKEND_URL  # dibaca frontend/core.py saat diimpor AppTest
TMP = Path(tempfile.mkdtemp(prefix="uji_auth_"))
DB_UJI = TMP / "auth_uji.db"
ADMIN = {"email": "admin.uji@example.com", "password": "AdminUji123", "nama": "Admin Uji"}
PASSWORD = "rahasia123"
PROFIL = {"tipe_kulit": "kombinasi", "masalah_kulit": ["jerawat", "kusam"], "budget": 100000,
          "tanpa_batas_budget": False}
_hasil = []
_proses = None


def cek(kode, deskripsi, lulus, bukti=""):
    _hasil.append((kode, deskripsi, bool(lulus), bukti))
    print(f"  [{'PASS' if lulus else 'FAIL'}] {kode} {deskripsi}" + (f"\n         bukti: {bukti}" if bukti else ""))


# ---------------- backend uji ----------------

def nyalakan_backend():
    global _proses
    env = {**os.environ, "DATABASE_PATH": str(DB_UJI), "MODE_RINGAN": "1", "ADMIN_EMAIL": ADMIN["email"],
           "ADMIN_PASSWORD": ADMIN["password"], "ADMIN_NAMA": ADMIN["nama"], "PYTHONIOENCODING": "utf-8",
           "WAJIB_HTTPS": "1"}  # seperti saat deploy; request ke localhost tetap diizinkan
    for k in ("RATE_LIMIT_REGISTER", "RATE_LIMIT_LOGIN_GAGAL"):
        env.pop(k, None)  # pakai nilai default produksi
    log = open(TMP / "backend.log", "w", encoding="utf-8")
    _proses = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(PORT)],
                               cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    atexit.register(matikan_backend)
    batas = time.time() + 240
    while time.time() < batas:
        if _proses.poll() is not None:
            sys.exit(f"Backend uji mati saat startup, lihat {TMP / 'backend.log'}")
        try:
            if api("GET", "/health")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(1)
    sys.exit("Backend uji tidak siap dalam 240 detik")


def matikan_backend():
    if _proses and _proses.poll() is None:
        _proses.terminate()
        try:
            _proses.wait(10)
        except subprocess.TimeoutExpired:
            _proses.kill()


def api(method, path, body=None, token=None, ip="127.0.0.1", headers=None):
    """Request ke backend uji dari alamat IP sumber tertentu (127.x.x.x) --
    dipakai untuk menguji rate limit per IP. return: (status, json, headers)."""
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60, source_address=(ip, 0))
    h = {"Content-Type": "application/json", **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=h)
    resp = conn.getresponse()
    teks = resp.read().decode("utf-8")
    conn.close()
    try:
        data = json.loads(teks) if teks else {}
    except ValueError:
        data = {"_mentah": teks}
    return resp.status, data, {k.lower(): v for k, v in resp.getheaders()}


_nomor_ip = itertools.count(1)


def ip_baru():
    """IP sumber unik per pendaftaran lewat API, supaya tes-tes lain tidak
    saling menghabiskan jatah rate limit register (per IP)."""
    n = next(_nomor_ip)
    return f"127.0.{2 + n // 250}.{1 + n % 250}"


def email_unik(awal="uji"):
    return f"{awal}.{uuid.uuid4().hex[:8]}@example.com"


def daftar(nama="Pengguna Uji", email=None, password=PASSWORD, **tambahan):
    email = email or email_unik()
    s, d, _ = api("POST", "/register", {"nama": nama, "email": email, "password": password, **tambahan}, ip=ip_baru())
    return s, d, email


def masuk(email, password=PASSWORD, ip="127.0.0.1"):
    return api("POST", "/login", {"email": email, "password": password}, ip=ip)


def baris_db(sql, *param):
    conn = sqlite3.connect(DB_UJI)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, param).fetchall()]
    finally:
        conn.close()


# ---------------- frontend (AppTest) ----------------

def app(ke=None):
    from streamlit.testing.v1 import AppTest
    if str(ROOT / "frontend") not in sys.path:  # `streamlit run` menambahkan ini otomatis, AppTest tidak
        sys.path.insert(0, str(ROOT / "frontend"))
    at = AppTest.from_file(str(ROOT / "frontend" / "app.py"), default_timeout=60)
    if ke:
        at.query_params["ke"] = ke
    at.run()
    return at


def isi_register(at, nama, email, password, konfirmasi):
    for i, v in enumerate((nama, email, password, konfirmasi)):
        at.text_input[i].set_value(v)
    at.button[0].click()
    at.run()
    return at


def isi_login(at, email, password):
    at.text_input[0].set_value(email)
    at.text_input[1].set_value(password)
    at.button[0].click()
    at.run()
    return at


def error_field(at):
    """Pesan error per field yang tampil di bawah input (class field-error)."""
    return [m.value for m in at.markdown if m.value.startswith('<div class="field-error">')]


def teks_error(at):
    return " | ".join(e.value for e in at.error)


# ---------------- BAGIAN 1: registrasi ----------------

def uji_bagian_1():
    print("\n=== BAGIAN 1: Registrasi (buat akun baru) ===")

    # 1.1 register lengkap -> akun dibuat, langsung ke form onboarding
    s, d, email_api = daftar("Rina Uji")
    email_form = email_unik("form")
    at = isi_register(app("register"), "Sari Uji", email_form, PASSWORD, PASSWORD)
    ss = at.session_state
    ke_onboarding = ss["user"] is not None and not ss["onboarding_selesai"] and len(at.selectbox) == 1 \
        and len(at.multiselect) == 1 and len(at.chat_input) == 0
    cek("1.1", "Register lengkap & valid -> akun dibuat, langsung login & diarahkan ke form onboarding",
        s == 201 and set(d) == {"id", "nama", "email"} and d["email"] == email_api and ke_onboarding
        and ss["user"]["nama"] == "Sari Uji" and ss["token"],
        f"API -> {s} {d}; lewat form -> login otomatis sebagai {ss['user']['nama'] if ss['user'] else None}, "
        f"halaman berikutnya = form onboarding (tipe kulit, masalah kulit, budget)={ke_onboarding}")

    # 1.2 email sudah terdaftar
    s2, d2, _ = daftar("Orang Lain", email=email_api)
    s3, d3, _ = daftar("Orang Lain", email=email_api.upper())
    at = isi_register(app("register"), "Orang Lain", email_form, PASSWORD, PASSWORD)
    err = error_field(at)
    cek("1.2", "Email sudah terdaftar -> ditolak dengan pesan jelas + diarahkan ke login (juga kalau beda huruf besar/kecil)",
        s2 == 409 and "sudah terdaftar" in d2["detail"] and s3 == 409
        and len(err) == 1 and "sudah terdaftar" in err[0] and "?ke=login" in err[0] and at.session_state["user"] is None,
        f"API -> {s2} {d2['detail']!r}; huruf besar -> {s3}; form -> di bawah field email: "
        f"{err[0] if err else None!r}")

    # 1.3 format email tidak valid -- frontend DAN backend
    hasil = {}
    for salah in ("user@", "usergmail.com", "user @gmail.com"):
        s, d, _ = daftar(email=salah)
        at = isi_register(app("register"), "Uji", salah, PASSWORD, PASSWORD)
        hasil[salah] = (s, (d.get("errors") or {}).get("email"), error_field(at), at.session_state["user"])
    cek("1.3", "Format email tidak valid -> ditolak di form DAN di backend (request langsung)",
        all(s == 400 and pesan and "Format email tidak valid" in pesan and len(ef) == 1 and "Format email" in ef[0]
            and u is None for s, pesan, ef, u in hasil.values()),
        "; ".join(f"{e!r}: backend {s} {p!r}, form menandai field email" for e, (s, p, _, _) in hasil.items()))

    # 1.4 password terlalu pendek (dan terlalu panjang: dulu error 500 di bcrypt)
    s, d, _ = daftar(password="123")
    s_panjang, d_panjang, _ = daftar(password="a" * 80)
    at = isi_register(app("register"), "Uji", email_unik(), "123", "123")
    ef = error_field(at)
    cek("1.4", "Password terlalu pendek -> ditolak dengan syarat yang jelas (minimal 8 karakter); terlalu panjang "
               "-> ditolak rapi, bukan error server",
        s == 400 and "minimal 8 karakter" in d["errors"]["password"] and s_panjang == 400
        and "maksimal 72" in d_panjang["errors"]["password"] and len(ef) == 1 and "minimal 8 karakter" in ef[0],
        f"'123' -> backend {s} {d['errors']['password']!r}, form: {ef[0] if ef else None!r}; 80 karakter -> "
        f"{s_panjang} {d_panjang['errors']['password']!r} (sebelumnya 500)")

    # 1.5 konfirmasi password (field-nya ADA di form yang dibangun, jadi diuji)
    email_konf = email_unik()
    at = isi_register(app("register"), "Uji", email_konf, PASSWORD, "rahasia124")
    ef = error_field(at)
    tidak_dibuat = masuk(email_konf)[0] == 401
    cek("1.5", "Konfirmasi password tidak cocok -> ditolak di form, akun tidak dibuat (field konfirmasi ada di "
               "form yang dibangun, jadi skenario ini tetap diuji)",
        len(ef) == 1 and "Konfirmasi password tidak sama" in ef[0] and tidak_dibuat,
        f"form: {ef[0] if ef else None!r}; akun tidak terbentuk={tidak_dibuat}")

    # 1.6 field wajib kosong -> ditolak PER FIELD
    s, d, _ = api("POST", "/register", {"nama": "", "email": "", "password": ""}, ip=ip_baru())
    s_hilang, d_hilang, _ = api("POST", "/register", {}, ip=ip_baru())
    s_spasi, d_spasi, _ = daftar(nama="    ")
    at = isi_register(app("register"), "", "", "", "")
    ef = error_field(at)
    cek("1.6", "Field wajib dikosongkan -> ditolak per field (jelas field mana), di form & backend",
        s == 400 and set(d["errors"]) == {"nama", "email", "password"}
        and s_hilang == 400 and all(v == "wajib diisi" for v in d_hilang["errors"].values()) and len(d_hilang["errors"]) == 3
        and s_spasi == 400 and "Nama wajib diisi" in d_spasi["errors"]["nama"]
        and len(ef) == 3 and any("Nama wajib" in e for e in ef) and any("Email wajib" in e for e in ef)
        and any("Password wajib" in e for e in ef),
        f"backend (semua kosong) -> {d['errors']}; field tidak dikirim -> {d_hilang['errors']}; nama spasi -> "
        f"{d_spasi['errors']}; form -> {len(ef)} pesan, masing-masing di bawah fieldnya")

    # 1.7 bypass form: request langsung dengan data tidak valid
    kasus = {"email salah": {"nama": "A", "email": "bukan-email", "password": PASSWORD},
             "password pendek": {"nama": "A", "email": email_unik(), "password": "abc"},
             "nama kosong": {"nama": "", "email": email_unik(), "password": PASSWORD},
             "tipe data salah": {"nama": 123, "email": ["x"], "password": None},
             "bukan JSON objek": ["nama", "email"]}
    langsung = {}
    for nama_kasus, body in kasus.items():
        s, d, _ = api("POST", "/register", body, ip=ip_baru())
        langsung[nama_kasus] = (s, d.get("detail"))
    jumlah_user = baris_db("SELECT COUNT(*) n FROM users")[0]["n"]
    cek("1.7", "Request langsung ke backend (bypass form) dengan data tidak valid -> tetap ditolak dengan aturan "
               "yang sama (400, bukan 500), tidak ada akun terbentuk",
        all(s == 400 for s, _ in langsung.values())
        and not baris_db("SELECT 1 FROM users WHERE email IN ('bukan-email')"),
        "; ".join(f"{k}: {s} {p!r}" for k, (s, p) in langsung.items()) + f"; jumlah akun di DB uji: {jumlah_user}")

    # 1.8 karakter berbahaya: XSS & SQL injection
    xss = "<script>alert(1)</script>"
    sqli = "'; DROP TABLE users;--"
    s, d, email_xss = daftar(nama=xss, password=sqli + "abc")
    s_sqli_email, _, _ = daftar(email="x'; DROP TABLE users;--@example.com")
    tabel_utuh = bool(baris_db("SELECT name FROM sqlite_master WHERE type='table' AND name='users'"))
    tersimpan = baris_db("SELECT nama FROM users WHERE email=?", email_xss)
    s_login, d_login, _ = masuk(email_xss, sqli + "abc")
    s_bypass, _, _ = api("POST", "/login", {"email": "' OR '1'='1", "password": "' OR '1'='1"})
    api("PUT", "/profile", PROFIL, token=d_login.get("access_token"))
    at = isi_login(app("login"), email_xss, sqli + "abc")
    at.session_state["halaman"] = "profile"
    at.run()
    halaman = " ".join(m.value for m in at.markdown)
    aman = "&lt;script&gt;alert(1)&lt;/script&gt;" in halaman and xss not in halaman
    cek("1.8", "Karakter berbahaya (XSS/SQL injection) -> disimpan sebagai teks biasa, di-escape saat tampil, "
               "tidak dieksekusi; query SQL berparameter",
        s == 201 and tersimpan and tersimpan[0]["nama"] == xss and tabel_utuh and s_sqli_email in (201, 400)
        and s_login == 200 and s_bypass in (400, 401) and aman,
        f"nama {xss!r} -> {s}, tersimpan apa adanya, tampil di halaman profil sebagai "
        f"'&lt;script&gt;...' (tidak dieksekusi)={aman}; password berisi {sqli!r} -> login normal ({s_login}); "
        f"email berisi SQL -> {s_sqli_email}; login \"' OR '1'='1\" -> {s_bypass}; tabel users masih ada={tabel_utuh}")

    # 1.10 password tersimpan ter-hash (bcrypt), bukan teks biasa
    import bcrypt
    row = baris_db("SELECT * FROM users WHERE email=?", email_api)[0]
    h = row["password_hash"]
    kolom_bocor = [k for k, v in row.items() if isinstance(v, str) and PASSWORD in v]
    cek("1.10", "Password tersimpan ter-hash bcrypt di database, bukan plain text",
        h.startswith("$2b$") and len(h) == 60 and PASSWORD not in h and bcrypt.checkpw(PASSWORD.encode(), h.encode())
        and not kolom_bocor,
        f"kolom password_hash = {h[:12]}...{h[-4:]} (bcrypt, {len(h)} karakter, cost {h[4:6]}); password asli tidak "
        f"muncul di kolom mana pun={not kolom_bocor}")

    # 1.11 mencoba membuat Admin lewat /register
    s, d, email_adm = daftar(nama="Penyusup", role="admin", is_active=1)
    s_b, d_b, email_adm2 = daftar(nama="Penyusup 2", role="Admin")
    peran = [baris_db("SELECT role FROM users WHERE email=?", e)[0]["role"] for e in (email_adm, email_adm2)]
    token = masuk(email_adm)[1]["access_token"]
    s_admin = api("GET", "/admin/users", token=token)[0]
    cek("1.11", "Kirim role:'admin' lewat POST /register -> diabaikan, akun tetap role User & tidak bisa akses admin",
        s == 201 and s_b == 201 and peran == ["User", "User"] and s_admin == 403,
        f"register dengan role 'admin'/'Admin' -> {s}/{s_b}, role di DB = {peran}; GET /admin/users -> {s_admin}")

    # 1.9 rate limit register (dari 1 IP khusus, supaya jatah IP lain tidak terpakai)
    ip_bot = "127.0.9.9"
    status = []
    for i in range(15):
        s, d, h = api("POST", "/register", {"nama": "Bot", "email": f"bot{i}.{uuid.uuid4().hex[:6]}@example.com",
                                            "password": PASSWORD}, ip=ip_bot)
        status.append(s)
        if s == 429:
            break
    s_lain, _, _ = daftar()  # IP lain tetap bisa daftar
    cek("1.9", "Register beruntun dari 1 perangkat -> dibatasi (429 + pesan kapan boleh coba lagi); perangkat lain "
               "tidak ikut terblokir",
        status[-1] == 429 and status.count(201) == 10 and "Terlalu banyak percobaan daftar" in d["detail"]
        and int(h.get("retry-after", 0)) > 0 and s_lain == 201,
        f"status berturut-turut: {status}; pesan: {d['detail']!r}; Retry-After={h.get('retry-after')} detik; "
        f"IP lain -> {s_lain} (batas default: 10 percobaan / 10 menit per IP)")


# ---------------- BAGIAN 2: login ----------------

def token_palsu(user_id, kedaluwarsa=True, role="User"):
    """JWT bertanda tangan asli (secret dari .env, sama dengan backend) tapi
    sudah kedaluwarsa -- mensimulasikan sesi yang habis di tengah chat."""
    import jwt
    from dotenv import dotenv_values
    secret = dotenv_values(ROOT / ".env")["JWT_SECRET"]
    sekarang = int(time.time())
    payload = {"sub": user_id, "role": role, "iat": sekarang - 8 * 86400,
               "exp": sekarang - 3600 if kedaluwarsa else sekarang + 3600}
    return jwt.encode(payload, secret, algorithm="HS256")


def akun_lengkap(nama="Pengguna Uji", profil=PROFIL):
    """Akun REAL (register + login sungguhan) yang sudah pernah mengisi profil."""
    s, d, email = daftar(nama)
    token = masuk(email)[1]["access_token"]
    api("PUT", "/profile", profil, token=token)
    return email, token, d["id"]


def token_admin():
    return masuk(ADMIN["email"], ADMIN["password"])[1]["access_token"]


def uji_bagian_2():
    print("\n=== BAGIAN 2: Login ===")

    # 2.1 login benar, akun sudah pernah isi profil -> langsung chat pakai profil terakhir
    email, _, _ = akun_lengkap("Dina Uji")
    at = isi_login(app("login"), email, PASSWORD)
    ss = at.session_state
    langsung_chat = ss["onboarding_selesai"] and len(at.chat_input) == 1 and len(at.selectbox) == 0
    ob = dict(ss["onboarding"])
    cek("2.1", "Login benar (akun REAL yang sudah pernah isi profil) -> langsung ke chat pakai profil terakhir, "
               "tanpa form ulang",
        langsung_chat and ob["tipe_kulit"] == PROFIL["tipe_kulit"] and ob["masalah_kulit"] == PROFIL["masalah_kulit"]
        and ob["budget"] == PROFIL["budget"],
        f"akun baru didaftarkan & mengisi profil lewat API, lalu login lewat form -> halaman chat={langsung_chat}, "
        f"profil dipulihkan={ob}")

    # 2.2 & 2.3 password salah vs email tidak terdaftar -> pesan & waktu respons sama
    def waktu(email_uji, pw):
        mulai = time.perf_counter()
        s, d, _ = masuk(email_uji, pw, ip=ip_baru())
        return s, d, time.perf_counter() - mulai
    salah = [waktu(email, "passwordsalah1") for _ in range(3)]
    tidak_ada = [waktu(email_unik("hantu"), "passwordsalah1") for _ in range(3)]
    rata = lambda xs: sum(x[2] for x in xs) / len(xs)  # noqa: E731
    at_salah = isi_login(app("login"), email, "passwordsalah1")
    at_hantu = isi_login(app("login"), email_unik("hantu"), "passwordsalah1")
    sama = {(s, d["detail"]) for s, d, _ in salah + tidak_ada}
    cek("2.2", "Password salah (email terdaftar) -> ditolak dengan pesan GENERIK, bukan 'password salah'",
        sama == {(401, "Email atau kata sandi salah.")} and "password salah" not in teks_error(at_salah).lower()
        and teks_error(at_salah) == "Email atau kata sandi salah.",
        f"API -> {salah[0][0]} {salah[0][1]['detail']!r}; form -> {teks_error(at_salah)!r}")
    cek("2.3", "Email tidak terdaftar -> pesan SAMA PERSIS dengan 2.2 (status, isi, dan lama respons mirip) -- "
               "tidak bisa dipakai menebak email mana yang punya akun",
        len(sama) == 1 and teks_error(at_hantu) == teks_error(at_salah) and abs(rata(salah) - rata(tidak_ada)) < 0.15,
        f"respons email terdaftar vs tidak: {sorted(sama)} (identik); form: {teks_error(at_hantu)!r}; rata-rata waktu "
        f"{rata(salah):.3f} dtk vs {rata(tidak_ada):.3f} dtk (email tidak terdaftar tetap menjalankan bcrypt)")

    # 2.4 gagal berkali-kali -> dikunci sementara
    email_b, _, _ = akun_lengkap("Target Brute Force")
    ip_penyerang = "127.0.8.8"
    status = [masuk(email_b, f"tebakan{i}", ip=ip_penyerang)[0] for i in range(7)]
    s_benar, d_benar, h_benar = masuk(email_b, PASSWORD, ip=ip_penyerang)
    s_lain_email = masuk(email_unik("lain"), "tebakan", ip=ip_penyerang)[0]
    s_pemilik = masuk(email_b, PASSWORD, ip=ip_baru())[0]
    hantu = email_unik("hantu")
    status_hantu = [masuk(hantu, f"tebakan{i}", ip="127.0.8.9")[0] for i in range(6)]
    cek("2.4", "Login gagal berkali-kali -> dikunci sementara (429 + kapan boleh coba lagi), password benar pun "
               "ditolak selama terkunci; berlaku juga untuk email tidak terdaftar",
        status[:5] == [401] * 5 and status[5:] == [429, 429] and s_benar == 429
        and "Terlalu banyak percobaan login" in d_benar["detail"] and int(h_benar.get("retry-after", 0)) > 0
        and s_lain_email == 401 and s_pemilik == 200 and status_hantu == [401] * 5 + [429],
        f"7x salah dari 1 perangkat: {status}; lalu password BENAR -> {s_benar} {d_benar['detail']!r}; email lain dari "
        f"perangkat itu -> {s_lain_email}; pemilik dari perangkat lain -> {s_pemilik}; email tidak terdaftar: "
        f"{status_hantu} (sama, tidak membocorkan) -- batas default 5 gagal / 15 menit")

    # 2.5 field kosong saat submit -> ditolak sebelum dikirim
    at = isi_login(app("login"), "", "")
    ef = error_field(at)
    s, d, _ = api("POST", "/login", {"email": "", "password": ""})
    cek("2.5", "Field kosong saat login -> ditolak di form (per field) sebelum dikirim; backend juga menolak",
        len(ef) == 2 and "Email wajib diisi" in ef[0] and "Password wajib diisi" in ef[1] and at.session_state["user"] is None
        and s == 400 and set(d["errors"]) == {"email", "password"},
        f"form -> {[e.split('>')[1].split('<')[0] for e in ef]}; backend -> {s} {d['errors']}")

    # 2.6 email tidak peka huruf besar/kecil
    email_c = f"User.Case.{uuid.uuid4().hex[:6]}@Example.COM"
    s_reg, d_reg, _ = daftar("Case", email=email_c)
    varian = {e: masuk(e)[0] for e in (email_c.lower(), email_c.upper(), f"  {email_c}  ")}
    at = isi_login(app("login"), email_c.lower(), PASSWORD)
    s_dobel = daftar("Case 2", email=email_c.lower())[0]
    cek("2.6", "Register 'User@Gmail.com', login 'user@gmail.com' -> akun yang SAMA (email tidak peka huruf besar/kecil)",
        s_reg == 201 and d_reg["email"] == email_c.lower() and set(varian.values()) == {200}
        and at.session_state["user"] is not None and s_dobel == 409,
        f"daftar {email_c!r} -> tersimpan {d_reg.get('email')!r}; login huruf kecil/besar/berspasi -> {list(varian.values())}; "
        f"daftar lagi versi huruf kecil -> {s_dobel} (dianggap email yang sama)")

    # 2.7 token kedaluwarsa di tengah chat -> diarahkan login ulang dengan pesan jelas
    email_d, token_d, id_d = akun_lengkap("Sesi Habis")
    basi = token_palsu(id_d)
    s_chat, d_chat, _ = api("POST", "/chat", {"message": "rekomendasiin sunscreen dong", "onboarding": PROFIL}, token=basi)
    s_hist, d_hist, _ = api("GET", "/history", token=basi)
    at = isi_login(app("login"), email_d, PASSWORD)
    at.session_state["token"] = basi
    at.chat_input[0].set_value("rekomendasiin sunscreen dong").run()
    peringatan = " ".join(w.value for w in at.warning)
    cek("2.7", "Token kedaluwarsa di tengah chat -> diarahkan ke halaman login dengan pesan jelas (bukan diam-diam "
               "jadi tamu / error / hang)",
        s_chat == 401 and "Sesi login kamu sudah berakhir" in d_chat["detail"] and s_hist == 401
        and at.session_state["halaman"] == "login" and at.session_state["token"] is None
        and "Sesi login kamu sudah berakhir" in peringatan and len(at.chat_input) == 0,
        f"POST /chat dengan token kedaluwarsa -> {s_chat} {d_chat['detail']!r} (dulu: diam-diam dijawab sebagai tamu, "
        f"riwayat tidak tersimpan); di aplikasi -> pindah ke halaman login dengan peringatan {peringatan!r}")

    # 2.8 login dari 2 device bersamaan -> keduanya aktif (keputusan: boleh)
    email_e, _, _ = akun_lengkap("Dua Device")
    laptop = masuk(email_e, ip=ip_baru())[1]["access_token"]
    hp = masuk(email_e, ip=ip_baru())[1]["access_token"]  # di detik yang sama dengan laptop
    s_laptop, s_hp = api("GET", "/history", token=laptop)[0], api("GET", "/history", token=hp)[0]
    cek("2.8", "Login dari 2 device bersamaan -> dua sesi sama-sama aktif & terpisah (kebijakan yang dipilih: boleh "
               "bersamaan)",
        laptop != hp and s_laptop == 200 and s_hp == 200,
        f"login laptop & HP dalam detik yang sama -> token berbeda={laptop != hp} (tiap sesi punya id unik); akses "
        f"riwayat dari laptop -> {s_laptop}, dari HP -> {s_hp}")

    # 2.9 akun dinonaktifkan admin -> login ditolak dengan pesan KHUSUS (hanya kalau password benar)
    email_f, token_f, id_f = akun_lengkap("Dinonaktifkan")
    s_nonaktif = api("PUT", f"/admin/users/{id_f}", {"is_active": False}, token=token_admin())[0]
    s1, d1, _ = masuk(email_f, ip=ip_baru())
    s2, d2, _ = masuk(email_f, "passwordsalah1", ip=ip_baru())
    at = isi_login(app("login"), email_f, PASSWORD)
    cek("2.9", "Akun dinonaktifkan admin, login dengan password BENAR -> ditolak 401 dengan pesan khusus 'hubungi "
               "admin'; password salah tetap pesan generik",
        s_nonaktif == 200 and s1 == 401 and "dinonaktifkan" in d1["detail"] and "admin" in d1["detail"].lower()
        and d1["detail"] != "Email atau kata sandi salah." and s2 == 401 and d2["detail"] == "Email atau kata sandi salah."
        and "dinonaktifkan" in teks_error(at),
        f"password benar -> {s1} {d1['detail']!r}; password salah -> {s2} {d2['detail']!r}; form -> {teks_error(at)!r}")


# ---------------- BAGIAN 3: logout & sesi ----------------

PORT_FRONTEND = 8511
_frontend = None


def nyalakan_frontend():
    """Streamlit sungguhan (dibuka di Chrome headless) yang terhubung ke backend uji."""
    global _frontend
    if _frontend is None:
        env = {**os.environ, "BACKEND_URL": BACKEND_URL}
        log = open(TMP / "frontend.log", "w", encoding="utf-8")
        _frontend = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "frontend/app.py", "--server.port",
                                      str(PORT_FRONTEND), "--server.headless", "true"],
                                     cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        atexit.register(lambda: _frontend.poll() is None and _frontend.terminate())
        batas = time.time() + 90
        while time.time() < batas:
            try:
                c = http.client.HTTPConnection("127.0.0.1", PORT_FRONTEND, timeout=2)
                c.request("GET", "/")
                if c.getresponse().status == 200:
                    break
            except OSError:
                time.sleep(1)
    return f"http://localhost:{PORT_FRONTEND}"


def browser():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument("--window-size=1200,1300")
    return webdriver.Chrome(options=o)


def tunggu_teks(d, teks, detik=40):
    from selenium.webdriver.common.by import By
    batas = time.time() + detik
    while time.time() < batas:
        if teks in d.find_element(By.TAG_NAME, "body").text:
            return True
        time.sleep(0.5)
    return False


def login_browser(d, url, email, password=PASSWORD):
    from selenium.webdriver.common.by import By
    d.get(f"{url}/?ke=login")
    tunggu_teks(d, "Welcome back")
    kolom = d.find_elements(By.CSS_SELECTOR, ".st-key-auth_card input")
    kolom[0].send_keys(email)
    kolom[1].send_keys(password)
    d.find_element(By.XPATH, '//button[.//p[text()="Login"]]').click()
    if tunggu_teks(d, "Ada yang bisa dibantu?", 60) and d.find_elements(By.CSS_SELECTOR, 'div[data-testid="stChatInput"] textarea'):
        return True
    d.save_screenshot(str(TMP / f"login_gagal_{uuid.uuid4().hex[:6]}.png"))
    print("    [diagnosa] halaman setelah login:", d.find_element(By.TAG_NAME, "body").text[:300].replace("\n", " | "))
    return False


def penyimpanan_browser(d):
    """Isi localStorage, sessionStorage, dan cookie halaman (untuk mencari token)."""
    return d.execute_script("return JSON.stringify({local: Object.assign({}, localStorage), "
                            "session: Object.assign({}, sessionStorage), cookie: document.cookie});")


def uji_bagian_3():
    print("\n=== BAGIAN 3: Logout & manajemen sesi ===")
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    # 3.1 logout -> sesi benar-benar berakhir (token dicabut di server, bukan hanya dihapus di aplikasi)
    email, _, _ = akun_lengkap("Logout Uji")
    lain = masuk(email, ip=ip_baru())[1]["access_token"]  # sesi di device lain
    at = isi_login(app("login"), email, PASSWORD)
    token_lama = at.session_state["token"]
    s_sebelum = api("GET", "/history", token=token_lama)[0]
    at.session_state["halaman"] = "profile"
    at.run()
    next(b for b in at.button if b.label == "Log out").click()
    at.run()
    ss = at.session_state
    # AppTest ikut menyimpan elemen halaman Profile dari run yang di-rerun, jadi yang
    # dicek: form login BENAR tampil (judul + input Email & Password)
    form_login = "Welcome back" in " ".join(m.value for m in at.markdown) \
        and {"Email", "Password"} <= {t.label for t in at.text_input}
    s_sesudah, d_sesudah, _ = api("GET", "/history", token=token_lama)
    s_lain = api("GET", "/history", token=lain)[0]
    baru = app()
    cek("3.1", "Klik logout -> sesi benar-benar berakhir: token dicabut di server, data akun dibersihkan dari "
               "aplikasi, buka chatbot lagi tidak otomatis masuk",
        s_sebelum == 200 and ss["token"] is None and ss["user"] is None and ss["halaman"] == "login"
        and not ss["onboarding_selesai"] and ss["onboarding"]["tipe_kulit"] == "" and form_login
        and s_sesudah == 401 and "berakhir" in d_sesudah["detail"] and s_lain == 200
        and baru.session_state["user"] is None,
        f"sebelum logout token -> {s_sebelum}; sesudah logout token yang SAMA -> {s_sesudah} {d_sesudah['detail']!r} "
        f"(dulu tetap berlaku sampai 7 hari); profil kulit akun ikut dihapus dari aplikasi, pindah ke halaman login; "
        f"sesi di device lain tetap jalan -> {s_lain}; buka chatbot lagi -> belum login")

    # 3.2 & 3.3 di browser sungguhan
    url = nyalakan_frontend()
    email_b, _, _ = akun_lengkap("Browser Uji")
    d = browser()
    try:
        masuk_ok = login_browser(d, url, email_b)
        bocor_back = True
        if masuk_ok:
            chat = d.find_element(By.CSS_SELECTOR, 'div[data-testid="stChatInput"] textarea')
            chat.send_keys("rahasia pribadi: rekomendasiin sunscreen dong")
            chat.send_keys(Keys.ENTER)
            tunggu_teks(d, "sunscreen untuk kulit", 60)
            d.find_element(By.XPATH, '//button[.//p[text()="Profile"]]').click()
            tunggu_teks(d, "Browser Uji")
            d.find_element(By.XPATH, '//button[.//p[text()="Log out"]]').click()
            tunggu_teks(d, "Welcome back")
            jejak = []
            for _ in range(3):
                d.back()
                time.sleep(4)
                teks = d.find_element(By.TAG_NAME, "body").text
                jejak.append(("rahasia pribadi" in teks) or ("Browser Uji" in teks) or (email_b in teks))
            bocor_back = any(jejak)
    finally:
        d.quit()
    cek("3.2", "Tombol back browser setelah logout -> histori chat & profil lama TIDAK terlihat lagi",
        masuk_ok and not bocor_back,
        f"login di Chrome, chat, buka Profile, logout, lalu tekan back 3x -> isi chat/nama/email lama terlihat="
        f"{bocor_back} (histori & token hanya ada di sesi server Streamlit, bukan di cache halaman browser)")

    d = browser()
    try:
        login_browser(d, url, email_b)
        simpanan = penyimpanan_browser(d)
        tab_lama = d.current_window_handle
        d.switch_to.new_window("tab")
        tab_baru = d.current_window_handle
        d.switch_to.window(tab_lama)
        d.close()  # tutup tanpa logout
        d.switch_to.window(tab_baru)
        d.get(url)
        tunggu_teks(d, "Tipe kulit")
        teks = d.find_element(By.TAG_NAME, "body").text
        masih_login = "Browser Uji" in teks or "Ada yang bisa dibantu?" in teks
        form_tamu = "won't be saved" in teks
    finally:
        d.quit()
    cek("3.3", "Tutup browser/tab tanpa logout lalu buka lagi -> wajib login ulang (kebijakan yang dipilih), konsisten "
               "karena token tidak pernah disimpan di browser",
        not masih_login and form_tamu and "eyJ" not in simpanan,
        f"setelah tab ditutup & chatbot dibuka lagi di browser yang sama -> masih login={masih_login}, tampil form "
        f"tamu={form_tamu}; token JWT di localStorage/sessionStorage/cookie={'eyJ' in simpanan}")


# ---------------- BAGIAN 5: keamanan tambahan ----------------

def chat_login(pesan, token, conversation_id=None, konteks=None):
    body = {"message": pesan, "onboarding": PROFIL, "konteks": konteks}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return api("POST", "/chat", body, token=token)


def uji_bagian_5():
    print("\n=== BAGIAN 5: Keamanan tambahan ===")

    # 5.1 IDOR: user B memakai ID milik user A
    email_a, token_a, id_a = akun_lengkap("Pemilik A")
    email_b, token_b, id_b = akun_lengkap("Penyusup B")
    _, d_a, _ = chat_login("rekomendasiin sunscreen dong", token_a)
    conv_a = d_a["conversation_id"]
    pesan_a = len(api("GET", "/history", token=token_a)[1]["conversations"][0]["messages"])
    s_chat, d_chat, _ = chat_login("tulis ke percakapan orang lain", token_b, conversation_id=conv_a)
    s_hist, d_hist, _ = api("GET", f"/history?user_id={id_a}", token=token_b)
    punya_b = [c["id"] for c in d_hist["conversations"]]
    s_prof = api("PUT", "/profile", {**PROFIL, "tipe_kulit": "sensitif", "user_id": id_a, "id": id_a}, token=token_b)[0]
    profil_a = masuk(email_a)[1]["user"]["tipe_kulit"]
    s_admin = api("PUT", f"/admin/users/{id_a}", {"is_active": False}, token=token_b)[0]
    pesan_a_sesudah = len(api("GET", "/history", token=token_a)[1]["conversations"][0]["messages"])
    cek("5.1", "Manipulasi ID milik user lain (percakapan, riwayat, profil, status akun) -> ditolak / diabaikan; "
               "backend selalu memakai identitas dari sesi login",
        s_chat == 403 and conv_a not in punya_b and s_hist == 200 and s_prof == 200 and profil_a == PROFIL["tipe_kulit"]
        and s_admin == 403 and pesan_a_sesudah == pesan_a and masuk(email_a)[0] == 200,
        f"B kirim pesan ke conversation_id milik A -> {s_chat} {d_chat.get('detail')!r}; B minta /history?user_id=<A> "
        f"-> cuma dapat riwayatnya sendiri ({len(punya_b)} percakapan, milik A tidak ada); B PUT /profile dengan "
        f"user_id A -> yang berubah profil B, profil A tetap {profil_a!r}; B nonaktifkan akun A -> {s_admin}; isi "
        f"percakapan A tidak bertambah ({pesan_a} -> {pesan_a_sesudah} pesan)")

    # 5.2 password/token tidak bocor di response, pesan error, maupun log server
    rahasia = f"Bocor{uuid.uuid4().hex[:10]}"
    email_c = email_unik("rahasia")
    respons = []
    respons.append(api("POST", "/register", {"nama": "C", "email": email_c, "password": rahasia}, ip=ip_baru())[1])
    s_login, d_login, _ = masuk(email_c, rahasia)
    token_c = d_login["access_token"]
    respons.append({k: v for k, v in d_login.items() if k != "access_token"})
    respons.append(api("POST", "/register", {"nama": "C", "email": "salah@", "password": rahasia}, ip=ip_baru())[1])
    respons.append(masuk(email_c, rahasia + "x")[1])
    respons.append(api("GET", "/history", token=token_c)[1])
    respons.append(api("GET", "/admin/users", token=token_admin())[1])
    respons.append(api("PUT", "/change-password", {"password_lama": rahasia + "x", "password_baru": "barubaru123"},
                       token=token_c)[1])
    teks_respons = json.dumps(respons)
    at = isi_register(app("register"), "C", "salah@", rahasia, rahasia)
    teks_halaman = " ".join(m.value for m in at.markdown) + teks_error(at)
    log = (TMP / "backend.log").read_text(encoding="utf-8", errors="replace")
    bocor = {"password di response": rahasia in teks_respons, "hash di response": "$2b$" in teks_respons
             or "password_hash" in teks_respons, "token di response selain /login": token_c in teks_respons,
             "password di halaman": rahasia in teks_halaman, "password di log server": rahasia in log,
             "hash di log server": "$2b$" in log, "token di log server": token_c in log or "eyJ" in log}
    cek("5.2", "Password/token tidak muncul mentah di response API, pesan error, halaman, maupun log server",
        s_login == 200 and not any(bocor.values()),
        f"dicek {len(respons)} response (register, login, error validasi, login gagal, riwayat, daftar user admin, "
        f"ganti password gagal), halaman form, dan {len(log.splitlines())} baris log server -> "
        + ", ".join(f"{k}={v}" for k, v in bocor.items()))

    # 5.3 HTTPS
    s_http, d_http, _ = api("GET", "/health", headers={"Host": "dewai.example.com", "X-Forwarded-Proto": "http"})
    s_https, _, h_https = api("GET", "/health", headers={"Host": "dewai.example.com", "X-Forwarded-Proto": "https"})
    s_lokal = api("GET", "/health")[0]
    sys.path.insert(0, str(ROOT / "frontend"))
    from core import backend_aman
    aturan_url = {u: backend_aman(u) for u in ("https://dewai.up.railway.app", "http://dewai.up.railway.app",
                                               "http://127.0.0.1:8000", "http://localhost:8000")}
    kode = ("import os, sys; sys.path.insert(0, 'frontend'); os.environ['BACKEND_URL'] = 'http://dewai.up.railway.app'\n"
            "from streamlit.testing.v1 import AppTest\n"
            "at = AppTest.from_file('frontend/app.py', default_timeout=60); at.run()\n"
            "print('|'.join(e.value for e in at.error), len(at.text_input) + len(at.selectbox))")
    keluaran = subprocess.run([sys.executable, "-c", kode], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"}).stdout
    cek("5.3", "Koneksi login/register wajib HTTPS: backend (WAJIB_HTTPS=1 saat deploy) menolak HTTP polos dari luar "
               "& mengirim HSTS; frontend menolak BACKEND_URL http ke server luar",
        s_http == 400 and "HTTPS" in d_http["detail"] and s_https == 200 and "strict-transport-security" in h_https
        and s_lokal == 200 and aturan_url == {"https://dewai.up.railway.app": True, "http://dewai.up.railway.app": False,
                                              "http://127.0.0.1:8000": True, "http://localhost:8000": True}
        and "harus lewat HTTPS" in keluaran and keluaran.strip().endswith(" 0"),
        f"request HTTP dari luar -> {s_http} {d_http['detail']!r}; lewat HTTPS -> {s_https} + HSTS "
        f"{h_https.get('strict-transport-security')!r}; localhost (pengembangan) -> {s_lokal}; frontend: {aturan_url}; "
        f"BACKEND_URL http ke server luar -> aplikasi berhenti dengan pesan & tanpa form")

    # 5.4 token di sisi klien
    url = nyalakan_frontend()
    email_d, _, _ = akun_lengkap("Klien Uji")
    d = browser()
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        login_ok = login_browser(d, url, email_d)
        if login_ok:
            chat = d.find_element(By.CSS_SELECTOR, 'div[data-testid="stChatInput"] textarea')
            chat.send_keys("rekomendasiin toner dong")
            chat.send_keys(Keys.ENTER)
            tunggu_teks(d, "toner untuk kulit", 60)
        simpanan = penyimpanan_browser(d)
        dom = d.page_source
    finally:
        d.quit()
    cek("5.4", "Token sesi tidak disimpan di browser (localStorage/sessionStorage/cookie/halaman) -- tidak bisa "
               "dicuri lewat XSS; token hanya ada di sesi server Streamlit",
        login_ok and "eyJ" not in simpanan and "eyJ" not in dom,
        f"setelah login & chat di Chrome: token JWT di localStorage/sessionStorage/cookie={'eyJ' in simpanan}, di "
        f"halaman (DOM)={'eyJ' in dom}. Browser hanya bicara ke server Streamlit; token dipakai server Streamlit "
        "untuk memanggil backend, jadi ini lebih ketat dari cookie httpOnly")


# ---------------- BAGIAN 6b: ganti password (dari layar Profil) ----------------

def app_profil(email, password=PASSWORD):
    at = isi_login(app("login"), email, password)
    at.session_state["halaman"] = "profile"
    at.run()
    return at


def ganti_password_form(at, lama, baru):
    kolom = {t.label: t for t in at.text_input}
    kolom["Current password"].set_value(lama)
    kolom["New password"].set_value(baru)
    next(b for b in at.button if b.label == "Change Password").click()
    at.run()
    return at


def uji_bagian_6b():
    print("\n=== BAGIAN 6b: Ganti password (layar Profil) ===")
    email, token, _ = akun_lengkap("Ganti Sandi")

    # 6b.1 password lama salah
    s, d, _ = api("PUT", "/change-password", {"password_lama": "bukanpassword1", "password_baru": "sandibaru123"}, token=token)
    at = ganti_password_form(app_profil(email), "bukanpassword1", "sandibaru123")
    ef = error_field(at)
    cek("6b.1", "Password lama salah -> ditolak dengan pesan jelas, user tetap login",
        s == 401 and d["detail"] == "Current password is incorrect." and len(ef) == 1
        and "Current password is incorrect" in ef[0]
        and at.session_state["token"] and at.session_state["halaman"] == "profile",
        f"API -> {s} {d['detail']!r}; form -> di bawah field Password Lama: {ef[0] if ef else None!r}, tetap login")

    # 6b.2 password baru sama dengan yang lama
    s, d, _ = api("PUT", "/change-password", {"password_lama": PASSWORD, "password_baru": PASSWORD}, token=token)
    at = ganti_password_form(app_profil(email), PASSWORD, PASSWORD)
    ef = error_field(at)
    cek("6b.2", "Password baru sama persis dengan password lama -> ditolak (400)",
        s == 400 and "be the same as your current password" in d["errors"]["password_baru"] and len(ef) == 1
        and "be the same as your current password" in ef[0],
        f"API -> {s} {d['errors']}; form -> {ef[0] if ef else None!r}")

    # 6b.3 password baru kurang dari 8 karakter
    s, d, _ = api("PUT", "/change-password", {"password_lama": PASSWORD, "password_baru": "abc123"}, token=token)
    at = ganti_password_form(app_profil(email), PASSWORD, "abc123")
    ef = error_field(at)
    cek("6b.3", "Password baru kurang dari 8 karakter -> ditolak, syarat sama dengan register",
        s == 400 and d["errors"]["password_baru"] == "Password must be at least 8 characters." and len(ef) == 1
        and "at least 8 characters" in ef[0] and masuk(email)[0] == 200,
        f"API -> {s} {d['errors']}; form -> {ef[0] if ef else None!r}; password lama masih berlaku")

    # 6b.4 berhasil: sesi ini tetap jalan, device lain dikeluarkan (kebijakan yang dipilih)
    device_lain = masuk(email, ip=ip_baru())[1]["access_token"]
    at = app_profil(email)
    ganti_password_form(at, PASSWORD, "sandibaru123")
    sukses = " ".join(x.value for x in at.success)
    token_sesi = at.session_state["token"]
    s_sesi = api("GET", "/history", token=token_sesi)[0]
    s_lain, d_lain, _ = api("GET", "/history", token=device_lain)
    s_lama = masuk(email, PASSWORD, ip=ip_baru())[0]
    s_baru = masuk(email, "sandibaru123", ip=ip_baru())[0]
    at.session_state["halaman"] = "chat"
    at.run()
    at.chat_input[0].set_value("rekomendasiin sunscreen dong").run()
    masih_chat = at.session_state["halaman"] == "chat" and at.session_state["token"] is not None
    cek("6b.4", "Ganti password berhasil -> sesi yang sedang dipakai tetap jalan, sesi di device lain dikeluarkan "
               "(kebijakan yang dipilih); password lama tidak berlaku lagi",
        "Password changed" in sukses and s_sesi == 200 and s_lain == 401 and "password akun diganti" in d_lain["detail"]
        and s_lama == 401 and s_baru == 200 and masih_chat,
        f"pesan: {sukses!r}; sesi ini (token diperbarui otomatis) -> {s_sesi}, lanjut chat tanpa login ulang={masih_chat}; "
        f"device lain -> {s_lain} {d_lain['detail']!r}; login password lama -> {s_lama}, password baru -> {s_baru}")


# ---------------- BAGIAN 6c: riwayat percakapan ----------------

def tombol_riwayat(at):
    return [b for b in at.button if b.key and str(b.key).startswith("recent_")]


def uji_bagian_6c():
    print("\n=== BAGIAN 6c: Riwayat percakapan ===")

    # 6c.1 riwayat kosong -> ada keterangan state kosong
    email, token, _ = akun_lengkap("Riwayat Kosong")
    s, d, _ = api("GET", "/history", token=token)
    at = isi_login(app("login"), email, PASSWORD)
    teks = " ".join(m.value for m in at.sidebar.markdown)
    cek("6c.1", "Riwayat kosong (user baru belum pernah chat) -> tampil keterangan 'Belum ada percakapan tersimpan'",
        s == 200 and d["conversations"] == [] and "Belum ada percakapan tersimpan" in teks and not tombol_riwayat(at),
        f"GET /history -> {d['conversations']}; sidebar: 'Recents' + \"Belum ada percakapan tersimpan...\" (dulu tidak "
        f"ada keterangan apa pun)")

    # 6c.2 beberapa percakapan -> semua muncul, judul & tanggal benar, terakhir dipakai paling atas
    judul = ["rekomendasiin sunscreen dong", "carikan toner buat kulit kombinasi", "kasih serum buat bekas jerawat"]
    conv = [chat_login(j, token)[1]["conversation_id"] for j in judul]
    chat_login("kasih 5", token, conversation_id=conv[0], konteks=None)  # percakapan pertama dilanjutkan
    riwayat = api("GET", "/history", token=token)[1]["conversations"]
    urutan = [c["id"] for c in riwayat]
    at = isi_login(app("login"), email, PASSWORD)
    label = [b.label for b in tombol_riwayat(at)]
    from datetime import datetime
    bulan = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
    hari_ini = f"{datetime.now().day} {bulan[datetime.now().month - 1]}"
    cek("6c.2", "Beberapa percakapan -> semua muncul dengan judul (potongan pesan pertama) & tanggal, terurut dari "
               "yang terakhir dipakai",
        urutan == [conv[0], conv[2], conv[1]] and [c["title"] for c in riwayat] == [judul[0], judul[2], judul[1]]
        and len(label) == 3 and all(l.endswith(f":gray[{hari_ini}]") for l in label) and label[0].startswith(judul[0])
        and len(riwayat[0]["messages"]) == 4,
        f"3 percakapan dibuat, lalu yang pertama dilanjutkan -> urutan di sidebar: {label}")

    # 6c.3 buka percakapan lama & lanjutkan -> tampil utuh & tersambung ke conversation_id yang sama
    email_b, token_b, _ = akun_lengkap("Lanjut Chat")
    at = isi_login(app("login"), email_b, PASSWORD)
    at.chat_input[0].set_value("rekomendasiin sunscreen dong").run()
    nama_awal = [x["produk"] for x in at.session_state["riwayat_pesan"][-1]["produk"]]
    conv_b = at.session_state["conversation_id"]
    at = isi_login(app("login"), email_b, PASSWORD)  # kunjungan baru
    tombol_riwayat(at)[0].click()
    at.run()
    dipulihkan = list(at.session_state["riwayat_pesan"])
    kartu_utuh = [x["produk"] for x in dipulihkan[-1].get("produk") or []] == nama_awal
    at.chat_input[0].set_value("bandingkan nomor 1 sama 2").run()
    jawab = at.session_state["riwayat_pesan"][-1]
    tabel = jawab.get("perbandingan") or {}
    riwayat_b = api("GET", "/history", token=token_b)[1]["conversations"]
    cek("6c.3", "Buka percakapan lama lalu lanjut chat -> histori tampil utuh (termasuk kartu produk), pesan baru "
               "nyambung ke conversation_id yang SAMA dan ingatan percakapan ikut ('nomor 1' = produk yang sama)",
        len(nama_awal) == 3 and kartu_utuh and at.session_state["conversation_id"] == conv_b and len(riwayat_b) == 1
        and len(riwayat_b[0]["messages"]) == 4 and len(tabel.get("produk", [])) == 2
        and nama_awal[0][:25] in tabel["produk"][0] and nama_awal[1][:25] in tabel["produk"][1],
        f"dibuka lagi di kunjungan baru: {len(dipulihkan)} pesan, kartu 3 produk ikut tampil={kartu_utuh} (dulu cuma "
        f"teks); 'bandingkan nomor 1 sama 2' -> tabel {tabel.get('produk')} = produk nomor 1 & 2 dari jawaban lama; "
        f"tetap 1 percakapan ({len(riwayat_b[0]['messages'])} pesan), bukan percakapan baru")

    # 6c.4 akses riwayat/percakapan milik user lain
    email_c, token_c, _ = akun_lengkap("Penyusup Riwayat")
    s_c, d_c, _ = chat_login("lanjutkan percakapan orang lain", token_c, conversation_id=conv_b)
    at = isi_login(app("login"), email_c, PASSWORD)
    label_c = [b.label for b in tombol_riwayat(at)]
    riwayat_c = api("GET", "/history", token=token_c)[1]["conversations"]
    cek("6c.4", "User lain memakai conversation_id milik user A -> ditolak (403), riwayat & ingatan percakapan A "
               "tidak ikut terkirim, tidak muncul di riwayatnya",
        s_c == 403 and "konteks" not in d_c and "recommendation" not in d_c and riwayat_c == [] and not label_c
        and len(api("GET", "/history", token=token_b)[1]["conversations"][0]["messages"]) == 4,
        f"POST /chat dengan conversation_id milik A -> {s_c} {d_c.get('detail')!r} (isi response hanya pesan error); "
        f"riwayat penyusup: {riwayat_c}; percakapan A tetap 4 pesan")


# ---------------- BAGIAN 6d: kontrol akses admin (RBAC) ----------------

ENDPOINT_ADMIN = [("GET", "/admin/users", None), ("PUT", "/admin/users/xyz", {"is_active": False}),
                  ("PUT", "/admin/products/PRD0001", {"versi": 1})]


def app_admin():
    token = token_admin()
    api("PUT", "/profile", PROFIL, token=token)  # admin juga lewat onboarding kalau profilnya belum ada
    at = isi_login(app("login"), ADMIN["email"], ADMIN["password"])
    at.session_state["halaman"] = "admin_users"
    at.run()
    return at


def uji_bagian_6d():
    print("\n=== BAGIAN 6d: Kontrol akses admin (RBAC) ===")

    # 6d.1 user biasa akses admin
    email, token, _ = akun_lengkap("User Biasa")
    status = [api(m, p, b, token=token)[0] for m, p, b in ENDPOINT_ADMIN]
    at = isi_login(app("login"), email, PASSWORD)
    menu = {b.label for b in at.button}
    at.session_state["halaman"] = "admin_users"
    at.run()
    judul = " ".join(m.value for m in at.markdown)
    cek("6d.1", "User biasa akses endpoint/layar admin -> 403, menu admin tidak terlihat, layar admin tidak bisa dibuka",
        status == [403, 403, 403] and not ({"Dashboard", "User Management", "Product Management"} & menu)
        and "User Management" not in judul and len(at.chat_input) == 1,
        f"GET/PUT endpoint admin dengan token user biasa -> {status}; menu admin di sidebar: tidak ada; memaksa buka "
        f"halaman admin_users -> yang tampil tetap halaman chat")

    # 6d.2 tanpa login
    status = [api(m, p, b)[0] for m, p, b in ENDPOINT_ADMIN]
    cek("6d.2", "Belum login akses endpoint admin -> 401", status == [401, 401, 401],
        f"tanpa token -> {status}")

    # 6d.3 admin nonaktifkan akun lewat layar admin -> user langsung tidak bisa login & sesinya terputus
    email_t, token_t, id_t = akun_lengkap("Target Nonaktif")
    at_user = isi_login(app("login"), email_t, PASSWORD)  # user sedang login
    at_admin = app_admin()
    tombol = next(b for b in at_admin.button if b.key == f"toggle_{id_t}")
    label_awal = tombol.label
    tombol.click()
    at_admin.run()
    aktif_db = baris_db("SELECT is_active FROM users WHERE id=?", id_t)[0]["is_active"]
    s_login, d_login, _ = masuk(email_t, ip=ip_baru())
    at_user.chat_input[0].set_value("rekomendasiin sunscreen dong").run()
    peringatan = " ".join(w.value for w in at_user.warning)
    cek("6d.3", "Admin nonaktifkan user lewat layar admin -> status jadi tidak aktif, tidak bisa login, dan sesi yang "
               "sedang aktif LANGSUNG terputus (tidak menunggu token kedaluwarsa)",
        label_awal == "Deactivate" and aktif_db == 0 and s_login == 401 and "dinonaktifkan" in d_login["detail"]
        and at_user.session_state["halaman"] == "login" and "dinonaktifkan" in peringatan,
        f"klik '{label_awal}' di baris user -> is_active di DB = {aktif_db}; login -> {s_login} {d_login['detail']!r}; "
        f"user yang sedang chat -> langsung dipindah ke halaman login dengan pesan {peringatan!r}")

    # 6d.4 aktifkan lagi -> bisa login normal (sesi lama tetap tidak berlaku)
    at_admin = app_admin()
    tombol = next(b for b in at_admin.button if b.key == f"toggle_{id_t}")
    label_aktifkan = tombol.label
    tombol.click()
    at_admin.run()
    s_login2 = masuk(email_t, ip=ip_baru())[0]
    s_lama, d_lama, _ = api("GET", "/history", token=token_t)
    cek("6d.4", "Admin aktifkan lagi akun yang dinonaktifkan -> user bisa login normal lagi (sesi lama tetap berakhir)",
        label_aktifkan == "Activate" and s_login2 == 200 and s_lama == 401,
        f"klik '{label_aktifkan}' -> login -> {s_login2}; token sesi sebelum dinonaktifkan -> {s_lama} {d_lama['detail']!r}")

    # 6d.5 admin nonaktifkan akun sendiri -> ditolak dengan pesan jelas
    token_a = token_admin()
    id_admin = masuk(ADMIN["email"], ADMIN["password"])[1]["user"]["id"]
    s, d, _ = api("PUT", f"/admin/users/{id_admin}", {"is_active": False}, token=token_a)
    at_admin = app_admin()
    # tabel user per halaman (terbaru di atas) -- akun admin dicari dulu, bukan diasumsikan ada di halaman 1
    at_admin.text_input(key="cari_user").set_value(ADMIN["email"]).run()
    tombol_sendiri = next(b for b in at_admin.button if b.key == f"toggle_{id_admin}")
    cek("6d.5", "Admin coba nonaktifkan akunnya sendiri -> ditolak dengan pesan jelas (tombolnya juga dinonaktifkan), "
               "admin tidak terkunci",
        s == 400 and "your own account" in d["detail"] and tombol_sendiri.disabled and masuk(ADMIN["email"], ADMIN["password"])[0] == 200,
        f"API -> {s} {d['detail']!r}; di layar admin tombol baris akunnya sendiri disabled={tombol_sendiri.disabled}; "
        f"admin tetap bisa login")


# ---------------- BAGIAN 6: integrasi profil chatbot dengan login ----------------

KUNCI_SESI = ("token", "user", "onboarding", "onboarding_selesai", "conversation_id", "riwayat_pesan", "konteks",
              "percakapan_lokal", "halaman", "pesan_login")


def lanjut(at):
    """Lanjutkan sesi yang SAMA di AppTest baru (state sesi aplikasi dibawa utuh).
    Perlu karena AppTest ikut menyimpan widget halaman lama setelah st.rerun()
    (mis. register -> onboarding), dan interaksi berikutnya gagal karenanya."""
    from streamlit.testing.v1 import AppTest
    baru = AppTest.from_file(str(ROOT / "frontend" / "app.py"), default_timeout=60)
    for k in KUNCI_SESI:
        baru.session_state[k] = at.session_state[k]
    baru.run()
    return baru


def isi_onboarding(at, tipe, masalah, budget):
    at.selectbox[0].set_value(tipe)
    at.multiselect[0].set_value(masalah)
    at.number_input[0].set_value(budget)
    at.button[0].click()
    at.run()
    return at


def profil_akun(email):
    u = masuk(email, ip=ip_baru())[1]["user"]
    return u["tipe_kulit"], u["masalah_kulit"], u["budget"]


def uji_bagian_6():
    print("\n=== BAGIAN 6: Integrasi profil chatbot dengan login ===")

    # 6.1 register -> onboarding -> chat, profil tersimpan di akun
    email = email_unik("alur")
    at = isi_register(app("register"), "Alur Baru", email, PASSWORD, PASSWORD)
    judul = " ".join(m.value for m in at.markdown)
    di_onboarding = len(at.selectbox) == 1 and len(at.chat_input) == 0 and "Halo, Alur" in judul
    at = isi_onboarding(lanjut(at), "berminyak", ["jerawat", "kusam"], 120000)
    ke_chat = at.session_state["onboarding_selesai"] and len(at.chat_input) == 1
    tersimpan = profil_akun(email)
    cek("6.1", "Alur register -> langsung form onboarding (sapaan nama) -> setelah diisi masuk chat; profil tersimpan "
               "di akun",
        di_onboarding and ke_chat and tersimpan == ("berminyak", ["jerawat", "kusam"], 120000),
        f"setelah register -> form onboarding 'Halo, Alur'={di_onboarding}; setelah diisi -> halaman chat={ke_chat}; "
        f"profil di akun (dibaca ulang dari backend) = {tersimpan}")

    # 6.2 profil diingat lintas kunjungan -- akun REAL hasil register + onboarding lewat form
    at2 = lanjut(isi_login(app("login"), email, PASSWORD))  # kunjungan baru (sesi baru)
    ob = dict(at2.session_state["onboarding"])
    at2.chat_input[0].set_value("rekomendasiin dong").run()
    konteks = at2.session_state["konteks"] or {}
    cek("6.2", "Kunjungan berikutnya dengan akun REAL (register + onboarding lewat form, bukan simulasi) -> langsung "
               "chat dengan profil terakhir, dan profil itu yang dipakai rekomendasi",
        at2.session_state["onboarding_selesai"] and len(at2.selectbox) == 0
        and (ob["tipe_kulit"], ob["masalah_kulit"], ob["budget"]) == ("berminyak", ["jerawat", "kusam"], 120000)
        and konteks.get("profil", {}).get("tipe_kulit") == "berminyak" and at2.session_state["riwayat_pesan"][-1]["produk"],
        f"login di sesi baru -> tanpa form, profil {ob}; chat pertama memakai profil itu "
        f"({konteks.get('profil')})")

    # 6.3a tamu isi profil & chat, lalu DAFTAR di tengah sesi -> profil & chat ikut pindah
    at = lanjut(isi_onboarding(app(), "sensitif", ["dehidrasi"], 70000))
    at.chat_input[0].set_value("rekomendasiin serum dong").run()
    kartu_tamu = [x["produk"] for x in at.session_state["riwayat_pesan"][-1]["produk"]]
    at.query_params["ke"] = "register"
    at.run()
    email_t = email_unik("tamu")
    at = lanjut(isi_register(lanjut(at), "Dari Tamu", email_t, PASSWORD, PASSWORD))
    ss = at.session_state
    riwayat = api("GET", "/history", token=ss["token"])[1]["conversations"]
    kartu_akun = [x["produk"] for x in (riwayat[0]["messages"][1]["data"] or {}).get("recommendation", [])] if riwayat else []
    conv = ss["conversation_id"]
    at.chat_input[0].set_value("kasih 5").run()
    riwayat2 = api("GET", "/history", token=ss["token"])[1]["conversations"]
    cek("6.3", "Tamu chat lalu daftar/login di tengah sesi -> (keputusan) profil tamu dipakai akun yang belum punya "
               "profil & percakapan yang sedang terbuka ikut tersimpan dan bisa dilanjutkan",
        ss["user"] is not None and ss["onboarding_selesai"] and len(at.selectbox) == 0
        and profil_akun(email_t) == ("sensitif", ["dehidrasi"], 70000)
        and len(riwayat) == 1 and len(riwayat[0]["messages"]) == 2 and kartu_akun == kartu_tamu and conv == riwayat[0]["id"]
        and len(riwayat2) == 1 and len(riwayat2[0]["messages"]) == 4,
        f"tamu isi profil (sensitif, dehidrasi, 70rb) & chat serum -> daftar akun baru: tanpa form ulang, profil akun = "
        f"{profil_akun(email_t)}; riwayat akun berisi percakapan tamu ({len(riwayat[0]['messages']) if riwayat else 0} "
        f"pesan, {len(kartu_akun)} kartu produk sama persis); 'kasih 5' sesudahnya nyambung ke percakapan yang sama "
        f"({len(riwayat2[0]['messages']) if riwayat2 else 0} pesan)")

    # 6.3b akun yang SUDAH punya profil -> profil akun tidak ditimpa profil tamu
    email_p, _, _ = akun_lengkap("Sudah Berprofil")
    at = lanjut(isi_onboarding(app(), "kering", ["penuaan"], 50000))
    at.chat_input[0].set_value("carikan moisturizer").run()
    at.query_params["ke"] = "login"
    at.run()
    at = isi_login(lanjut(at), email_p, PASSWORD)
    ob = at.session_state["onboarding"]
    riwayat = api("GET", "/history", token=at.session_state["token"])[1]["conversations"]
    cek("6.3b", "Tamu login ke akun yang SUDAH punya profil -> profil akun tetap dipakai (tidak ditimpa profil tamu), "
                "percakapan tamu tetap ikut tersimpan",
        ob["tipe_kulit"] == PROFIL["tipe_kulit"] and profil_akun(email_p)[0] == PROFIL["tipe_kulit"]
        and len(riwayat) == 1 and riwayat[0]["title"] == "carikan moisturizer",
        f"profil tamu 'kering' vs profil akun '{PROFIL['tipe_kulit']}' -> dipakai '{ob['tipe_kulit']}'; riwayat akun: "
        f"{[r['title'] for r in riwayat]}")


BAGIAN = {1: uji_bagian_1, 2: uji_bagian_2, 3: uji_bagian_3, 5: uji_bagian_5, "6b": uji_bagian_6b,
          "6c": uji_bagian_6c, "6d": uji_bagian_6d, 6: uji_bagian_6}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bagian", choices=[str(k) for k in BAGIAN])
    args = parser.parse_args()
    print(f"Menyalakan backend uji di port {PORT} (database sementara: {DB_UJI}) ...")
    nyalakan_backend()
    try:
        for nomor, fungsi in BAGIAN.items():
            if args.bagian in (None, str(nomor)):
                fungsi()
    finally:
        matikan_backend()
    lulus = sum(1 for *_, ok, _ in _hasil if ok)
    print(f"\n=== RINGKASAN: {lulus}/{len(_hasil)} skenario PASS ===")
    for kode, deskripsi, ok, _ in _hasil:
        if not ok:
            print(f"  FAIL {kode} {deskripsi}")
    sys.exit(0 if lulus == len(_hasil) else 1)


if __name__ == "__main__":
    main()
