"""
uji_survei.py -- pengujian otomatis fitur survei SUS di dalam aplikasi (mode ?survei=1).
Tiap skenario dicetak PASS/FAIL beserta buktinya.

Seperti uji_admin.py, skrip ini menyalakan BACKEND SENDIRI (port 8014, database sementara,
MODE_RINGAN) dan FRONTEND SENDIRI (port 8514) untuk uji di browser (Chrome headless, layar HP),
jadi jawaban uji tidak mengotori backend/chatbot.db.

CARA PAKAI (dari root repo):
    python tests/uji_survei.py              # semua bagian
    python tests/uji_survei.py --bagian 1   # 1 = API, 2 = browser
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT, PORT_FE = 8014, 8514
TMP = Path(tempfile.mkdtemp(prefix="uji_survei_"))
DB_UJI = TMP / "survei_uji.db"
ADMIN = {"email": "admin.survei@example.com", "password": "AdminUji123", "nama": "Admin Uji"}
BATAS_SURVEI = "3/3600"  # dipersempit agar skenario rate limit cepat
JAWABAN_75 = [4, 2] * 5  # ganjil 4, genap 2 -> (3 x 5 + 3 x 5) x 2,5 = 75
KUALITAS_UJI = [5, 4, 3, 4, 5]  # penilaian kualitas jawaban (terpisah dari skor SUS)
_hasil, _proses = [], []
_nomor_ip = itertools.count(1)


def cek(kode, deskripsi, lulus, bukti=""):
    _hasil.append((kode, deskripsi, bool(lulus), bukti))
    print(f"  [{'PASS' if lulus else 'FAIL'}] {kode} {deskripsi}" + (f"\n         bukti: {bukti}" if bukti else ""))


def api(method, path, body=None, token=None, ip="127.0.0.1"):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=60, source_address=(ip, 0))
    h = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=h)
    resp = conn.getresponse()
    teks = resp.read().decode("utf-8")
    conn.close()
    return resp.status, (json.loads(teks) if teks else {})


def ip_baru():
    n = next(_nomor_ip)
    return f"127.0.{2 + n // 250}.{1 + n % 250}"


def jalankan(perintah, env, nama):
    log = open(TMP / f"{nama}.log", "w", encoding="utf-8")
    p = subprocess.Popen(perintah, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    _proses.append(p)
    return p


def nyalakan_backend():
    env = {**os.environ, "DATABASE_PATH": str(DB_UJI), "MODE_RINGAN": "1", "ADMIN_EMAIL": ADMIN["email"],
           "ADMIN_PASSWORD": ADMIN["password"], "ADMIN_NAMA": ADMIN["nama"], "RATE_LIMIT_SURVEI": BATAS_SURVEI,
           "PYTHONIOENCODING": "utf-8"}
    p = jalankan([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(PORT)], env, "backend")
    batas = time.time() + 240
    while time.time() < batas:
        if p.poll() is not None:
            sys.exit(f"Backend uji mati saat startup, lihat {TMP / 'backend.log'}")
        try:
            if api("GET", "/health")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(1)
    sys.exit("Backend uji tidak siap dalam 240 detik")


def nyalakan_frontend():
    import urllib.request
    env = {**os.environ, "BACKEND_URL": f"http://127.0.0.1:{PORT}"}
    jalankan([sys.executable, "-m", "streamlit", "run", "frontend/app.py", "--server.port", str(PORT_FE),
              "--server.headless", "true"], env, "frontend")
    batas = time.time() + 120
    while time.time() < batas:
        try:
            if urllib.request.urlopen(f"http://localhost:{PORT_FE}/_stcore/health", timeout=5).status == 200:
                return f"http://localhost:{PORT_FE}"
        except OSError:
            time.sleep(1)
    sys.exit("Frontend uji tidak siap dalam 120 detik")


@atexit.register
def matikan_semua():
    for p in _proses:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()


def token(email, password):
    return api("POST", "/login", {"email": email, "password": password}, ip=ip_baru())[1]["access_token"]


def penilaian(**ubah):
    return {"perangkat": "HP", "frekuensi": "Setiap hari", "jawaban": JAWABAN_75, "kualitas": KUALITAS_UJI,
            "tugas_selesai": ["profil", "rekomendasi"], "suka": "misinya seru", "perbaiki": None, **ubah}


def jumlah_baris():
    conn = sqlite3.connect(DB_UJI)
    try:
        return conn.execute("SELECT COUNT(*) FROM survei_sus").fetchone()[0]
    finally:
        conn.close()


# ---------------- BAGIAN 1: API ----------------

def uji_bagian_1():
    print("\n=== BAGIAN 1: API survei ===")
    s, d = api("POST", "/survei", penilaian(), ip=ip_baru())
    conn = sqlite3.connect(DB_UJI)
    kolom = [r[1] for r in conn.execute("PRAGMA table_info(survei_sus)")]
    baris = conn.execute("SELECT jawaban, skor, perangkat, kualitas FROM survei_sus").fetchall()
    conn.close()
    cek("1.1", "Penilaian lengkap tanpa login -> tersimpan (201), skor SUS dihitung server hanya dari 10 pernyataan "
               "SUS, 5 jawaban kualitas jawaban ikut tersimpan, anonim (tanpa kolom akun)",
        s == 201 and d.get("skor") == 75.0 and len(baris) == 1 and json.loads(baris[0][0]) == JAWABAN_75
        and json.loads(baris[0][3]) == KUALITAS_UJI and not any("user" in k or "email" in k for k in kolom),
        f"status {s}, skor {d.get('skor')}; kualitas tersimpan {baris[0][3] if baris else None}; kolom tabel: {kolom}")

    tanpa_kualitas = penilaian()
    del tanpa_kualitas["kualitas"]
    salah = {
        "9 jawaban": penilaian(jawaban=JAWABAN_75[:9]),
        "nilai 6": penilaian(jawaban=[6] + JAWABAN_75[1:]),
        "kualitas 4 jawaban": penilaian(kualitas=KUALITAS_UJI[:4]),
        "kualitas nilai 0": penilaian(kualitas=[0] + KUALITAS_UJI[1:]),
        "tanpa kualitas": tanpa_kualitas,
        "perangkat 'Tablet'": penilaian(perangkat="Tablet"),
        "frekuensi tak dikenal": penilaian(frekuensi="Kadang"),
        "saran 1001 karakter": penilaian(suka="a" * 1001),
    }
    sebelum = jumlah_baris()
    hasil = {k: api("POST", "/survei", body, ip=ip_baru()) for k, body in salah.items()}
    cek("1.2", "Input tidak valid ditolak 400 dengan pesan jelas dan tidak tersimpan",
        all(s == 400 for s, _ in hasil.values()) and jumlah_baris() == sebelum,
        "; ".join(f"{k} -> {s} {d.get('detail')!r}" for k, (s, d) in hasil.items()))

    s, d = api("POST", "/survei", penilaian(tugas_selesai=["banding", "hack", "profil", "banding"]), ip=ip_baru())
    conn = sqlite3.connect(DB_UJI)
    tugas = json.loads(conn.execute("SELECT tugas_selesai FROM survei_sus WHERE id = ?", (d["id"],)).fetchone()[0])
    conn.close()
    cek("1.3", "Kode misi tak dikenal dibuang, duplikat digabung, urutan baku",
        s == 201 and tugas == ["profil", "banding"], f"dikirim ['banding','hack','profil','banding'] -> tersimpan {tugas}")

    ip = ip_baru()
    status = [api("POST", "/survei", penilaian(), ip=ip)[0] for _ in range(4)]
    lain = api("POST", "/survei", penilaian(), ip=ip_baru())[0]
    cek("1.4", f"Pembatas spam: lebih dari {BATAS_SURVEI.split('/')[0]} kiriman per jam dari perangkat yang sama -> 429; "
               "perangkat lain tidak terpengaruh",
        status == [201, 201, 201, 429] and lain == 201, f"perangkat sama: {status}; perangkat lain: {lain}")

    s_tamu = api("GET", "/admin/survei")[0]
    email = f"user.{time.time_ns()}@example.com"
    api("POST", "/register", {"nama": "User Uji", "email": email, "password": "rahasia123"}, ip=ip_baru())
    s_user = api("GET", "/admin/survei", token=token(email, "rahasia123"))[0]
    s_admin, d = api("GET", "/admin/survei", token=token(ADMIN["email"], ADMIN["password"]))
    r = d.get("ringkasan", {})
    n = jumlah_baris()
    cek("1.5", "Hasil survei hanya untuk admin (tamu 401, user 403); ringkasan sesuai isi database",
        s_tamu == 401 and s_user == 403 and s_admin == 200 and r.get("n") == n == len(d["respon"])
        and r.get("rata") == 75.0 and r.get("grade") == "B" and d["rata_pernyataan"] == [float(x) for x in JAWABAN_75]
        and d["penyelesaian_tugas"]["profil"] == 1.0
        and [k["rata"] for k in d["kualitas"]] == [float(x) for x in KUALITAS_UJI]
        and [k["setuju"] for k in d["kualitas"]] == [1.0 if x >= 4 else 0.0 for x in KUALITAS_UJI],
        f"tamu {s_tamu}, user {s_user}, admin {s_admin}; n={r.get('n')}, rata {r.get('rata')}, grade {r.get('grade')}, "
        f"penyelesaian misi {d.get('penyelesaian_tugas')}; kualitas rata {[k['rata'] for k in d.get('kualitas', [])]}, "
        f"setuju {[k['setuju'] for k in d.get('kualitas', [])]}")

    sys.path.insert(0, str(ROOT / "frontend"))
    sys.path.insert(0, str(ROOT / "models"))
    import io
    import pandas as pd
    import evaluasi_sus
    from halaman.admin_survei import _csv
    df = pd.read_csv(io.BytesIO(_csv(d["respon"])))
    peta = evaluasi_sus.kolom_sus(df)
    skor = [evaluasi_sus.skor_dari_jawaban([int(b[peta[k]]) for k in range(1, 11)]) for _, b in df.iterrows()]
    peta_k = evaluasi_sus.kolom_kualitas(df)
    kualitas_csv = [[int(b[peta_k[k]]) for k in range(1, 6)] for _, b in df.iterrows()] if peta_k else []
    cek("1.6", "CSV unduhan panel admin terbaca skrip models/evaluasi_sus.py dengan skor yang sama, termasuk 5 kolom "
               "kualitas jawaban",
        len(skor) == n and skor == list(df["Skor SUS"]) and len(peta_k) == 5 and kualitas_csv == [KUALITAS_UJI] * n,
        f"{len(skor)} baris, skor dari CSV {sorted(set(skor))}; kolom kualitas {list(peta_k.values())[:1]}...")


# ---------------- BAGIAN 2: browser ----------------

def uji_bagian_2():
    print("\n=== BAGIAN 2: alur responden di browser (layar HP) ===")
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    url = nyalakan_frontend()
    o = Options()
    o.add_argument("--headless=new")
    o.add_experimental_option("mobileEmulation", {"deviceMetrics": {"width": 390, "height": 844, "pixelRatio": 2}})
    d = webdriver.Chrome(options=o)

    def teks():
        return d.find_element(By.TAG_NAME, "body").text

    def tunggu(f, detik=40):
        batas = time.time() + detik
        while time.time() < batas:
            try:
                if f():
                    time.sleep(1)
                    return True
            except Exception:
                pass
            time.sleep(0.4)
        return False

    def progres():
        e = d.find_elements(By.CSS_SELECTOR, ".misi-angka")
        return e[0].text if e else None

    def onboarding():
        tunggu(lambda: d.find_elements(By.CSS_SELECTOR, ".st-key-form_onboarding_fld_tipe"))
        for kont, pilihan in ((".st-key-form_onboarding_fld_tipe", "Berminyak"),
                              (".st-key-form_onboarding_fld_masalah", "Jerawat")):
            d.find_element(By.CSS_SELECTOR, f'{kont} [data-baseweb="select"]').click()
            time.sleep(0.8)
            next(x for x in d.find_elements(By.CSS_SELECTOR, '[role="option"]') if x.text.strip() == pilihan).click()
            time.sleep(0.8)
        d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        d.find_element(By.CSS_SELECTOR, ".st-key-form_onboarding_fld_budget input").send_keys("150000")
        d.find_element(By.XPATH, '//button[.//p[normalize-space()="Start Chat"]]').click()
        tunggu(lambda: d.find_elements(By.CSS_SELECTOR, 'div[data-testid="stChatInput"] textarea'))

    def kirim(pesan):
        n = len(d.find_elements(By.CSS_SELECTOR, '[data-testid="stChatMessage"]'))
        box = d.find_element(By.CSS_SELECTOR, 'div[data-testid="stChatInput"] textarea')
        box.send_keys(pesan)
        box.send_keys(Keys.ENTER)
        tunggu(lambda: len(d.find_elements(By.CSS_SELECTOR, '[data-testid="stChatMessage"]')) >= n + 2)
        time.sleep(1.5)
        return progres(), [t.text.split("\n")[-1] for t in d.find_elements(By.CSS_SELECTOR, '[data-testid="stToast"]')]

    try:
        d.get(url)
        onboarding()
        tanpa_kartu = not d.find_elements(By.CSS_SELECTOR, ".st-key-misi_survei")
        d.delete_all_cookies()
        d.get(url + "/?survei=1")
        onboarding()
        awal = progres()
        top = d.execute_script("return Math.round(document.querySelector('.misi-kepala').getBoundingClientRect().top)")
        cek("2.1", "Tanpa ?survei=1 tidak ada kartu misi; dengan ?survei=1 kartu misi tampil utuh di layar HP "
                   "(tidak tertutup bilah atas) dengan misi 'Isi profil kulit' langsung selesai",
            tanpa_kartu and awal == "1/5" and top >= 60,
            f"link biasa tanpa kartu={tanpa_kartu}; link survei: progres {awal}, judul kartu {top}px dari atas")

        langkah = [("rekomendasiin sunscreen dong", "2/5"), ("ada review bagus soal nomor 1 ga?", "3/5"),
                   # temuan uji coba: "bagusan mana" (tabel + 1 pemenang) dulu tidak mencentang misi perbandingan
                   ("produk 1 dan 3 bagusan mana", "4/5"), ("kulitku sebenernya kering", "5/5")]
        hasil = [(p, *kirim(p)) for p, _ in langkah]
        cek("2.2", "Misi tercentang otomatis dari percakapan (rekomendasi, ulasan, perbandingan -- termasuk lewat "
                   "'bagusan mana', ubah kondisi kulit) dan setiap misi yang selesai memunculkan notifikasi",
            [h[1] for h in hasil] == [x for _, x in langkah] and all(h[2] for h in hasil),
            "; ".join(f"{p!r} -> {prog}, notifikasi {t}" for p, prog, t in hasil))

        ajakan = bool(d.find_elements(By.CSS_SELECTOR, ".st-key-ajakan_survei"))
        # setelah jawaban baru, halaman digulir ke pertanyaan terakhir; ajakan ada di bawah jawaban -> digulir dulu
        tombol = d.find_element(By.CSS_SELECTOR, ".st-key-survei_nilai_bawah button")
        d.execute_script("arguments[0].scrollIntoView({block:'center'});", tombol)
        time.sleep(0.5)
        tombol.click()
        tunggu(lambda: "Penilaian Dew AI" in teks())
        n_awal = jumlah_baris()
        d.find_element(By.XPATH, '//button[.//p[normalize-space()="Kirim penilaian"]]').click()
        time.sleep(2)
        tolak_kosong = "Masih ada yang belum dijawab" in teks() and jumlah_baris() == n_awal
        cek("2.3", "Semua misi selesai -> ajakan 'Beri penilaian' muncul di bawah percakapan; form menolak kiriman "
                   "yang belum lengkap",
            ajakan and tolak_kosong, f"ajakan tampil={ajakan}; kirim kosong ditolak={tolak_kosong}")

        def pilih(key, label):
            el = d.find_element(By.XPATH, f'//div[contains(@class,"st-key-{key}")]//label[.//p[normalize-space()="{label}"]]')
            d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            el.click()
            time.sleep(0.3)

        pilih("sv_perangkat", "HP")
        pilih("sv_frekuensi", "Setiap hari")
        for i, n in enumerate(JAWABAN_75, 1):
            pilih(f"sv_sus_{i}", str(n))
        for i, n in enumerate(KUALITAS_UJI, 1):
            pilih(f"sv_kualitas_{i}", str(n))
        d.find_element(By.CSS_SELECTOR, ".st-key-sv_suka textarea").send_keys("misinya seru")
        sebelum = jumlah_baris()
        d.find_element(By.XPATH, '//button[.//p[normalize-space()="Kirim penilaian"]]').click()
        terima = tunggu(lambda: "Terima kasih!" in teks(), 20)
        conn = sqlite3.connect(DB_UJI)
        akhir = conn.execute("SELECT skor, tugas_selesai, perangkat, kualitas FROM survei_sus ORDER BY rowid DESC "
                             "LIMIT 1").fetchone()
        conn.close()
        d.find_element(By.XPATH, '//button[.//p[normalize-space()="Kembali ke chat"]]').click()
        time.sleep(3)
        kartu_hilang = not d.find_elements(By.CSS_SELECTOR, ".st-key-misi_survei")
        cek("2.4", "Penilaian lengkap terkirim -> 'Terima kasih!', tersimpan dengan skor SUS, 5 jawaban kualitas "
                   "jawaban & misi yang selesai; kartu misi tidak tampil lagi",
            terima and jumlah_baris() == sebelum + 1 and akhir[0] == 75.0 and len(json.loads(akhir[1])) == 5
            and json.loads(akhir[3] or "[]") == KUALITAS_UJI and kartu_hilang,
            f"terima kasih={terima}; tersimpan skor {akhir[0]}, kualitas {akhir[3]}, misi {json.loads(akhir[1])}, "
            f"perangkat {akhir[2]}; kartu hilang={kartu_hilang}")
    finally:
        d.quit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bagian", choices=["1", "2"])
    a = p.parse_args()
    nyalakan_backend()
    if a.bagian in (None, "1"):
        uji_bagian_1()
    if a.bagian in (None, "2"):
        uji_bagian_2()
    lulus = sum(1 for h in _hasil if h[2])
    print(f"\n=== RINGKASAN: {lulus}/{len(_hasil)} skenario PASS ===")
    for kode, deskripsi, ok, _ in _hasil:
        if not ok:
            print(f"  FAIL {kode} {deskripsi}")
    sys.exit(0 if lulus == len(_hasil) else 1)


if __name__ == "__main__":
    main()
