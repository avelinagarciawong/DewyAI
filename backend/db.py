"""
db.py

Database SQLite buat backend chatbot -- diselaraskan ke spesifikasi API
(spek dipegang saat coding backend/frontend, lihat pesan yang kasih
dokumen "Spesifikasi API"). Perubahan dari versi awal:
  - user diidentifikasi pakai EMAIL (bukan username), plus field `nama`.
  - ada `role` ('User'/'Admin') buat endpoint /admin/*.
  - ada `is_active` (dipakai /admin/users buat nonaktifkan akun).
  - id user & conversation pakai UUID string (bukan angka auto-increment)
    -- ini yang dipakai sebagai `sub` claim di JWT (lihat auth.py), dan
    match sama contoh response spek ("id": "uuid").
  - password di-hash pakai bcrypt (lewat auth.py), bukan sha256 manual
    lagi -- karena sekarang beneran ada alur JWT/production-shaped, jadi
    ditingkatkan dari versi awal yang sha256+salt.

SKEMA:
  users          : id, nama, email (UNIQUE), password_hash, role,
                   is_active, tipe_kulit, masalah_kulit, budget_max,
                   created_at
  conversations  : id, user_id, judul, created_at
  messages       : id, conversation_id, peran ('user'/'bot'), isi,
                   created_at
                   (peran pakai 'bot' bukan 'assistant' -- ikut kunci
                   "sender" di response GET /history sesuai spek)

CATATAN: /chat tanpa token tidak pernah menulis ke conversations/messages
(percakapan tamu hanya disimpan di session_state frontend, sesuai spesifikasi).
Fungsi simpan_pesan/buat_percakapan hanya dipanggil bila ada user_id dari token
yang tervalidasi.

CARA PAKAI:
    from db import init_db
    init_db()  # panggil sekali di startup
"""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

# Lokasi database dapat diganti lewat env var DATABASE_PATH, misalnya ke folder
# yang tidak terhapus saat deploy ulang. Default: chatbot.db di sebelah file ini.
DB_FILE = Path(os.getenv("DATABASE_PATH", str(Path(__file__).parent / "chatbot.db")))

PERAN_VALID = {"user", "bot"}


def buat_uuid() -> str:
    return uuid.uuid4().hex


def get_conn():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)  # jaga-jaga folder Volume/custom path belum ada
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            nama TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'User' CHECK(role IN ('User','Admin')),
            is_active INTEGER NOT NULL DEFAULT 1,
            tipe_kulit TEXT,
            masalah_kulit TEXT,
            budget_max INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            judul TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL REFERENCES conversations(id),
            peran TEXT NOT NULL CHECK(peran IN ('user','bot')),
            isi TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- sesi (token) yang sudah diakhiri lewat logout: token JWT tetap sah
        -- secara tanda tangan sampai exp, jadi harus dicatat supaya ditolak
        CREATE TABLE IF NOT EXISTS sesi_dicabut (
            jti TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            exp INTEGER NOT NULL
        );

        -- katalog produk yang dipakai chatbot (diisi sekali dari
        -- data/products_final.csv, lalu dikelola admin). Kolom datanya sama
        -- dengan CSV; is_active = nonaktif tanpa hapus permanen, versi = naik
        -- setiap kali baris berubah (mendeteksi 2 admin mengedit bersamaan)
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            nama_produk TEXT NOT NULL,
            link TEXT,
            brand TEXT,
            kategori TEXT NOT NULL,
            kandungan TEXT,
            deskripsi TEXT,
            tipe_kulit_cocok TEXT,
            masalah_kulit_cocok TEXT,
            sumber_label_tipe_kulit TEXT,
            sumber_label_masalah_kulit TEXT,
            harga REAL,
            harga_outlier INTEGER NOT NULL DEFAULT 0,
            rating REAL,
            skor_sentimen REAL,
            jml_ulasan INTEGER,
            sumber TEXT,
            updated_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            versi INTEGER NOT NULL DEFAULT 1
        );
    """)
    # kolom yang ditambahkan belakangan -- database lama (chatbot.db yang sudah
    # berisi akun) ikut diperbarui tanpa kehilangan data
    _tambah_kolom(conn, "users", "sesi_berlaku_sejak", "INTEGER NOT NULL DEFAULT 0")  # ms; token lebih tua ditolak
    _tambah_kolom(conn, "conversations", "konteks", "TEXT")      # ingatan percakapan (JSON) untuk dilanjutkan
    _tambah_kolom(conn, "conversations", "diperbarui", "TEXT")   # waktu pesan terakhir (urutan riwayat)
    _tambah_kolom(conn, "messages", "data", "TEXT")              # kartu produk/tabel jawaban bot (JSON)
    conn.commit()
    conn.close()


def _tambah_kolom(conn, tabel, kolom, tipe):
    ada = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabel})")}
    if kolom not in ada:
        conn.execute(f"ALTER TABLE {tabel} ADD COLUMN {kolom} {tipe}")


# ---------- sesi ----------

def cabut_sesi(jti: str, user_id: str, exp: int):
    conn = get_conn()
    conn.execute("DELETE FROM sesi_dicabut WHERE exp < strftime('%s','now')")  # yang sudah kedaluwarsa tidak perlu dicatat lagi
    conn.execute("INSERT OR IGNORE INTO sesi_dicabut (jti, user_id, exp) VALUES (?,?,?)", (jti, user_id, exp))
    conn.commit()
    conn.close()


def sesi_dicabut(jti: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM sesi_dicabut WHERE jti=?", (jti,)).fetchone()
    conn.close()
    return row is not None


# ---------- users ----------

def cari_user_by_email(email: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def cari_user_by_id(user_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def buat_user(nama: str, email: str, password_hash: str, role: str = "User") -> dict:
    if cari_user_by_email(email):
        raise ValueError("Email sudah digunakan")
    user_id = buat_uuid()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO users (id, nama, email, password_hash, role) VALUES (?,?,?,?,?)",
            (user_id, nama, email, password_hash, role),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # 2 pendaftaran email yang sama datang hampir bersamaan: yang kalah
        # lolos cek di atas tapi ditolak UNIQUE -- tetap "email sudah dipakai"
        raise ValueError("Email sudah digunakan")
    finally:
        conn.close()
    return cari_user_by_id(user_id)


def ubah_password(user_id: str, password_hash_baru: str, sesi_berlaku_sejak_ms: int):
    """sesi_berlaku_sejak_ms: token yang dibuat sebelum waktu ini (sesi di
    device lain) tidak diterima lagi setelah password diganti."""
    conn = get_conn()
    conn.execute("UPDATE users SET password_hash=?, sesi_berlaku_sejak=? WHERE id=?",
                 (password_hash_baru, sesi_berlaku_sejak_ms, user_id))
    conn.commit()
    conn.close()


def simpan_profil(user_id: str, tipe_kulit=None, masalah_kulit=None, budget_max=None, tanpa_batas_budget=False):
    """Update sebagian -- field yang None/tidak dikirim TIDAK menimpa nilai lama.
    tanpa_batas_budget=True menyimpan budget_max NULL (user sengaja pilih
    "Tidak ada batas budget"), beda dari budget_max=None yang artinya "tidak diubah"."""
    ada = cari_user_by_id(user_id)
    if ada is None:
        raise ValueError("User tidak ditemukan")
    tipe_kulit = tipe_kulit if tipe_kulit is not None else ada["tipe_kulit"]
    masalah_kulit_str = ",".join(masalah_kulit) if masalah_kulit is not None else ada["masalah_kulit"]
    if tanpa_batas_budget:
        budget_max = None
    elif budget_max is None:
        budget_max = ada["budget_max"]
    conn = get_conn()
    conn.execute(
        "UPDATE users SET tipe_kulit=?, masalah_kulit=?, budget_max=? WHERE id=?",
        (tipe_kulit, masalah_kulit_str, budget_max, user_id),
    )
    conn.commit()
    conn.close()
    return ambil_profil(user_id)


def ambil_profil(user_id: str):
    user = cari_user_by_id(user_id)
    if user is None:
        return None
    user["masalah_kulit"] = user["masalah_kulit"].split(",") if user["masalah_kulit"] else []
    return user


def daftar_semua_user():
    conn = get_conn()
    rows = conn.execute("SELECT id, nama, email, role, is_active, created_at FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _pola_like(kata: str) -> str:
    """Kata cari -> pola LIKE. % dan _ yang diketik admin dicari sebagai
    huruf biasa, bukan wildcard."""
    return "%" + kata.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _syarat_cari(q, kolom):
    """Setiap kata di q harus muncul (di salah satu kolom) -- "wardah sunscreen"
    menemukan "Wardah UV Shield ... Sunscreen". LIKE SQLite tidak peka huruf
    besar/kecil."""
    syarat, param = [], []
    for kata in (q or "").split():
        syarat.append("(" + " OR ".join(f"{k} LIKE ? ESCAPE '\\'" for k in kolom) + ")")
        param += [_pola_like(kata)] * len(kolom)
    return syarat, param


def cari_user(q=None, halaman=1, per_halaman=20):
    """Daftar user untuk tabel admin (per halaman). return: (users, total)."""
    syarat, param = _syarat_cari(q, ("nama", "email"))
    where = f"WHERE {' AND '.join(syarat)}" if syarat else ""
    conn = get_conn()
    total = conn.execute(f"SELECT COUNT(*) FROM users {where}", param).fetchone()[0]
    rows = conn.execute(f"SELECT id, nama, email, role, is_active, created_at FROM users {where} "
                        "ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                        [*param, per_halaman, (halaman - 1) * per_halaman]).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def jumlah_admin_aktif() -> int:
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM users WHERE role='Admin' AND is_active=1").fetchone()[0]
    conn.close()
    return n


def ringkasan():
    """Angka blok ringkasan admin -- dihitung langsung dari tabel setiap
    kali diminta (bukan angka yang disimpan terpisah, jadi tidak bisa basi)."""
    conn = get_conn()
    satu = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    hasil = {
        "total_user": satu("SELECT COUNT(*) FROM users"),
        "user_aktif": satu("SELECT COUNT(*) FROM users WHERE is_active=1"),
        "total_admin": satu("SELECT COUNT(*) FROM users WHERE role='Admin'"),
        "total_produk": satu("SELECT COUNT(*) FROM products"),
        "produk_aktif": satu("SELECT COUNT(*) FROM products WHERE is_active=1"),
        "total_percakapan": satu("SELECT COUNT(*) FROM conversations"),
    }
    conn.close()
    return hasil


def set_status_aktif(user_id: str, is_active: bool):
    """Menonaktifkan juga mengakhiri SEMUA sesi akun itu secara permanen --
    kalau nanti diaktifkan lagi, token lama tetap tidak berlaku (harus login).
    Admin aktif terakhir tidak bisa dinonaktifkan: syaratnya dicek di DALAM
    perintah UPDATE yang sama (atomik), jadi 2 admin yang saling menonaktifkan
    pada saat bersamaan tidak bisa membuat sistem tanpa admin aktif.
    return: 'ok' | 'tidak_ada' | 'admin_terakhir'."""
    conn = get_conn()
    if is_active:
        cur = conn.execute("UPDATE users SET is_active=1 WHERE id=?", (user_id,))
    else:
        cur = conn.execute(
            "UPDATE users SET is_active=0, sesi_berlaku_sejak=? WHERE id=? AND (role<>'Admin' OR EXISTS "
            "(SELECT 1 FROM users lain WHERE lain.role='Admin' AND lain.is_active=1 AND lain.id<>?))",
            (int(time.time() * 1000), user_id, user_id))
    conn.commit()
    diubah = cur.rowcount > 0
    conn.close()
    if diubah:
        return "ok"
    return "tidak_ada" if cari_user_by_id(user_id) is None else "admin_terakhir"


# ---------- conversations & messages (HANYA dipanggil kalau user login) ----------

def buat_percakapan(user_id: str, judul: str = None) -> str:
    conv_id = buat_uuid()
    conn = get_conn()
    conn.execute("INSERT INTO conversations (id, user_id, judul) VALUES (?,?,?)", (conv_id, user_id, judul))
    conn.commit()
    conn.close()
    return conv_id


def simpan_pesan(conversation_id: str, peran: str, isi: str, data=None):
    """data: isi jawaban bot yang terstruktur (kartu produk, kelompok, tabel
    perbandingan) -- disimpan supaya riwayat yang dibuka lagi tampil utuh,
    sama seperti saat chat berlangsung, tidak hanya teksnya."""
    if peran not in PERAN_VALID:
        raise ValueError(f"peran harus salah satu dari {PERAN_VALID}, dapat '{peran}'")
    conn = get_conn()
    conn.execute(
        "INSERT INTO messages (conversation_id, peran, isi, data) VALUES (?,?,?,?)",
        (conversation_id, peran, isi, None if data is None else json.dumps(data, ensure_ascii=False)),
    )
    conn.execute("UPDATE conversations SET diperbarui=strftime('%Y-%m-%d %H:%M:%f','now') WHERE id=?", (conversation_id,))
    conn.commit()
    conn.close()


def simpan_konteks(conversation_id: str, konteks):
    """Ingatan percakapan (profil yang diubah lewat chat, daftar produk yang
    sedang tampil, dst) -- supaya percakapan lama yang dibuka lagi bisa
    dilanjutkan ("bandingkan nomor 1 sama 2" tetap nyambung)."""
    conn = get_conn()
    conn.execute("UPDATE conversations SET konteks=? WHERE id=?",
                 (json.dumps(konteks, ensure_ascii=False), conversation_id))
    conn.commit()
    conn.close()


def _json_atau_none(teks):
    try:
        return json.loads(teks) if teks else None
    except ValueError:
        return None


def ambil_percakapan_lengkap_user(user_id: str):
    """Buat GET /history -- balikin semua percakapan user BESERTA pesan-pesannya
    (nested), sesuai bentuk response di spek. Urut dari yang terakhir dipakai;
    pesan urut sesuai urutan disimpan (id, bukan waktu -- beberapa pesan bisa
    tersimpan di detik yang sama)."""
    conn = get_conn()
    percakapan = conn.execute(
        "SELECT *, COALESCE(diperbarui, created_at) AS terakhir FROM conversations WHERE user_id=? "
        "ORDER BY terakhir DESC, rowid DESC", (user_id,)
    ).fetchall()
    hasil = []
    for p in percakapan:
        pesan = conn.execute(
            "SELECT peran, isi, data FROM messages WHERE conversation_id=? ORDER BY id ASC", (p["id"],)
        ).fetchall()
        hasil.append({
            "id": p["id"],
            "title": p["judul"],
            "created_at": p["created_at"],
            "updated_at": p["terakhir"],
            "konteks": _json_atau_none(p["konteks"]),
            "messages": [{"sender": m["peran"], "content": m["isi"], "data": _json_atau_none(m["data"])}
                         for m in pesan],
        })
    conn.close()
    return hasil


def milik_user(conversation_id: str, user_id: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id)
    ).fetchone()
    conn.close()
    return row is not None


# ---------- products (katalog chatbot, dikelola admin) ----------

# kolom data -- sama persis dengan data/products_final.csv (yang dibaca CBFEngine)
KOLOM_PRODUK = ("id", "nama_produk", "link", "brand", "kategori", "kandungan", "deskripsi", "tipe_kulit_cocok",
                "masalah_kulit_cocok", "sumber_label_tipe_kulit", "sumber_label_masalah_kulit", "harga",
                "harga_outlier", "rating", "skor_sentimen", "jml_ulasan", "sumber", "updated_at")
_KOLOM_ANGKA = ("harga", "rating", "skor_sentimen", "jml_ulasan")
# kolom yang boleh diubah lewat ubah_produk (nama kolom masuk ke SQL, jadi dibatasi)
KOLOM_BISA_DIUBAH = {"nama_produk", "link", "brand", "kategori", "kandungan", "deskripsi", "tipe_kulit_cocok",
                     "masalah_kulit_cocok", "sumber_label_tipe_kulit", "sumber_label_masalah_kulit", "harga",
                     "harga_outlier"}


def _ke_sql(v):
    """Nilai dari pandas -> nilai SQLite: NaN/teks kosong -> NULL, tipe numpy -> Python."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, str):
        return v if v.strip() else None
    if hasattr(v, "item"):  # numpy.int64 / numpy.bool_ / numpy.float64
        v = v.item()
    return int(v) if isinstance(v, bool) else v


def _waktu_sekarang():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def seed_produk_dari_csv(path) -> int:
    """Isi tabel products dari dataset hasil pipeline -- HANYA kalau tabelnya
    masih kosong (instalasi baru), supaya perubahan admin tidak pernah
    tertimpa saat backend restart. return: jumlah produk yang dimasukkan."""
    path = Path(path)
    conn = get_conn()
    try:
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] or not path.exists():
            return 0
        import pandas as pd
        df = pd.read_csv(path)
        kolom = [k for k in KOLOM_PRODUK if k in df.columns]
        baris = [tuple(_ke_sql(r[k]) for k in kolom) for r in df.to_dict("records")]
        conn.executemany(f"INSERT INTO products ({','.join(kolom)}) VALUES ({','.join('?' * len(kolom))})", baris)
        conn.commit()
        return len(baris)
    finally:
        conn.close()


def produk_df(hanya_aktif=True):
    """Katalog sebagai DataFrame berkolom sama dengan products_final.csv --
    bahan index CBFEngine. Urutan baris = urutan dataset (produk baru di
    belakang), sama seperti waktu CBF membaca CSV."""
    import pandas as pd
    conn = get_conn()
    df = pd.read_sql_query(f"SELECT {','.join(KOLOM_PRODUK)} FROM products "
                           f"{'WHERE is_active=1' if hanya_aktif else ''} ORDER BY rowid", conn)
    conn.close()
    df = df.where(df.notna(), float("nan"))  # NULL teks -> NaN, sama seperti hasil read_csv
    for k in _KOLOM_ANGKA:
        df[k] = pd.to_numeric(df[k], errors="coerce")
    df["harga_outlier"] = df["harga_outlier"].fillna(0).astype(bool)
    return df


def _produk_ke_dict(row):
    p = dict(row)
    p["harga_outlier"] = bool(p["harga_outlier"])
    p["is_active"] = bool(p["is_active"])
    return p


def cari_produk(q=None, kategori=None, tipe_kulit=None, status=None, halaman=1, per_halaman=20):
    """Tabel produk admin: filter digabung AND, per halaman, terbaru di atas.
    tipe_kulit cocok kalau ada di daftar tipe_kulit_cocok produk ("kering;
    sensitif") -- produk yang tag-nya kosong tidak ikut. return: (produk, total)."""
    syarat, param = _syarat_cari(q, ("nama_produk", "brand"))
    if kategori:
        syarat.append("kategori = ?")
        param.append(kategori)
    if tipe_kulit:
        syarat.append("(';' || REPLACE(COALESCE(tipe_kulit_cocok, ''), ' ', '') || ';') LIKE ?")
        param.append(f"%;{tipe_kulit};%")
    if status in ("aktif", "nonaktif"):
        syarat.append(f"is_active = {1 if status == 'aktif' else 0}")
    where = f"WHERE {' AND '.join(syarat)}" if syarat else ""
    conn = get_conn()
    total = conn.execute(f"SELECT COUNT(*) FROM products {where}", param).fetchone()[0]
    rows = conn.execute(f"SELECT id, nama_produk, brand, kategori, harga, harga_outlier, tipe_kulit_cocok, "
                        f"masalah_kulit_cocok, link, jml_ulasan, is_active, versi FROM products {where} "
                        "ORDER BY rowid DESC LIMIT ? OFFSET ?",
                        [*param, per_halaman, (halaman - 1) * per_halaman]).fetchall()
    conn.close()
    return [_produk_ke_dict(r) for r in rows], total


def ambil_produk(produk_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM products WHERE id=?", (produk_id,)).fetchone()
    conn.close()
    return _produk_ke_dict(row) if row else None


def buat_produk(data: dict) -> dict:
    """data: kolom produk yang sudah divalidasi. id dibuat berurutan (PRD0985,
    ...) di dalam transaksi yang mengunci tulis, jadi 2 admin yang menambah
    bersamaan tidak mendapat id yang sama."""
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        maks = conn.execute("SELECT MAX(CAST(SUBSTR(id, 4) AS INTEGER)) FROM products WHERE id LIKE 'PRD%'"
                            ).fetchone()[0] or 0
        baris = {**{k: None for k in KOLOM_PRODUK}, **data, "id": f"PRD{maks + 1:04d}",
                 "updated_at": _waktu_sekarang()}
        conn.execute(f"INSERT INTO products ({','.join(KOLOM_PRODUK)}) VALUES ({','.join('?' * len(KOLOM_PRODUK))})",
                     [_ke_sql(baris[k]) for k in KOLOM_PRODUK])
        conn.commit()
    finally:
        conn.close()
    return ambil_produk(baris["id"])


def ubah_produk(produk_id: str, perubahan: dict, versi: int):
    """Ubah HANYA kolom di `perubahan`, dan hanya kalau baris di database
    masih versi yang dibuka admin (optimistic locking). return (status, produk):
    'ok' | 'tidak_ada' | 'konflik' (sudah diubah/dinonaktifkan admin lain)."""
    kolom = [k for k in perubahan if k in KOLOM_BISA_DIUBAH]
    conn = get_conn()
    cur = conn.execute(
        f"UPDATE products SET {''.join(f'{k}=?, ' for k in kolom)}versi=versi+1, updated_at=? WHERE id=? AND versi=?",
        [*(_ke_sql(perubahan[k]) for k in kolom), _waktu_sekarang(), produk_id, versi])
    conn.commit()
    conn.close()
    produk = ambil_produk(produk_id)
    if cur.rowcount:
        return "ok", produk
    return ("tidak_ada", None) if produk is None else ("konflik", produk)


def set_status_produk(produk_id: str, is_active: bool):
    """Nonaktif = disembunyikan dari chatbot, BUKAN dihapus (datanya tetap)."""
    conn = get_conn()
    cur = conn.execute("UPDATE products SET is_active=?, versi=versi+1, updated_at=? WHERE id=?",
                       (int(is_active), _waktu_sekarang(), produk_id))
    conn.commit()
    conn.close()
    return ambil_produk(produk_id) if cur.rowcount else None


def id_produk_aktif(ids) -> set:
    """Dari daftar id, mana yang masih aktif di katalog (dipakai riwayat chat:
    kartu produk yang sudah nonaktif/tidak ada diberi label "tidak tersedia")."""
    ids = list(set(ids))
    if not ids:
        return set()
    conn = get_conn()
    rows = conn.execute(f"SELECT id FROM products WHERE is_active=1 AND id IN ({','.join('?' * len(ids))})",
                        ids).fetchall()
    conn.close()
    return {r["id"] for r in rows}
