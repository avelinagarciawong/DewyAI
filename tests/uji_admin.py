"""
uji_admin.py -- pengujian otomatis dokumen "Skenario Pengujian Panel Admin".
Tiap skenario dicetak PASS/FAIL beserta buktinya (untuk Bab IV).

Sama seperti uji_login_register.py: skrip ini menyalakan BACKEND SENDIRI
(port 8012) dengan database sementara + MODE_RINGAN (CBF saja, tanpa RAG/LLM),
jadi produk/akun uji tidak mengotori backend/chatbot.db. Katalog awal diisi
dari data/products_final.csv seperti instalasi baru. Layar admin diuji pakai
streamlit.testing (AppTest) yang diarahkan ke backend uji ini.

CARA PAKAI (dari root project):
    python tests/uji_admin.py              # semua bagian
    python tests/uji_admin.py --bagian 2   # bagian tertentu
"""
import argparse
import atexit
import http.client
import itertools
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
PORT = 8012
PORT_KOSONG = 8013  # backend kedua untuk skenario instalasi baru (1.3)
BACKEND_URL = f"http://127.0.0.1:{PORT}"
os.environ["BACKEND_URL"] = BACKEND_URL  # dibaca frontend/core.py saat diimpor AppTest
TMP = Path(tempfile.mkdtemp(prefix="uji_admin_"))
DB_UJI = TMP / "admin_uji.db"
ADMIN = {"email": "admin.uji@example.com", "password": "AdminUji123", "nama": "Admin Uji"}
PASSWORD = "rahasia123"
PROFIL = {"tipe_kulit": "kombinasi", "masalah_kulit": ["jerawat", "kusam"], "budget": 100000,
          "tanpa_batas_budget": False}
_hasil = []
_proses = []


def cek(kode, deskripsi, lulus, bukti=""):
    _hasil.append((kode, deskripsi, bool(lulus), bukti))
    print(f"  [{'PASS' if lulus else 'FAIL'}] {kode} {deskripsi}" + (f"\n         bukti: {bukti}" if bukti else ""))


# ---------------- backend uji ----------------

def nyalakan_backend(port=PORT, db_path=DB_UJI, **env_tambahan):
    env = {**os.environ, "DATABASE_PATH": str(db_path), "MODE_RINGAN": "1", "ADMIN_EMAIL": ADMIN["email"],
           "ADMIN_PASSWORD": ADMIN["password"], "ADMIN_NAMA": ADMIN["nama"], "PYTHONIOENCODING": "utf-8",
           **env_tambahan}
    for k in ("RATE_LIMIT_REGISTER", "RATE_LIMIT_LOGIN_GAGAL", "PRODUK_CSV"):
        if k not in env_tambahan:
            env.pop(k, None)
    log = open(TMP / f"backend_{port}.log", "w", encoding="utf-8")
    proses = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port)],
                              cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    _proses.append(proses)
    batas = time.time() + 240
    while time.time() < batas:
        if proses.poll() is not None:
            sys.exit(f"Backend uji mati saat startup, lihat {TMP / f'backend_{port}.log'}")
        try:
            if api("GET", "/health", port=port)[0] == 200:
                return proses
        except OSError:
            pass
        time.sleep(1)
    sys.exit("Backend uji tidak siap dalam 240 detik")


def matikan(proses):
    if proses.poll() is None:
        proses.terminate()
        try:
            proses.wait(10)
        except subprocess.TimeoutExpired:
            proses.kill()


@atexit.register
def matikan_semua():
    for p in _proses:
        matikan(p)


def api(method, path, body=None, token=None, ip="127.0.0.1", port=PORT, params=None):
    """return: (status, json). ip = alamat sumber (127.x.x.x), supaya
    pendaftaran akun uji tidak menghabiskan jatah rate limit register per IP."""
    if params:
        path = f"{path}?{urlencode({k: v for k, v in params.items() if v is not None})}"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60, source_address=(ip, 0))
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=h)
    resp = conn.getresponse()
    teks = resp.read().decode("utf-8")
    conn.close()
    try:
        return resp.status, json.loads(teks) if teks else {}
    except ValueError:
        return resp.status, {"_mentah": teks}


_nomor_ip = itertools.count(1)


def ip_baru():
    n = next(_nomor_ip)
    return f"127.0.{2 + n // 250}.{1 + n % 250}"


def email_unik(awal="uji"):
    return f"{awal}.{uuid.uuid4().hex[:8]}@example.com"


def daftar(nama="Pengguna Uji", email=None):
    email = email or email_unik()
    s, d = api("POST", "/register", {"nama": nama, "email": email, "password": PASSWORD}, ip=ip_baru())
    assert s == 201, (s, d)
    return d["id"], email


def masuk(email, password=PASSWORD, port=PORT):
    return api("POST", "/login", {"email": email, "password": password}, ip=ip_baru(), port=port)


def token_admin(port=PORT):
    return masuk(ADMIN["email"], ADMIN["password"], port=port)[1]["access_token"]


def akun_lengkap(nama="Pengguna Uji"):
    """Akun REAL (register + login) yang sudah mengisi profil kulit."""
    uid, email = daftar(nama)
    token = masuk(email)[1]["access_token"]
    api("PUT", "/profile", PROFIL, token=token)
    return uid, email, token


def baris_db(sql, *param, db_path=DB_UJI):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, param).fetchall()]
    finally:
        conn.close()


def satu_db(sql, *param, db_path=DB_UJI):
    return next(iter(baris_db(sql, *param, db_path=db_path)[0].values()))


def chat(pesan, token=None, konteks=None, onboarding=None, conversation_id=None):
    body = {"message": pesan, "onboarding": onboarding or PROFIL, "konteks": konteks,
            "conversation_id": conversation_id}
    return api("POST", "/chat", body, token=token)


# ---------------- frontend (AppTest) ----------------

def app(ke=None):
    from streamlit.testing.v1 import AppTest
    if str(ROOT / "frontend") not in sys.path:  # `streamlit run` menambahkan ini otomatis, AppTest tidak
        sys.path.insert(0, str(ROOT / "frontend"))
    at = AppTest.from_file(str(ROOT / "frontend" / "app.py"), default_timeout=90)
    if ke:
        at.query_params["ke"] = ke
    at.run()
    return at


def app_login(email, password, halaman=None):
    at = app("login")
    at.text_input[0].set_value(email)
    at.text_input[1].set_value(password)
    at.button[0].click()
    at.run()
    if halaman:
        at.session_state["halaman"] = halaman
        at.run()
    return at


def app_admin(halaman="admin_users"):
    api("PUT", "/profile", PROFIL, token=token_admin())  # admin juga lewat onboarding kalau profilnya belum ada
    return app_login(ADMIN["email"], ADMIN["password"], halaman)


def markdown(at):
    return [m.value for m in at.markdown]


def angka_ringkasan(at):
    """{label: angka} dari blok ringkasan (stat tile) yang sedang tampil."""
    html = " ".join(markdown(at))
    return {label: int(n.replace(".", "")) for label, n in
            re.findall(r'</span>([^<]+)</div><div class="stat-num">([\d.]+)</div>', html)}


def baris_user(at):
    """Isi tabel user yang tampil: [{nama, email, role, status}] sesuai urutan."""
    md, hasil = markdown(at), []
    for i, v in enumerate(md):
        if v.startswith('<span class="td-nama">'):
            teks = [re.sub(r"<[^>]+>", "", x) for x in md[i:i + 4]]
            hasil.append(dict(zip(("nama", "email", "role", "status"), teks)))
    return hasil


def info_halaman(at):
    """'Showing 1–20 of 961 products · Page 1 / 49' (keterangan jumlah + pill nomor halaman)."""
    teks = [re.sub(r"<[^>]+>", "", v) for v in markdown(at) if 'class="info-halaman"' in v or 'class="pill-halaman"' in v]
    return " · ".join(teks)


def tombol(at, key):
    return next((b for b in at.button if b.key == key), None)


# ---------------- BAGIAN 1: blok ringkasan admin ----------------

def uji_bagian_1():
    print("\n=== BAGIAN 1: Blok ringkasan admin (di atas tabel User Management) ===")

    # data nyata: 2 user + 1 percakapan tersimpan
    _, _, token_u = akun_lengkap("Ringkasan Satu")
    akun_lengkap("Ringkasan Dua")
    chat("rekomendasiin sunscreen dong", token=token_u)

    at = app_admin("admin_users")
    md = markdown(at)
    i_blok = next((i for i, v in enumerate(md) if 'class="stat-grid"' in v), None)
    i_tabel = next((i for i, v in enumerate(md) if v == '<span class="th">Name</span>'), None)
    angka = angka_ringkasan(at)
    cek("1.1", "Admin buka layar User Management -> blok ringkasan (total user, produk aktif, total percakapan) "
               "tampil di ATAS tabel user, bukan layar terpisah",
        i_blok is not None and i_tabel is not None and i_blok < i_tabel
        and {"Total users", "Active products", "Total conversations"} <= set(angka)
        and at.session_state["halaman"] == "admin_users",
        f"halaman aktif '{at.session_state['halaman']}', urutan elemen: blok ringkasan #{i_blok} < kepala tabel "
        f"#{i_tabel}; isi blok: {angka}")

    # 1.2 angka == hitungan langsung dari database, dan ikut berubah saat data berubah
    def db_sekarang():
        return {"Total users": satu_db("SELECT COUNT(*) FROM users"),
                "Active products": satu_db("SELECT COUNT(*) FROM products WHERE is_active=1"),
                "Total conversations": satu_db("SELECT COUNT(*) FROM conversations")}
    awal_db = db_sekarang()
    cocok_awal = {k: angka.get(k) for k in awal_db} == awal_db
    token = token_admin()
    id_produk = baris_db("SELECT id FROM products WHERE is_active=1 LIMIT 1")[0]["id"]
    api("PUT", f"/admin/products/{id_produk}/status", {"is_active": False}, token=token)
    daftar("Ringkasan Tiga")
    chat("carikan toner", token=token_u)
    angka2 = angka_ringkasan(app_admin("admin_users"))
    akhir_db = db_sekarang()
    api("PUT", f"/admin/products/{id_produk}/status", {"is_active": True}, token=token)  # kembalikan
    cek("1.2", "Angka ringkasan akurat (sama dengan hitungan langsung dari database) dan bukan angka tetap -- "
               "ikut berubah saat user/produk/percakapan berubah",
        cocok_awal and {k: angka2.get(k) for k in akhir_db} == akhir_db
        and angka2["Total users"] == angka["Total users"] + 1 and angka2["Active products"] == angka["Active products"] - 1
        and angka2["Total conversations"] == angka["Total conversations"] + 1,
        f"tampil {angka} vs hitung DB {awal_db}; setelah +1 user, 1 produk dinonaktifkan, +1 percakapan -> tampil "
        f"{angka2} vs DB {akhir_db}")

    # 1.3 instalasi baru: database kosong & belum ada dataset produk
    db_kosong = TMP / "kosong.db"
    proses = nyalakan_backend(PORT_KOSONG, db_kosong, PRODUK_CSV=str(TMP / "tidak_ada.csv"))
    try:
        s, r = api("GET", "/admin/ringkasan", token=token_admin(PORT_KOSONG), port=PORT_KOSONG)
        s_chat, d_chat = api("POST", "/chat", {"message": "rekomendasiin moisturizer", "onboarding": PROFIL},
                             port=PORT_KOSONG)
        import core  # modul frontend yang sudah dimuat AppTest -- diarahkan sementara ke backend kosong
        core.BACKEND_URL = f"http://127.0.0.1:{PORT_KOSONG}"
        try:
            at0 = app_login(ADMIN["email"], ADMIN["password"])
            if not at0.session_state["onboarding_selesai"]:
                api("PUT", "/profile", PROFIL, token=at0.session_state["token"], port=PORT_KOSONG)
                at0 = app_login(ADMIN["email"], ADMIN["password"])
            at0.session_state["halaman"] = "admin_users"
            at0.run()
            angka0 = angka_ringkasan(at0)
            error0 = [e.value for e in at0.error] + [e.value for e in at0.exception]
        finally:
            core.BACKEND_URL = BACKEND_URL
    finally:
        matikan(proses)
    cek("1.3", "Instalasi baru (database kosong, belum ada dataset produk) -> blok menampilkan 0 dengan jelas, bukan "
               "error atau kosong; chatbot juga tidak error",
        s == 200 and r["total_produk"] == 0 and r["produk_aktif"] == 0 and r["total_percakapan"] == 0
        and angka0 == {"Total users": 1, "Active products": 0, "Total conversations": 0} and not error0
        and s_chat == 200 and d_chat["recommendation"] == [],
        f"GET /admin/ringkasan -> {s} {r}; tampil di layar {angka0}, error di layar: {error0 or 'tidak ada'}; "
        f"/chat di katalog kosong -> {s_chat}, {d_chat.get('explanation', '')[:90]!r}")


# ---------------- BAGIAN 2: kelola user ----------------

def semua_halaman_ui(at):
    """Klik 'Berikutnya' sampai halaman terakhir. return: (baris per halaman, info tiap halaman)."""
    halaman, info = [baris_user(at)], [info_halaman(at)]
    while (b := tombol(at, "hal_users_berikut")) is not None and not b.disabled:
        b.click()
        at.run()
        halaman.append(baris_user(at))
        info.append(info_halaman(at))
    return halaman, info


def uji_bagian_2():
    print("\n=== BAGIAN 2: Kelola user (layar 09) ===")
    for i in range(25 - satu_db("SELECT COUNT(*) FROM users")):  # > 1 halaman (20 per halaman)
        daftar(f"Anggota Uji {i:02d}")
    total_db = satu_db("SELECT COUNT(*) FROM users")
    email_db = {r["email"] for r in baris_db("SELECT email FROM users")}

    at = app_admin("admin_users")
    per_hal, infos = semua_halaman_ui(at)
    semua = [b for h in per_hal for b in h]
    lengkap = all(b["nama"] and "@" in b["email"] and b["role"] in ("User", "Admin")
                  and b["status"] in ("Active", "Inactive") for b in semua)
    cek("2.1", "Lihat daftar semua user -> tabel berisi nama, email, role, status; SEMUA user terbaca (bukan sebagian)",
        lengkap and {b["email"] for b in semua} == email_db and len(semua) == total_db,
        f"{total_db} user di database, {len(semua)} baris terbaca lewat tabel (semua halaman), email sama persis: "
        f"{ {b['email'] for b in semua} == email_db }; contoh baris: {semua[0]}")

    cek("2.2", "User lebih dari 1 halaman -> ada pagination yang jelas (20 per halaman, keterangan jumlah), tidak "
               "ditumpuk 1 halaman dan tidak terpotong diam-diam",
        len(per_hal) >= 2 and len(per_hal[0]) == 20 and len(semua) == len({b["email"] for b in semua})
        and infos[0].startswith(f"Showing 1–20 of {total_db} users"),
        f"{len(per_hal)} halaman, isi per halaman {[len(h) for h in per_hal]}, tanpa duplikat; keterangan: "
        f"{infos[0]!r} ... {infos[-1]!r}")

    # 2.3 cari
    uid_c, email_c = daftar("Citra Kirana Unik")
    at = app_admin("admin_users")
    hasil = {}
    for q in ("kirana", "KIRANA UNIK", email_c.split("@")[0][-8:], "zzz-tidak-ada"):
        at.text_input(key="cari_user").set_value(q).run()
        hasil[q] = baris_user(at)
    pesan_kosong = any("No users match" in v for v in markdown(at))
    cek("2.3", "Cari user berdasarkan nama/email -> hasil akurat, tidak peka huruf besar/kecil; tidak ada hasil -> "
               "pesan jelas",
        all(len(hasil[q]) == 1 and hasil[q][0]["email"] == email_c for q in list(hasil)[:3])
        and hasil["zzz-tidak-ada"] == [] and pesan_kosong,
        f"hasil per kata kunci: { {q: [b['nama'] for b in v] for q, v in hasil.items()} }; tanpa hasil -> "
        f"pesan 'No users match ...' tampil={pesan_kosong}")

    # 2.4 nonaktifkan lewat tombol -> status berubah saat itu juga
    uid_t, email_t, token_t = akun_lengkap("Target Toggle")
    at = app_admin("admin_users")
    at.text_input(key="cari_user").set_value("Target Toggle").run()
    label_awal = tombol(at, f"toggle_{uid_t}").label
    tombol(at, f"toggle_{uid_t}").click()
    at.run()
    status_layar = baris_user(at)[0]["status"]
    label_baru = tombol(at, f"toggle_{uid_t}").label
    s_login, d_login = masuk(email_t)
    cek("2.4", "Nonaktifkan 1 user -> status di tabel berubah SAAT ITU JUGA (tanpa refresh manual) dan user langsung "
               "tidak bisa login",
        label_awal == "Deactivate" and status_layar == "Inactive" and label_baru == "Activate"
        and satu_db("SELECT is_active FROM users WHERE id=?", uid_t) == 0 and s_login == 401,
        f"klik '{label_awal}' -> baris yang sama langsung '{status_layar}', tombol jadi '{label_baru}'; login -> "
        f"{s_login} {d_login.get('detail')!r}")

    # 2.6 sesi yang sedang berjalan (akun yang tadi dinonaktifkan masih memegang token)
    s_hist, d_hist = api("GET", "/history", token=token_t)
    s_chat, d_chat = chat("carikan serum", token=token_t)
    cek("2.6", "Efek nonaktif ke sesi yang SEDANG berjalan -> perilaku eksplisit: sesi langsung terputus paksa "
               "(request berikutnya ditolak 401 dengan pesan 'dinonaktifkan'), tidak menunggu token kedaluwarsa",
        s_hist == 401 and s_chat == 401 and "dinonaktifkan" in d_hist.get("detail", ""),
        f"token yang masih berlaku (belum kedaluwarsa) setelah akun dinonaktifkan: GET /history -> {s_hist} "
        f"{d_hist.get('detail')!r}; POST /chat -> {s_chat}. (Di layar, user dipindah ke halaman login -- diuji di "
        f"uji_login_register.py 6d.3)")

    # 2.5 aktifkan kembali
    tombol(at, f"toggle_{uid_t}").click()
    at.run()
    status_layar = baris_user(at)[0]["status"]
    s_login2 = masuk(email_t)[0]
    cek("2.5", "Aktifkan kembali user yang nonaktif -> status kembali Aktif dan user bisa login normal lagi",
        status_layar == "Active" and tombol(at, f"toggle_{uid_t}").label == "Deactivate" and s_login2 == 200,
        f"klik 'Aktifkan' -> status '{status_layar}'; login -> {s_login2}")

    # 2.7 admin menonaktifkan admin lain
    uid_b, email_b = daftar("Admin Kedua")
    with sqlite3.connect(DB_UJI) as conn:  # tidak ada endpoint promosi admin: dibuat langsung di database
        conn.execute("UPDATE users SET role='Admin' WHERE id=?", (uid_b,))
    id_a = masuk(ADMIN["email"], ADMIN["password"])[1]["user"]["id"]
    at = app_admin("admin_users")
    at.text_input(key="cari_user").set_value("Admin").run()
    tombol_b, tombol_a = tombol(at, f"toggle_{uid_b}"), tombol(at, f"toggle_{id_a}")
    s_b, _ = api("PUT", f"/admin/users/{uid_b}", {"is_active": False}, token=token_admin())
    login_b = masuk(email_b)[0]
    api("PUT", f"/admin/users/{uid_b}", {"is_active": True}, token=token_admin())
    # dua admin saling menonaktifkan pada saat yang sama -> tetap tersisa minimal 1 admin aktif
    admin_tersisa = []
    for _ in range(5):
        tok_a, tok_b = token_admin(), masuk(email_b)[1]["access_token"]
        hasil_serentak = []
        th = [threading.Thread(target=lambda t, u: hasil_serentak.append(
            api("PUT", f"/admin/users/{u}", {"is_active": False}, token=t)[0]), args=args)
              for args in ((tok_a, uid_b), (tok_b, id_a))]
        [t.start() for t in th]
        [t.join() for t in th]
        admin_tersisa.append(satu_db("SELECT COUNT(*) FROM users WHERE role='Admin' AND is_active=1"))
        with sqlite3.connect(DB_UJI) as conn:
            conn.execute("UPDATE users SET is_active=1 WHERE role='Admin'")
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ["DATABASE_PATH"] = str(DB_UJI)
    import db as db_backend  # modul database backend, diarahkan ke database uji
    db_backend.DB_FILE = DB_UJI
    with sqlite3.connect(DB_UJI) as conn:
        conn.execute("UPDATE users SET is_active=0 WHERE id=?", (uid_b,))  # admin utama jadi satu-satunya admin aktif
    hasil_terakhir = db_backend.set_status_aktif(id_a, False)
    aktif_a = satu_db("SELECT is_active FROM users WHERE id=?", id_a)
    with sqlite3.connect(DB_UJI) as conn:
        conn.execute("UPDATE users SET is_active=1 WHERE id=?", (uid_b,))
    cek("2.7", "Admin A menonaktifkan admin B -> diizinkan, TAPI sistem selalu menyisakan minimal 1 admin aktif "
               "(juga saat 2 admin saling menonaktifkan bersamaan)",
        not tombol_b.disabled and tombol_a.disabled and s_b == 200 and login_b == 401 and min(admin_tersisa) >= 1
        and hasil_terakhir == "admin_terakhir" and aktif_a == 1,
        f"tombol di baris admin B aktif (disabled={tombol_b.disabled}), di baris akun sendiri disabled="
        f"{tombol_a.disabled}; A nonaktifkan B -> {s_b}, B login -> {login_b}; 5x uji saling-nonaktifkan serentak "
        f"-> admin aktif tersisa {admin_tersisa}; menonaktifkan admin aktif terakhir -> '{hasil_terakhir}' "
        f"(is_active tetap {aktif_a})")

    # 2.8 nonaktifkan diri sendiri
    s, d = api("PUT", f"/admin/users/{id_a}", {"is_active": False}, token=token_admin())
    cek("2.8", "Admin nonaktifkan akunnya sendiri -> ditolak dengan pesan jelas (tombolnya juga dinonaktifkan), admin "
               "tidak terkunci",
        s == 400 and "your own account" in d["detail"] and tombol_a.disabled
        and masuk(ADMIN["email"], ADMIN["password"])[0] == 200,
        f"API -> {s} {d['detail']!r}; tombol di baris sendiri disabled={tombol_a.disabled}; admin tetap bisa login")

    # 2.9 role yang tampil == role di database (semua halaman)
    at = app_admin("admin_users")
    per_hal, _ = semua_halaman_ui(at)
    role_db = {r["email"]: r["role"] for r in baris_db("SELECT email, role FROM users")}
    salah = [b for h in per_hal for b in h if role_db.get(b["email"]) != b["role"]]
    n_admin = sum(b["role"] == "Admin" for h in per_hal for b in h)
    cek("2.9", "Kolom role di tabel konsisten dengan role yang tersimpan di database (User vs Admin)",
        not salah and n_admin == sum(v == "Admin" for v in role_db.values()) >= 2,
        f"{sum(len(h) for h in per_hal)} baris dicek, salah label: {salah or 'tidak ada'}; admin tampil {n_admin} "
        f"= admin di DB")


# ---------------- BAGIAN 3: kelola produk -- lihat & cari ----------------

LABEL_TIPE = {"berminyak": "Berminyak", "kering": "Kering", "kombinasi": "Kombinasi", "sensitif": "Sensitif",
              "normal": "Normal"}


def baris_produk(at):
    """Isi tabel produk yang tampil: [{id, nama, kategori, harga, tipe, status, tanda}] sesuai urutan."""
    md, hasil = markdown(at), []
    for i, v in enumerate(md):
        if v.startswith('<div class="td-nama"'):
            teks = [re.sub(r"<[^>]+>", " ", x).split() for x in md[i:i + 5]]
            hasil.append({"id": re.search(r"PRD\d+", v).group(0), "nama": re.sub(r"<[^>]+>", "", v.split("</div>")[0]),
                          "kategori": " ".join(teks[1]), "harga": " ".join(teks[2]), "tipe": " ".join(teks[3]),
                          "status": " ".join(teks[4]), "tanda": re.findall(r'class="pill (pill-\w+)"', v)})
    return hasil


def app_produk():
    at = app_admin("admin_produk")
    return at


def semua_produk_api(token, **filter_):
    """Seluruh hasil filter lewat API (semua halaman) -- pembanding isi tabel."""
    hasil, hal = [], 1
    while True:
        s, d = api("GET", "/admin/products", token=token, params={**filter_, "halaman": hal, "per_halaman": 100})
        hasil += d["produk"]
        if hal >= d["jumlah_halaman"]:
            return hasil, d["total"]
        hal += 1


def katalog_db():
    return baris_db("SELECT id, nama_produk, brand, kategori, tipe_kulit_cocok, is_active FROM products")


def punya_tipe(tag, tipe):
    return tipe in [t.strip() for t in (tag or "").split(";")]


def uji_bagian_3():
    print("\n=== BAGIAN 3: Kelola produk -- lihat & cari (layar 10) ===")
    token = token_admin()
    kat = katalog_db()
    per_id = {p["id"]: p for p in kat}

    at = app_produk()
    kepala = [re.sub(r"<[^>]+>", "", v) for v in markdown(at) if v.startswith('<span class="th">')]
    rows = baris_produk(at)
    contoh = rows[0]
    asli = per_id[contoh["id"]]
    cek("3.1", "Admin buka kelola produk -> tabel muncul dengan kolom minimal nama, kategori, harga, tipe kulit cocok, "
               "status aktif, isinya sesuai database",
        {"Product name", "Category", "Price", "Suitable skin types", "Status"} <= set(kepala) and len(rows) == 20
        and contoh["nama"] == asli["nama_produk"]
        and contoh["kategori"] == __import__("core").KATEGORI_EN[asli["kategori"]]
        and contoh["status"] == "Active",
        f"kolom: {kepala}; baris pertama: {contoh}")

    # 3.2 pagination: 961 produk
    total_db = len(kat)
    info1 = info_halaman(at)
    tombol(at, "hal_produk_berikut").click()
    at.run()
    rows2, info2 = baris_produk(at), info_halaman(at)
    jumlah_hal = -(-total_db // 20)
    at.session_state["hal_produk"] = jumlah_hal
    at.run()
    rows_akhir, info_akhir = baris_produk(at), info_halaman(at)
    semua, total_api = semua_produk_api(token)
    ids = [p["id"] for p in semua]
    cek("3.2", f"{total_db} produk -> WAJIB ada pagination (20 per halaman), semua produk tetap terjangkau tanpa ada "
               f"yang terpotong diam-diam",
        info1.startswith(f"Showing 1–20 of {angka_id(total_db)} products") and len(rows2) == 20
        and not ({r["id"] for r in rows} & {r["id"] for r in rows2}) and info2.startswith("Showing 21–40")
        and len(rows_akhir) == total_db - (jumlah_hal - 1) * 20 and f"Page {jumlah_hal} / {jumlah_hal}" in info_akhir
        and len(ids) == len(set(ids)) == total_db == total_api,
        f"halaman 1: {info1!r}; klik Berikutnya: {info2!r} (20 baris lain); halaman terakhir: {info_akhir!r} "
        f"({len(rows_akhir)} baris); seluruh halaman lewat API: {len(set(ids))} id unik = {total_db} produk di DB")

    # 3.3 - 3.5 filter
    def pakai_filter(kategori="", tipe="", status="semua", q=""):
        a = app_produk()
        a.text_input(key="cari_produk").set_value(q)
        a.selectbox(key="filter_kategori").set_value(kategori)
        a.selectbox(key="filter_tipe").set_value(tipe)
        a.selectbox(key="filter_status").set_value(status)
        a.run()
        return a

    a = pakai_filter(kategori="serum")
    r, info = baris_produk(a), info_halaman(a)
    semua, total = semua_produk_api(token, kategori="serum")
    n_db = sum(p["kategori"] == "serum" for p in kat)
    cek("3.3", "Filter kategori -> tabel HANYA menampilkan produk kategori itu",
        r and all(x["kategori"] == "Serum" for x in r) and all(p["kategori"] == "serum" for p in semua)
        and total == n_db and f"of {n_db} products" in info,
        f"filter 'serum': {info!r}; kategori di layar: {sorted({x['kategori'] for x in r})}; seluruh hasil {total} = "
        f"{n_db} produk serum di DB")

    a = pakai_filter(tipe="kering")
    r, info = baris_produk(a), info_halaman(a)
    semua, total = semua_produk_api(token, tipe_kulit="kering")
    n_db = sum(punya_tipe(p["tipe_kulit_cocok"], "kering") for p in kat)
    cek("3.4", "Filter tipe kulit -> tabel HANYA menampilkan produk yang tipe_kulit_cocok-nya memuat tipe itu",
        r and all("Kering" in x["tipe"] for x in r) and all("kering" in p["tipe_kulit_cocok"] for p in semua)
        and total == n_db,
        f"filter 'kering': {info!r}; semua baris memuat 'Kering'; seluruh hasil {total} = {n_db} produk di DB")

    a = pakai_filter(kategori="toner", tipe="sensitif")
    r, info = baris_produk(a), info_halaman(a)
    semua, total = semua_produk_api(token, kategori="toner", tipe_kulit="sensitif")
    n_db = sum(p["kategori"] == "toner" and punya_tipe(p["tipe_kulit_cocok"], "sensitif") for p in kat)
    n_kat = sum(p["kategori"] == "toner" for p in kat)
    cek("3.5", "Filter kategori + tipe kulit sekaligus -> keduanya berlaku bersamaan (AND), tidak ada yang diabaikan",
        r and all(x["kategori"] == "Toner" and "Sensitif" in x["tipe"] for x in r) and total == n_db < n_kat,
        f"toner + sensitif: {info!r}; {total} produk (= hitungan DB {n_db}), lebih sedikit dari semua toner ({n_kat}) "
        f"-> filter tipe tidak diabaikan")

    # 3.6 kombinasi tanpa hasil
    kombinasi = next(((k, t) for k in sorted({p["kategori"] for p in kat}) for t in LABEL_TIPE
                      if not any(p["kategori"] == k and punya_tipe(p["tipe_kulit_cocok"], t) for p in kat)),
                     None)
    a = pakai_filter(kategori=kombinasi[0], tipe=kombinasi[1]) if kombinasi else pakai_filter(kategori="serum",
                                                                                              status="nonaktif")
    pesan = [re.sub(r"<[^>]+>", "", v) for v in markdown(a) if 'class="kosong-tabel"' in v]
    cek("3.6", "Filter yang tidak menghasilkan apa-apa -> tampil 'tidak ada produk yang cocok' secara eksplisit, "
               "bukan tabel kosong tanpa keterangan",
        not baris_produk(a) and pesan and "No products match" in pesan[0],
        f"filter {kombinasi or ('serum', 'nonaktif')} -> 0 baris, pesan: {pesan}")

    # 3.7 cari nama (sebagian, huruf besar/kecil bebas)
    hasil = {}
    for q in ("niacinamide", "NIACINAMIDE", "NiAcInAmIdE serum"):
        a = pakai_filter(q=q)
        semua, total = semua_produk_api(token, q=q)
        n_db = sum(all(k.lower() in f"{p['nama_produk']} {p['brand'] or ''}".lower() for k in q.split()) for p in kat)
        hasil[q] = (total, n_db, all(all(k.lower() in (x["nama"] + " " + (per_id[x["id"]]["brand"] or "")).lower()
                                         for k in q.split()) for x in baris_produk(a)), info_halaman(a))
    cek("3.7", "Cari produk berdasarkan sebagian nama -> hasil akurat dan tidak peka huruf besar/kecil",
        all(t == n and t > 0 and ok for t, n, ok, _ in hasil.values())
        and hasil["niacinamide"][0] == hasil["NIACINAMIDE"][0],
        f"{ {q: f'{t} hasil (DB: {n}), semua baris memuat kata kunci={ok}' for q, (t, n, ok, _) in hasil.items()} }")

    # 3.8 status nonaktif terlihat jelas
    pid = semua_produk_api(token, kategori="serum")[0][0]["id"]
    api("PUT", f"/admin/products/{pid}/status", {"is_active": False}, token=token)
    a = pakai_filter(kategori="serum")
    baris = next((x for x in baris_produk(a) if x["id"] == pid), None)
    label = tombol(a, f"status_{pid}").help if baris else None
    a2 = pakai_filter(kategori="serum", status="nonaktif")
    di_nonaktif = [x["id"] for x in baris_produk(a2)]
    api("PUT", f"/admin/products/{pid}/status", {"is_active": True}, token=token)
    cek("3.8", "Produk yang sudah dinonaktifkan tetap terlihat di tabel dengan status yang jelas (tidak disembunyikan "
               "diam-diam), dan bisa difilter",
        baris is not None and baris["status"] == "Inactive" and label == "Activate product" and di_nonaktif == [pid],
        f"{pid} dinonaktifkan -> tetap ada di tabel (filter 'semua status') dengan status '{baris and baris['status']}', "
        f"tombol '{label}'; filter status 'Nonaktif' -> {di_nonaktif}")


def angka_id(n):
    return f"{n:,}".replace(",", ".")


# ---------------- BAGIAN 4: tambah produk ----------------

PRODUK_VALID = {"nama_produk": "Embun Mist Uji Segar", "brand": "Merek Uji", "kategori": "mist", "harga": 45000,
                "tipe_kulit_cocok": ["kering"], "masalah_kulit_cocok": ["jerawat", "dehidrasi"],
                "kandungan": "Niacinamide, Centella Asiatica",
                "deskripsi": "Face mist untuk kulit kering berjerawat, menenangkan jerawat dan melembapkan kulit.",
                "link": "https://shopee.co.id/embun-mist-uji-segar"}
PROFIL_MIST = {"tipe_kulit": "kering", "masalah_kulit": ["jerawat", "dehidrasi"], "budget": 100000,
               "tanpa_batas_budget": False}
KUNCI_SESI = ("token", "user", "onboarding", "onboarding_selesai", "conversation_id", "riwayat_pesan", "konteks",
              "percakapan_lokal", "halaman", "pesan_login", "produk_mode", "produk_pesan", "produk_edit",
              "opsi_produk", "hal_produk", "hal_produk_filter")


def lanjut(at):
    """Sesi yang SAMA di AppTest baru -- AppTest ikut menyimpan elemen halaman
    lama setelah st.rerun() (mis. form -> tabel), jadi hasil akhirnya dibaca
    dari AppTest baru dengan state sesi yang dibawa utuh."""
    from streamlit.testing.v1 import AppTest
    baru = AppTest.from_file(str(ROOT / "frontend" / "app.py"), default_timeout=90)
    for k in KUNCI_SESI:
        if k in at.session_state:
            baru.session_state[k] = at.session_state[k]
    baru.run()
    return baru


def app_form_tambah():
    at = app_admin("admin_produk")
    tombol(at, "tambah_produk").click()
    at.run()
    return at


def isi_form(at, kunci, isian, label_simpan):
    opsi_tipe = ["berminyak", "kering", "kombinasi", "sensitif", "normal"]
    opsi_masalah = ["jerawat", "kusam", "hiperpigmentasi", "penuaan", "kemerahan_iritasi", "dehidrasi"]
    for field, nilai in isian.items():
        if field in ("nama_produk", "brand", "link"):
            at.text_input(key=f"{kunci}_{'nama' if field == 'nama_produk' else field}").set_value(nilai or "")
        elif field == "kategori":
            at.selectbox(key=f"{kunci}_kategori").set_value(nilai or "")
        elif field == "harga":
            at.number_input(key=f"{kunci}_harga").set_value(nilai)
        elif field in ("kandungan", "deskripsi"):
            at.text_area(key=f"{kunci}_{field}").set_value(nilai or "")
        elif field == "tipe_kulit_cocok":
            for t in opsi_tipe:
                at.checkbox(key=f"{kunci}_tipe_{t}").set_value(t in nilai)
        elif field == "masalah_kulit_cocok":
            for m in opsi_masalah:
                at.checkbox(key=f"{kunci}_masalah_{m}").set_value(m in nilai)
    next(b for b in at.button if b.label == label_simpan).click()
    at.run()
    return at


def error_form(at):
    return [re.sub(r"<[^>]+>", "", m) for m in markdown(at) if m.startswith('<div class="field-error">')]


def jumlah_produk():
    return satu_db("SELECT COUNT(*) FROM products")


def tambah_api(token, **isian):
    return api("POST", "/admin/products", {**PRODUK_VALID, **isian}, token=token)


def id_rekomendasi(respons):
    return [p["id"] for p in respons.get("recommendation") or []]


def uji_bagian_4():
    print("\n=== BAGIAN 4: Kelola produk -- tambah produk baru (layar 10) ===")
    token = token_admin()

    # 4.1 lewat form, lengkap & valid
    n0 = jumlah_produk()
    at = isi_form(app_form_tambah(), "fp_tambah", PRODUK_VALID, "Save product")
    sukses = [s.value for s in at.success]
    at = lanjut(at)
    baris_atas = baris_produk(at)[0]
    db_baru = baris_db("SELECT * FROM products ORDER BY rowid DESC LIMIT 1")[0]
    id_mist = db_baru["id"]
    cek("4.1", "Tambah produk lengkap & valid lewat form -> tersimpan dan langsung kelihatan di tabel (paling atas)",
        jumlah_produk() == n0 + 1 and any("Product added" in s for s in sukses)
        and baris_atas["id"] == id_mist and baris_atas["nama"] == PRODUK_VALID["nama_produk"]
        and db_baru["kategori"] == "mist" and db_baru["tipe_kulit_cocok"] == "kering"
        and db_baru["masalah_kulit_cocok"] == "jerawat; dehidrasi" and db_baru["harga"] == 45000
        and db_baru["is_active"] == 1,
        f"pesan: {sukses}; baris teratas tabel: {baris_atas['id']} '{baris_atas['nama']}' ({baris_atas['kategori']}, "
        f"{baris_atas['harga']}, {baris_atas['tipe']}); di DB: tipe='{db_baru['tipe_kulit_cocok']}', "
        f"masalah='{db_baru['masalah_kulit_cocok']}'")

    # 4.16 produk baru LANGSUNG dipakai chatbot (tanpa restart)
    s1, d1 = chat("carikan face mist dong", onboarding=PROFIL_MIST)
    s2, d2 = chat(f"info produk {PRODUK_VALID['nama_produk']}", onboarding=PROFIL_MIST)
    cek("4.16", "Produk baru langsung kepakai di rekomendasi (index TF-IDF di-fit ulang saat disimpan, bukan cuma "
                "tersimpan di database) -- juga dikenali saat ditanya namanya",
        s1 == 200 and id_mist in id_rekomendasi(d1) and s2 == 200 and d2.get("tipe") == "info_produk"
        and PRODUK_VALID["nama_produk"] in d2["explanation"],
        f"tepat setelah disimpan (backend tidak di-restart): 'carikan face mist dong' (profil kering, jerawat+dehidrasi) "
        f"-> {id_rekomendasi(d1)} (produk baru {id_mist} ikut, urutan ke-"
        f"{id_rekomendasi(d1).index(id_mist) + 1 if id_mist in id_rekomendasi(d1) else '-'}); "
        f"'info produk {PRODUK_VALID['nama_produk']}' -> jawaban {d2.get('tipe')}: "
        f"{d2.get('explanation', '')[:110]!r}")

    # 4.2 & 4.3 & 4.6 & 4.9 lewat form -> pesan per field, tidak tersimpan
    def tolak_form(**ubah):
        n = jumlah_produk()
        a = isi_form(app_form_tambah(), "fp_tambah", {**PRODUK_VALID, **ubah}, "Save product")
        return error_form(a), jumlah_produk() == n

    err, tetap = tolak_form(nama_produk="   ")
    s, d = tambah_api(token, nama_produk="")
    cek("4.2", "Nama produk kosong -> ditolak (wajib), pesan tepat di bawah field nama",
        tetap and err == ["Product name is required."] and s == 400 and "nama_produk" in d["errors"],
        f"form -> pesan {err}, tidak tersimpan; API -> {s} {d['errors']}")

    err, tetap = tolak_form(kategori="")
    s, d = tambah_api(token, kategori=None)
    cek("4.3", "Kategori tidak dipilih -> ditolak (wajib)",
        tetap and err == ["Category is required."] and s == 400 and d["errors"].get("kategori") == "Category is required.",
        f"form -> {err}; API tanpa kategori -> {s} {d['errors']}")

    # 4.4 kategori teks bebas lewat API langsung
    n = jumlah_produk()
    hasil = {k: tambah_api(token, kategori=k) for k in ("Serum ", "Serum", "serum ", "cleanser", "SERUM")}
    cek("4.4", "Kategori teks bebas lewat request langsung ke API ('Serum ', 'Serum', kategori di luar daftar) -> "
               "DITOLAK backend (whitelist, bukan cuma dropdown di frontend)",
        all(s == 400 and "kategori" in d["errors"] for s, d in hasil.values()) and jumlah_produk() == n,
        f"{ {k: s for k, (s, _) in hasil.items()} }; contoh pesan: {hasil['Serum '][1]['errors']['kategori']!r}")

    # 4.5 tipe & masalah kosong, kandungan terisi -> boleh
    s, d = tambah_api(token, nama_produk="Uji Hanya Kandungan", tipe_kulit_cocok=[], masalah_kulit_cocok=[],
                      deskripsi="", kandungan="Salicylic Acid, Zinc")
    cek("4.5", "Tipe kulit & masalah kulit kosong, tapi kandungan terisi -> boleh (aturannya minimal 1 dari 4 field)",
        s == 201 and d["produk"]["tipe_kulit_cocok"] == [] and d["produk"]["kandungan"] == "Salicylic Acid, Zinc",
        f"-> {s}, tersimpan {d.get('produk', {}).get('id')} dengan kandungan {d.get('produk', {}).get('kandungan')!r}")

    # 4.6 keempat field kosong
    err, tetap = tolak_form(tipe_kulit_cocok=[], masalah_kulit_cocok=[], kandungan="", deskripsi="")
    s, d = tambah_api(token, tipe_kulit_cocok=[], masalah_kulit_cocok=[], kandungan=None, deskripsi="  ")
    cek("4.6", "Keempat field (tipe kulit, masalah kulit, kandungan, deskripsi) kosong semua -> ditolak sebagai "
               "'data tidak valid'",
        tetap and len(err) == 1 and err[0].startswith("Invalid data") and s == 400
        and d["errors"].get("sinyal_rekomendasi", "").startswith("Invalid data"),
        f"form -> {err}; API -> {s}")

    # 4.7 & 4.8 tag teks bebas lewat API
    n = jumlah_produk()
    tipe = {repr(v): tambah_api(token, tipe_kulit_cocok=v)[0] for v in ("Kering", ["Kering"], ["oily"], ["kering "],
                                                                         ["kering", "Berminyak"])}
    masalah = {repr(v): tambah_api(token, masalah_kulit_cocok=v)[0] for v in
               ("Kemerahan & Iritasi", ["kemerahan iritasi"], ["Jerawat"], ["acne"], ["kemerahan_iritasi", "flek"])}
    s_ok, d_ok = tambah_api(token, nama_produk="Uji Tag Baku", tipe_kulit_cocok="kering; sensitif",
                            masalah_kulit_cocok=["kemerahan_iritasi"])
    cek("4.7", "Tipe kulit teks bebas lewat request langsung ('Kering', nilai di luar 5 baku) -> DITOLAK backend; "
               "hanya 5 nilai baku persis yang diterima",
        all(v == 400 for v in tipe.values()) and s_ok == 201
        and d_ok["produk"]["tipe_kulit_cocok"] == ["kering", "sensitif"],
        f"{tipe}; nilai baku 'kering; sensitif' -> {s_ok} {d_ok.get('produk', {}).get('tipe_kulit_cocok')}")
    cek("4.8", "Masalah kulit teks bebas lewat request langsung ('Kemerahan & Iritasi', format beda, di luar 6 baku) "
               "-> DITOLAK backend; hanya 6 nilai baku persis",
        all(v == 400 for v in masalah.values()) and jumlah_produk() == n + 1
        and d_ok["produk"]["masalah_kulit_cocok"] == ["kemerahan_iritasi"],
        f"{masalah}; nilai baku ['kemerahan_iritasi'] -> diterima")

    # 4.9 & 4.10 harga
    err, tetap = tolak_form(harga=None)
    harga = {repr(v): tambah_api(token, harga=v) for v in (None, 0, "", -50000, "abc", True)}
    tanpa_field = api("POST", "/admin/products", {k: v for k, v in PRODUK_VALID.items() if k != "harga"}, token=token)
    cek("4.9", "Harga kosong atau 0 -> ditolak (wajib, harus > 0)",
        tetap and err == ["Price is required."] and harga["None"][0] == harga["0"][0] == harga["''"][0] == 400
        and tanpa_field[0] == 400,
        f"form tanpa harga -> {err}; API: kosong -> {harga['None'][1]['errors']['harga']!r}, 0 -> "
        f"{harga['0'][1]['errors']['harga']!r}, field tidak dikirim -> {tanpa_field[0]}")
    err_neg, tetap_neg = tolak_form(harga=-50000)
    cek("4.10", "Harga negatif -> ditolak",
        tetap_neg and err_neg == ["Price must be greater than 0."] and harga["-50000"][0] == 400
        and harga["'abc'"][0] == harga["True"][0] == 400,
        f"form -50000 -> {err_neg}; API -50000 -> {harga['-50000'][0]}, 'abc' -> {harga[repr('abc')][0]}, "
        f"true -> {harga['True'][0]}")

    # 4.11 harga > Rp10 juta -> tersimpan, harga_outlier, tidak pernah direkomendasikan
    s, d = tambah_api(token, nama_produk="Embun Mist Uji Mahal", harga=15_000_000)
    id_mahal = d["produk"]["id"]
    rek_budget = api("GET", "/rekomendasi", params={"tipe_kulit": "kering", "masalah_kulit": "jerawat",
                                                    "budget": 20_000_000, "top_n": 2000})[1]
    rek_bebas = api("GET", "/rekomendasi", params={"tipe_kulit": "kering", "masalah_kulit": "jerawat", "top_n": 2000})[1]
    _, d_chat = chat("carikan face mist dong", onboarding={**PROFIL_MIST, "budget": 20_000_000})
    ids_budget = [p["id"] for p in rek_budget["produk"]]
    cek("4.11", "Harga di atas Rp10 juta -> tetap tersimpan TAPI otomatis ditandai harga_outlier=True, dan tidak "
                "muncul di rekomendasi (dengan atau tanpa batas budget)",
        s == 201 and d["produk"]["harga_outlier"] is True
        and satu_db("SELECT harga_outlier FROM products WHERE id=?", id_mahal) == 1
        and id_mahal not in ids_budget and id_mahal not in [p["id"] for p in rek_bebas["produk"]]
        and id_mist in ids_budget and id_mahal not in id_rekomendasi(d_chat),
        f"-> {s}, harga_outlier={d['produk']['harga_outlier']}; rekomendasi budget Rp20 juta ({len(ids_budget)} "
        f"produk, termasuk kembarannya yang wajar {id_mist}) tidak memuat {id_mahal}; tanpa budget juga tidak; chat "
        f"'carikan face mist' -> {id_rekomendasi(d_chat)}")

    # 4.12 kandungan generik
    s1, d1 = tambah_api(token, nama_produk="Uji Kandungan Campur", kandungan="Niacinamide, dll, original, premium, 1")
    s2, d2 = tambah_api(token, nama_produk="Uji Kandungan Generik", kandungan="dll, original, premium")
    s3, d3 = tambah_api(token, nama_produk="Uji Generik Saja", kandungan="dll, original, premium", tipe_kulit_cocok=[],
                        masalah_kulit_cocok=[], deskripsi="")
    cek("4.12", "Kandungan berisi kata generik ('dll, original, premium') -> kata generik otomatis dibuang, tidak "
                "tersisa kandungan yang tidak bermakna",
        s1 == 201 and d1["produk"]["kandungan"] == "Niacinamide" and s2 == 201 and d2["produk"]["kandungan"] is None
        and s3 == 400 and "sinyal_rekomendasi" in d3["errors"],
        f"'Niacinamide, dll, original, premium, 1' -> {d1['produk']['kandungan']!r}; 'dll, original, premium' -> "
        f"{d2['produk']['kandungan']!r} (kosong); kalau itu satu-satunya isian -> {s3} (tidak dihitung sebagai data)")

    # 4.13 tanpa link
    s, d = tambah_api(token, nama_produk="Uji Tanpa Link Unik", link="")
    a = app_produk()
    a.text_input(key="cari_produk").set_value("Uji Tanpa Link Unik").run()
    r = baris_produk(a)
    s_js, d_js = tambah_api(token, link="javascript:alert(1)")
    cek("4.13", "Link produk tidak diisi -> tetap tersimpan, TAPI ditandai 'info terbatas' (RAG tidak bisa ambil "
                "kutipan ulasan asli)",
        s == 201 and d["produk"]["info_terbatas"] is True and d["produk"]["link"] is None and r
        and "pill-info" in r[0]["tanda"] and s_js == 400,
        f"-> {s}, info_terbatas={d['produk']['info_terbatas']}; di tabel ada label 'limited info': "
        f"{bool(r and 'pill-info' in r[0]['tanda'])}; (link 'javascript:...' -> {s_js} {d_js['errors'].get('link')!r})")

    # 4.14 tanpa brand
    s, d = tambah_api(token, nama_produk="Uji Tanpa Brand", brand="")
    cek("4.14", "Brand tidak diisi -> tetap boleh tersimpan (brand cuma metadata tampilan)",
        s == 201 and d["produk"]["brand"] is None, f"-> {s}, brand={d['produk']['brand']!r}")

    # 4.15 karakter berbahaya
    jahat = {"nama_produk": "<script>alert(1)</script> Mist Uji Jahat", "kandungan": "'; DROP TABLE products;--",
             "deskripsi": "<img src=x onerror=alert(1)> untuk kulit kering berjerawat"}
    n = jumlah_produk()
    s, d = tambah_api(token, **jahat)
    id_jahat = d["produk"]["id"]
    tersimpan = baris_db("SELECT nama_produk, kandungan, deskripsi FROM products WHERE id=?", id_jahat)[0]
    a = app_produk()
    a.text_input(key="cari_produk").set_value("Mist Uji Jahat").run()
    html_tabel = " ".join(markdown(a))
    _, d_chat = chat(f"info produk {jahat['nama_produk']}", onboarding=PROFIL_MIST)
    import core  # frontend -- kartu chat dirender dengan fungsi yang sama seperti di layar chat
    cek("4.15", "Karakter berbahaya (<script>, SQL injection) di nama/kandungan/deskripsi -> disimpan sebagai teks "
                "biasa, tidak dieksekusi (tabel products utuh, HTML di-escape saat ditampilkan)",
        s == 201 and tersimpan == jahat and jumlah_produk() == n + 1
        and "&lt;script&gt;alert(1)&lt;/script&gt;" in html_tabel and "<script>" not in html_tabel
        and core.esc(jahat["nama_produk"]).startswith("&lt;script&gt;"),
        f"-> {s}; tersimpan persis sebagai teks, tabel products masih ada ({jumlah_produk()} baris); di tabel admin "
        f"tampil sebagai '&lt;script&gt;...' (tidak ada tag <script> mentah); chat -> {d_chat.get('tipe')}")

    # 4.17 hanya deskripsi -> lolos validasi DAN benar-benar bisa direkomendasikan
    s, d = tambah_api(token, nama_produk="Essence Uji Hanya Deskripsi", kategori="essence", tipe_kulit_cocok=[],
                      masalah_kulit_cocok=[], kandungan="",
                      deskripsi="Essence ringan yang cocok buat kulit berjerawat. Membantu meredakan jerawat dan "
                                "menjaga kulit tetap lembap.")
    id_desk = d["produk"]["id"]
    s_c, d_c = chat("carikan essence dong", onboarding={"tipe_kulit": "kering", "masalah_kulit": ["jerawat"],
                                                        "budget": 100000, "tanpa_batas_budget": False})
    cek("4.17", "Produk yang CUMA deskripsi terisi -> lolos validasi, DAN tetap bisa muncul di rekomendasi lewat "
                "pencocokan TF-IDF deskripsi",
        s == 201 and id_desk in id_rekomendasi(d_c),
        f"-> {s} ({id_desk}); 'carikan essence dong' (profil kering + jerawat) -> {id_rekomendasi(d_c)}")


# ---------------- BAGIAN 5: edit produk ----------------

def app_form_edit(pid):
    at = app_admin("admin_produk")
    at.session_state["produk_mode"] = ("edit", pid)
    at.session_state["produk_edit"] = {}
    at.run()
    return at, f"fp_edit_{pid}_{at.session_state['produk_edit']['versi']}"


def ubah_api(token, pid, **ubah):
    versi = satu_db("SELECT versi FROM products WHERE id=?", pid)
    return api("PUT", f"/admin/products/{pid}", {"versi": versi, **ubah}, token=token)


def baris_lengkap(pid):
    return baris_db("SELECT * FROM products WHERE id=?", pid)[0]


def uji_bagian_5():
    print("\n=== BAGIAN 5: Kelola produk -- edit produk yang sudah ada (layar 10) ===")
    token = token_admin()

    # 5.1 edit 1 field (harga) lewat form -> field lain tetap sama persis
    pid = baris_db("SELECT id FROM products WHERE is_active=1 AND kategori='serum' AND brand IS NOT NULL AND "
                   "kandungan IS NOT NULL AND deskripsi IS NOT NULL AND tipe_kulit_cocok IS NOT NULL AND "
                   "masalah_kulit_cocok IS NOT NULL AND harga IS NOT NULL AND rating IS NOT NULL LIMIT 1")[0]["id"]
    sebelum = baris_lengkap(pid)
    at, kunci = app_form_edit(pid)
    isi_form(at, kunci, {"harga": int(sebelum["harga"]) + 1000}, "Save changes")
    sukses = [s.value for s in at.success] + [s.value for s in lanjut(at).success]
    sesudah = baris_lengkap(pid)
    beda = sorted(k for k in sebelum if sebelum[k] != sesudah[k])
    cek("5.1", "Edit 1 field saja (harga) -> cuma field itu yang berubah, field lain tetap sama persis (tidak ada yang "
               "ter-reset diam-diam)",
        beda == ["harga", "updated_at", "versi"] and sesudah["harga"] == sebelum["harga"] + 1000
        and any("Product updated" in s for s in sukses),
        f"{pid}: kolom yang berubah di database = {beda} (harga {sebelum['harga']:.0f} -> {sesudah['harga']:.0f}); "
        f"nama, brand, kategori, kandungan, deskripsi, tag, link, rating, sentimen tidak tersentuh")

    # 5.2 edit kategori: serum -> toner lewat form; kategori tidak valid ditolak
    at, kunci = app_form_edit(pid)
    isi_form(at, kunci, {"kategori": "toner"}, "Save changes")
    kat_baru = satu_db("SELECT kategori FROM products WHERE id=?", pid)
    salah = {k: ubah_api(token, pid, kategori=k)[0] for k in ("Serum ", "Toner", "", "cleanser")}
    at, kunci = app_form_edit(pid)
    err_form = error_form(isi_form(at, kunci, {"kategori": ""}, "Save changes"))
    cek("5.2", "Edit kategori (serum -> toner) -> berhasil; validasi sama dengan tambah produk (wajib, harus salah satu "
               "kategori valid)",
        kat_baru == "toner" and all(v == 400 for v in salah.values()) and err_form == ["Category is required."]
        and satu_db("SELECT kategori FROM products WHERE id=?", pid) == "toner",
        f"form serum -> toner: tersimpan '{kat_baru}'; API kategori {salah}; form kategori dikosongkan -> {err_form}")

    # 5.3 semua validasi tambah produk juga berlaku di edit (pesan sama persis)
    kasus = {"nama kosong": {"nama_produk": " "}, "kategori 'Serum '": {"kategori": "Serum "},
             "tipe 'Kering'": {"tipe_kulit_cocok": ["Kering"]},
             "masalah 'Kemerahan & Iritasi'": {"masalah_kulit_cocok": "Kemerahan & Iritasi"},
             "harga kosong": {"harga": None}, "harga 0": {"harga": 0}, "harga -50000": {"harga": -50000},
             "link javascript:": {"link": "javascript:alert(1)"},
             "4 field sinyal dikosongkan": {"tipe_kulit_cocok": [], "masalah_kulit_cocok": [], "kandungan": "",
                                            "deskripsi": ""}}
    sebelum = baris_lengkap(pid)
    hasil = {}
    for nama, ubah in kasus.items():
        s_e, d_e = ubah_api(token, pid, **ubah)
        s_t, d_t = tambah_api(token, **(ubah if nama != "4 field sinyal dikosongkan" else
                                        {**ubah, "kandungan": None}))
        hasil[nama] = (s_e, s_t, d_e.get("errors") == d_t.get("errors"))
    tetap = baris_lengkap(pid) == sebelum
    at, kunci = app_form_edit(pid)
    err_ui = error_form(isi_form(at, kunci, {"nama_produk": "", "harga": -50000, "link": "ftp://x"}, "Save changes"))
    s_o, d_o = ubah_api(token, pid, harga=15_000_000)
    s_k, d_k = ubah_api(token, pid, kandungan="Niacinamide, dll, original")
    s_x, d_x = ubah_api(token, pid, nama_produk="<script>alert(1)</script> Serum Edit")
    ubah_api(token, pid, harga=sebelum["harga"], nama_produk=sebelum["nama_produk"])
    cek("5.3", "Semua validasi tambah produk (4.2-4.15) juga berlaku di edit dengan perilaku & pesan yang sama -- form "
               "edit tidak lebih longgar",
        all(se == 400 and st_ == 400 and sama for se, st_, sama in hasil.values()) and tetap
        and err_ui == ["Product name is required.", "Price must be greater than 0.",
                       "Link must be a full web address starting with http:// or https://."]
        and s_o == 200 and d_o["produk"]["harga_outlier"] is True and d_k["produk"]["kandungan"] == "Niacinamide"
        and d_x["produk"]["nama_produk"].startswith("<script>"),
        f"lewat edit vs tambah -> (status edit, status tambah, pesan sama): {hasil}; data produk tidak berubah sama "
        f"sekali setelah semua penolakan: {tetap}; form edit -> {err_ui}; harga 15 juta -> harga_outlier="
        f"{d_o['produk']['harga_outlier']}; kandungan generik -> {d_k['produk']['kandungan']!r}; <script> disimpan "
        f"sebagai teks")

    # 5.4 perubahan langsung dipakai chatbot
    s, d = tambah_api(token, nama_produk="Kabut Mist Uji Edit", tipe_kulit_cocok=["kering"])
    pid2 = d["produk"]["id"]
    berminyak = {"tipe_kulit": "berminyak", "masalah_kulit": ["jerawat", "dehidrasi"], "budget": 100000,
                 "tanpa_batas_budget": False}
    sebelum_edit = id_rekomendasi(chat("carikan face mist dong", onboarding=berminyak)[1])
    ubah_api(token, pid2, tipe_kulit_cocok=["berminyak"])
    sesudah_tipe = id_rekomendasi(chat("carikan face mist dong", onboarding=berminyak)[1])
    ubah_api(token, pid2, kategori="essence")
    mist_lagi = id_rekomendasi(chat("carikan face mist dong", onboarding=berminyak)[1])
    essence = id_rekomendasi(chat("carikan essence dong", onboarding=berminyak)[1])
    cek("5.4", "Edit tipe_kulit_cocok / kategori produk -> hasil rekomendasi chatbot LANGSUNG ikut berubah (index CBF "
               "di-refresh, tidak memakai data lama)",
        pid2 not in sebelum_edit and pid2 in sesudah_tipe and pid2 not in mist_lagi and pid2 in essence,
        f"{pid2} tipe 'kering' -> tidak muncul untuk kulit berminyak {sebelum_edit}; diedit jadi 'berminyak' -> "
        f"langsung muncul {sesudah_tipe}; kategori diedit mist -> essence -> hilang dari face mist {mist_lagi}, muncul "
        f"di essence {essence}")

    # 5.5 race condition: admin B membuka form, admin A menonaktifkan duluan, admin B menyimpan
    at_b, kunci = app_form_edit(pid2)
    harga_awal = satu_db("SELECT harga FROM products WHERE id=?", pid2)
    api("PUT", f"/admin/products/{pid2}/status", {"is_active": False}, token=token)  # admin A
    at_b = isi_form(at_b, kunci, {"harga": 99000}, "Save changes")
    err_b = [e.value for e in at_b.error]
    muat_ulang = tombol(at_b, "muat_ulang_edit")
    harga_akhir = satu_db("SELECT harga FROM products WHERE id=?", pid2)
    # varian: admin A mengedit (bukan menonaktifkan), dan produk yang tidak ada sama sekali
    api("PUT", f"/admin/products/{pid2}/status", {"is_active": True}, token=token)
    versi_lama = satu_db("SELECT versi FROM products WHERE id=?", pid2)
    ubah_api(token, pid2, nama_produk="Kabut Mist Uji Edit A")
    s_ubah, d_ubah = api("PUT", f"/admin/products/{pid2}", {"versi": versi_lama, "harga": 77000}, token=token)
    s_hilang, d_hilang = api("PUT", "/admin/products/PRD9999", {"versi": 1, "harga": 77000}, token=token)
    cek("5.5", "Edit produk yang sudah berubah/dinonaktifkan admin lain (race condition) -> ditolak dengan pesan jelas, "
               "tidak menimpa data; produk yang tidak ada -> pesan 'tidak ditemukan', bukan error mentah",
        any("was deactivated by another admin" in e for e in err_b) and muat_ulang is not None
        and harga_akhir == harga_awal and s_ubah == 409 and "was changed by another admin" in d_ubah["detail"]
        and satu_db("SELECT harga FROM products WHERE id=?", pid2) == harga_awal
        and s_hilang == 404 and "not found" in d_hilang["detail"],
        f"admin B simpan setelah admin A menonaktifkan -> {err_b} (+ tombol 'Reload product data'); harga tetap "
        f"{harga_akhir:.0f}; setelah admin A mengedit -> {s_ubah} {d_ubah['detail']!r}; produk tidak ada -> "
        f"{s_hilang} {d_hilang['detail']!r}")


# ---------------- BAGIAN 6: nonaktifkan produk ----------------

TIPE = ["berminyak", "kering", "kombinasi", "sensitif", "normal"]
MASALAH = ["jerawat", "kusam", "hiperpigmentasi", "penuaan", "kemerahan_iritasi", "dehidrasi"]


def rekomendasi_semua_profil(top_n):
    """{(tipe, masalah): [id]} untuk ke-30 kombinasi profil."""
    return {(t, m): [p["id"] for p in api("GET", "/rekomendasi", params={"tipe_kulit": t, "masalah_kulit": m,
                                                                           "top_n": top_n})[1]["produk"]]
            for t in TIPE for m in MASALAH}


def klik_status(pid, nama):
    """Klik ikon nonaktifkan/aktifkan di baris produk pada tabel admin. Menonaktifkan
    memunculkan pop-up konfirmasi dulu; tombol "Deactivate" di pop-up ikut diklik.
    return: (tooltip ikon, baris sesudahnya, pesan sukses, (pop-up muncul, is_active sebelum dikonfirmasi))."""
    at = app_produk()
    at.text_input(key="cari_produk").set_value(nama).run()
    label = tombol(at, f"status_{pid}").help
    tombol(at, f"status_{pid}").click()
    at.run()
    ya = tombol(at, "ya_nonaktif")
    popup = (ya is not None, satu_db("SELECT is_active FROM products WHERE id=?", pid))
    if ya is not None:
        ya.click()
        at.run()
    sukses = [s.value for s in at.success]  # pesan sekali-tampil, dibaca sebelum pindah ke AppTest baru
    at = lanjut(at)
    at.text_input(key="cari_produk").set_value(nama).run()
    baris = next((b for b in baris_produk(at) if b["id"] == pid), None)
    return label, baris, sukses, popup


def batal_status(pid, nama):
    """Klik ikon nonaktifkan lalu "Cancel" di pop-up -> produk harus tetap aktif.
    return: (is_active sesudah batal, pop-up masih menunggu konfirmasi)."""
    at = app_produk()
    at.text_input(key="cari_produk").set_value(nama).run()
    tombol(at, f"status_{pid}").click()
    at.run()
    tombol(at, "batal_nonaktif").click()
    at.run()
    return satu_db("SELECT is_active FROM products WHERE id=?", pid), "konfirmasi_nonaktif" in at.session_state


def uji_bagian_6():
    print("\n=== BAGIAN 6: Kelola produk -- nonaktifkan (bukan hapus permanen) ===")
    label_kat = api("GET", "/admin/opsi-produk", token=token_admin())[1]["kategori"]

    # produk yang SERING muncul di rekomendasi: paling sering masuk 10 besar dari 30 kombinasi profil
    awal = rekomendasi_semua_profil(10)
    frekuensi = {}
    for ids in awal.values():
        for i in ids:
            frekuensi[i] = frekuensi.get(i, 0) + 1
    # ... dan benar-benar muncul di jawaban chatbot untuk suatu profil (dipakai juga untuk riwayat 6.3)
    uid, email, token_u = akun_lengkap("Pemilik Riwayat")
    pid = profil = d_chat = None
    for kandidat in sorted(frekuensi, key=frekuensi.get, reverse=True)[:10]:
        kat = satu_db("SELECT kategori FROM products WHERE id=?", kandidat)
        t, m = max(awal, key=lambda c: (kandidat in awal[c], -awal[c].index(kandidat) if kandidat in awal[c] else 0))
        prof = {"tipe_kulit": t, "masalah_kulit": [m], "budget": None, "tanpa_batas_budget": True}
        api("PUT", "/profile", prof, token=token_u)
        s, d = chat(f"rekomendasiin {label_kat[kat]} dong", token=token_u, onboarding=prof)
        if kandidat in id_rekomendasi(d):
            pid, profil, d_chat, pesan_chat = kandidat, prof, d, f"rekomendasiin {label_kat[kat]} dong"
            break
    nama = satu_db("SELECT nama_produk FROM products WHERE id=?", pid)
    nomor = id_rekomendasi(d_chat).index(pid) + 1
    konteks_lama, conv_id = d_chat["konteks"], d_chat["conversation_id"]
    n_produk = jumlah_produk()

    # 6.1 nonaktifkan lewat tombol di tabel -> pop-up konfirmasi dulu ("Cancel" tidak mengubah apa-apa),
    # setelah dikonfirmasi status berubah, TIDAK dihapus
    batal = batal_status(pid, nama)
    label, baris, sukses, popup = klik_status(pid, nama)
    db_row = baris_db("SELECT id, is_active FROM products WHERE id=?", pid)
    cek("6.1", "Nonaktifkan 1 produk -> status jadi tidak aktif, TIDAK dihapus permanen dari database (pola is_active "
               "sama dengan user)",
        batal == (1, False) and label == "Deactivate product" and popup == (True, 1) and baris
        and baris["status"] == "Inactive" and db_row == [{"id": pid, "is_active": 0}] and jumlah_produk() == n_produk
        and any("deactivated" in s for s in sukses),
        f"{pid} (masuk 10 besar di {frekuensi[pid]}/30 kombinasi profil) -> klik '{label}' lalu 'Cancel' di pop-up: "
        f"is_active tetap {batal[0]}, pop-up tertutup={not batal[1]}; klik '{label}' -> pop-up muncul={popup[0]} "
        f"(is_active sebelum konfirmasi {popup[1]}) -> 'Deactivate': status di tabel '{baris and baris['status']}', "
        f"di DB {db_row}; jumlah baris products tetap {jumlah_produk()}; pesan: {sukses}")

    # 6.2 tidak muncul lagi di rekomendasi MANAPUN
    sesudah = rekomendasi_semua_profil(2000)
    muncul_rek = [c for c, ids in sesudah.items() if pid in ids]
    _, d_sama = chat(pesan_chat, onboarding=profil)
    _, d_lain = chat("yang lain dong", onboarding=profil, konteks=konteks_lama)
    _, d_nomor = chat(f"kenapa nomor {nomor} direkomendasiin?", onboarding=profil, konteks=konteks_lama)
    _, d_nama = chat(f"info produk {nama}", onboarding=profil)
    muncul_chat = [x for x, d in (("chat sama", d_sama), ("yang lain", d_lain), ("kenapa nomor", d_nomor),
                                  ("info nama", d_nama)) if pid in id_rekomendasi(d) or f"**{nama}**" in d["explanation"]]
    cek("6.2", "Produk yang sering direkomendasikan dinonaktifkan -> TIDAK muncul lagi di rekomendasi manapun sejak "
               "saat itu (juga di percakapan lama yang dilanjutkan)",
        not muncul_rek and not muncul_chat and "sudah tidak tersedia" in d_nomor["explanation"],
        f"30 kombinasi profil x seluruh katalog (top 2000) -> muncul di {len(muncul_rek)} kombinasi; chat yang sama "
        f"-> {id_rekomendasi(d_sama)}; 'yang lain dong' (percakapan lama) -> {id_rekomendasi(d_lain)}; 'kenapa nomor "
        f"{nomor}' -> {d_nomor['explanation'][:95]!r}; sebut namanya -> {d_nama.get('tipe')} (tidak memberi info produk itu)")

    # 6.3 riwayat lama: kartu tetap tampil + label "sudah tidak tersedia"
    riwayat = next(c for c in api("GET", "/history", token=token_u)[1]["conversations"] if c["id"] == conv_id)
    kartu = [p for m in riwayat["messages"] if m.get("data") for p in m["data"].get("recommendation") or []]
    label_api = {p["id"]: p.get("tidak_tersedia") for p in kartu}
    at = app_login(email, PASSWORD)
    tombol(at, f"recent_{conv_id}").click()
    at.run()
    html = " ".join(markdown(at))
    kartu_layar = re.findall(r'<div class="produk-card( tidak-tersedia)?">.*?<div class="produk-nama">([^<]*)</div>', html)
    ditandai = [n for tanda, n in kartu_layar if tanda]
    cek("6.3", "Riwayat chat lama yang berisi produk yang SEKARANG nonaktif -> kartu tetap tampil (catatan historis) "
               "dengan label 'Sudah tidak tersedia', produk lain tidak ikut ditandai",
        label_api.get(pid) is True and sum(bool(v) for v in label_api.values()) == 1 and len(kartu_layar) == len(kartu)
        and ditandai == [html_escape(nama)] and "Sudah tidak tersedia" in html,
        f"GET /history -> tidak_tersedia per kartu {label_api}; dibuka dari sidebar: {len(kartu_layar)} kartu tampil, "
        f"yang diberi label 'Sudah tidak tersedia': {ditandai}")

    # 6.4 aktifkan kembali -> bisa direkomendasikan lagi
    label, baris, _, _ = klik_status(pid, nama)
    lagi = rekomendasi_semua_profil(10)
    _, d_lagi = chat(pesan_chat, onboarding=profil)
    riwayat = next(c for c in api("GET", "/history", token=token_u)[1]["conversations"] if c["id"] == conv_id)
    label_lagi = [p.get("tidak_tersedia") for m in riwayat["messages"] if m.get("data")
                  for p in m["data"].get("recommendation") or [] if p["id"] == pid]
    cek("6.4", "Aktifkan kembali produk yang nonaktif -> kembali bisa direkomendasikan seperti biasa",
        label == "Activate product" and baris and baris["status"] == "Active" and lagi == awal
        and pid in id_rekomendasi(d_lagi)
        and label_lagi == [False],
        f"klik '{label}' -> status '{baris and baris['status']}'; 10 besar untuk 30 kombinasi profil sama persis dengan "
        f"sebelum dinonaktifkan: {lagi == awal}; chat yang sama -> {id_rekomendasi(d_lagi)}; label di riwayat hilang")


def uji_bagian_7():
    print("\n=== BAGIAN 7: Review laporan koreksi dari pengguna ===")
    print("  [LEWATI] 7.1-7.3 fitur masa depan (dokumen: \"bukan buat dites sekarang\") -- belum diimplementasikan, "
          "tidak dihitung di ringkasan")


def html_escape(teks):
    import html
    return html.escape(teks)


BAGIAN = {1: uji_bagian_1, 2: uji_bagian_2, 3: uji_bagian_3, 4: uji_bagian_4, 5: uji_bagian_5, 6: uji_bagian_6,
          7: uji_bagian_7}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bagian", choices=[str(k) for k in BAGIAN])
    args = parser.parse_args()
    print(f"Menyalakan backend uji di port {PORT} (database sementara: {DB_UJI}) ...")
    utama = nyalakan_backend()
    try:
        for nomor, fungsi in BAGIAN.items():
            if args.bagian in (None, str(nomor)):
                fungsi()
    finally:
        matikan(utama)
    lulus = sum(1 for *_, ok, _ in _hasil if ok)
    print(f"\n=== RINGKASAN: {lulus}/{len(_hasil)} skenario PASS ===")
    for kode, deskripsi, ok, _ in _hasil:
        if not ok:
            print(f"  FAIL {kode} {deskripsi}")
    sys.exit(0 if lulus == len(_hasil) else 1)


if __name__ == "__main__":
    main()
