"""
scrape_deskripsi_produk.py

Scraping deskripsi lengkap tiap produk Shopee (kandungan, kegunaan, cara pakai)
dari link di data/clean_produk.csv, dengan pola yang sama seperti
02_scrape_shopee.py.

FITUR:
- Driver anti-deteksi dengan chrome_profile yang bisa di-reset.
- Panggil API item/get langsung dari halaman aktif (tanpa membuka tiap halaman produk secara
  fisik) supaya jejak request lebih ringan dan tidak gampang kena rate-limit di guest mode.
  driver.get(link) hanya dipakai sebagai cadangan (API gagal / perlu HTML untuk JSON-LD).
- Pendeteksi traffic verification / captcha dengan mekanisme lanjut manual.
- Checkpoint berkala agar aman dari crash/interupsi.
- Custom delay & istirahat berkala untuk meniru perilaku manusia.
"""

import time
import random
import json
import pandas as pd
import os
import re
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ── Konfigurasi ───────────────────────────────────────────
INPUT_FILE = "data/clean_produk.csv"
OUTPUT_FILE = "data/deskripsi_produk.csv"
# profil Chrome & Chrome for Testing disimpan di root repo (folder di atas pipeline/),
# di mana pun repo-nya diletakkan
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME_PROFILE_PATH = os.path.join(ROOT, "chrome_profile_deskripsi")
CHECKPOINT_EVERY = 20
DELAY_MIN = 6.0
DELAY_MAX = 15.0

CHROMIUM_DIR = os.path.join(ROOT, "chrome-for-testing")
CHROMIUM_EXE_PATH = os.path.join(CHROMIUM_DIR, "chrome-win64", "chrome.exe")

os.makedirs("data", exist_ok=True)


def delay():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def scroll_halaman(driver):
    """Menggulung halaman secara acak untuk meniru perilaku manusia."""
    try:
        # Scroll down slightly
        scroll_y = random.randint(300, 750)
        driver.execute_script(f"window.scrollBy(0, {scroll_y});")
        time.sleep(random.uniform(1.0, 2.5))
        # Scroll up slightly
        scroll_up = random.randint(100, 300)
        driver.execute_script(f"window.scrollBy(0, -{scroll_up});")
        time.sleep(random.uniform(0.5, 1.5))
    except Exception as e:
        print(f"      [Warning] Gagal melakukan scroll simulasi: {e}")


def ambil_deskripsi_fallback_jsonld(driver):
    """Mencoba mengambil deskripsi produk dari JSON-LD schema markup di halaman."""
    try:
        scripts = driver.find_elements(By.CSS_SELECTOR, 'script[type="application/ld+json"]')
        for s in scripts:
            try:
                content = s.get_attribute("innerHTML").strip()
                data = json.loads(content)
                if isinstance(data, dict) and data.get('@type') == 'Product':
                    desc = data.get('description')
                    if desc:
                        return desc.strip()
            except Exception:
                pass
    except Exception as e:
        print(f"      [Warning] Gagal ekstraksi JSON-LD: {e}")
    return None


def hapus_lock_files(profile_dir):
    """Menghapus file lock dari profile Chrome agar tidak terjadi konflik atau error."""
    lock_files = ["SingletonLock", "lockfile", "lock"]
    for f_name in lock_files:
        path = os.path.join(profile_dir, f_name)
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f"    [+] Berhasil menghapus lock file: {path}")
            except Exception as e:
                print(f"    [-] Gagal menghapus lock file {path}: {e}")


def check_and_solve_verification(driver):
    """Mendeteksi apakah halaman saat ini adalah halaman verifikasi/blokir Shopee,
    lalu meminta user menyelesaikannya secara manual sebelum melanjutkan.
    """
    url_aktif = driver.current_url
    if "verify/traffic" in url_aktif or "verify" in url_aktif:
        print("\n" + "!" * 60)
        print(" 🛑 DETEKSI BLOKIR / TRAFFIC VERIFICATION TERJADI!")
        print(f" URL Terdeteksi: {url_aktif}")
        print(" INSTRUKSI:")
        print(" 1. Jika Anda melihat slide CAPTCHA di browser, silakan selesaikan.")
        print(" 2. Jika Anda melihat tulisan 'Halaman Tidak Tersedia' (Blokir IP/Akun):")
        print("    - JANGAN LOGIN dengan email Anda yang lama karena email/IP Anda sudah ditandai!")
        print("    - Coba klik tombol 'Kembali ke Halaman Utama' atau logo Shopee di kiri atas.")
        print("    - Jika tetap muncul halaman tidak tersedia, Anda harus mengganti IP Internet Anda:")
        print("      (Contoh: Matikan-hidupkan modem router, ganti ke hotspot HP, atau gunakan VPN/Proxy).")
        print("    - Setelah itu, tutup program ini dan jalankan kembali, lalu pilih 'y' untuk")
        print("      mereset cache/cookies Chrome agar sesi bersih kembali.")
        print(" Setelah halaman utama Shopee normal kembali (tampak produk-produk di homepage),")
        print(" kembali ke terminal ini, lalu ketik 'lanjut' dan tekan ENTER.")
        print("!" * 60 + "\n")
        
        user_input = ""
        while user_input.strip().lower() != "lanjut":
            user_input = input("Ketik 'lanjut' lalu tekan ENTER jika sudah normal kembali di browser: ")
            
        print(" [!] Mengarahkan kembali ke beranda Shopee untuk verifikasi status...")
        driver.get("https://shopee.co.id")
        time.sleep(3)
        
        if "verify/traffic" in driver.current_url or "verify" in driver.current_url:
            print(" [!] Browser masih dialihkan ke halaman verifikasi/blokir.")
            check_and_solve_verification(driver)
        else:
            print(" [+] Verifikasi terlewati, melanjutkan scraping...\n")


def get_chrome_major_version():
    """Mengambil major version Google Chrome yang terinstall di Windows."""
    try:
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
            version, _ = winreg.QueryValueEx(key, "version")
            return int(version.split(".")[0])
        except:
            pass
            
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Google\Chrome\BLBeacon")
            version, _ = winreg.QueryValueEx(key, "version")
            return int(version.split(".")[0])
        except:
            pass
            
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Google Chrome")
            version, _ = winreg.QueryValueEx(key, "DisplayVersion")
            return int(version.split(".")[0])
        except:
            pass
    except Exception as e:
        print(f"    [Warning] Gagal mendeteksi versi Chrome via Registry: {e}")
    return None


def setup_chromium():
    """Mendownload dan mengekstrak Chrome for Testing jika belum ada."""
    version_txt_path = os.path.join(CHROMIUM_DIR, "version.txt")
    if os.path.exists(CHROMIUM_EXE_PATH) and os.path.exists(version_txt_path):
        with open(version_txt_path, "r") as f:
            version = f.read().strip()
            return CHROMIUM_EXE_PATH, int(version.split(".")[0])
        return CHROMIUM_EXE_PATH, 150 # default fallback

    print("\n[*] Mencari versi Chrome for Testing terbaru...")
    import requests
    import zipfile
    
    try:
        r = requests.get("https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json").json()
        version = r['channels']['Stable']['version']
        download_url = [d['url'] for d in r['channels']['Stable']['downloads']['chrome'] if d['platform'] == 'win64'][0]
    except Exception as e:
        print(f" [-] Gagal mengambil info versi: {e}")
        version = "150.0.7871.115"
        download_url = f"https://storage.googleapis.com/chrome-for-testing-public/{version}/win64/chrome-win64.zip"

    print(f"[*] Mengunduh Chrome for Testing v{version} untuk menghindari limit...")
    os.makedirs(CHROMIUM_DIR, exist_ok=True)
    
    try:
        r = requests.get(download_url, stream=True)
        r.raise_for_status()
        
        zip_path = os.path.join(CHROMIUM_DIR, "chrome-win64.zip")
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                
        print(" [+] Unduhan selesai. Mengekstrak...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(CHROMIUM_DIR)
            
        os.remove(zip_path)
        
        # Simpan versi ke version.txt
        with open(version_txt_path, "w") as f:
            f.write(version)
            
        print(f" [+] Berhasil memasang Chromium di: {CHROMIUM_EXE_PATH}\n")
        return CHROMIUM_EXE_PATH, int(version.split(".")[0])
    except Exception as e:
        print(f" [-] Gagal mengunduh/memasang Chromium: {e}")
        print("     Akan mencoba menggunakan Google Chrome bawaan sistem...")
        return None, None


def buat_driver():
    """Buat Chrome driver dengan setting anti-deteksi."""
    import shutil
    import sys
    
    profile_dir = CHROME_PROFILE_PATH
    
    reset = input(" Apakah Anda ingin mereset cache/cookies Chrome? (y untuk Ya / ENTER untuk Tidak): ").strip().lower()
    if reset == "y":
        if sys.platform.startswith("win"):
            import subprocess
            print("    [*] Menutup proses Chrome background...")
            subprocess.run(["taskkill", "/f", "/im", "chrome.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["taskkill", "/f", "/im", "chromedriver.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2.0)
            
        hapus_lock_files(profile_dir)
        try:
            shutil.rmtree(profile_dir)
            os.makedirs(profile_dir, exist_ok=True)
            print(" [+] Profile Chrome berhasil direset. Sesi akan mulai dari awal.")
        except Exception as e:
            print(f" [!] Gagal menghapus folder profile lama: {e}")
    else:
        os.makedirs(profile_dir, exist_ok=True)
        hapus_lock_files(profile_dir)
 
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-data-dir={profile_dir}")

    # Ambil Chromium portable
    chromium_exe, major_ver = setup_chromium()

    if chromium_exe and os.path.exists(chromium_exe):
        print(f"[*] Menjalankan dengan Chromium (Chrome for Testing) dari: {chromium_exe} (versi {major_ver})")
        try:
            driver = uc.Chrome(options=options, browser_executable_path=chromium_exe, version_main=major_ver)
        except Exception as e:
            print(f"    [!] Gagal menginisialisasi dengan Chromium: {e}")
            print("    Mencoba default patcher...")
            driver = uc.Chrome(options=options)
    else:
        major_version = get_chrome_major_version()
        if major_version:
            print(f"[*] Mendeteksi Google Chrome versi: {major_version}")
            try:
                driver = uc.Chrome(options=options, version_main=major_version)
            except Exception:
                print("    [!] Gagal menginisialisasi dengan versi Chrome spesifik. Mencoba default patcher...")
                driver = uc.Chrome(options=options)
        else:
            print("[*] Menggunakan default undetected_chromedriver...")
            driver = uc.Chrome(options=options)
    return driver


def extract_shopid_itemid(link: str):
    """Dari URL '...-i.600719961.15304662949' -> (shopid, itemid)"""
    match = re.search(r"-i\.(\d+)\.(\d+)", link)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def ambil_deskripsi_api(driver, shopid: str, itemid: str) -> dict:
    """Panggil API internal Shopee lewat browser (sudah login).
    Mengembalikan dict berisi status, data (raw response), dan error.
    """
    api_url = f"https://shopee.co.id/api/v4/item/get?itemid={itemid}&shopid={shopid}"
    script = f"""
    return fetch("{api_url}", {{
        headers: {{ 
            "Accept": "application/json",
            "x-api-source": "pc-pc",
            "x-requested-with": "XMLHttpRequest",
            "x-shopee-language": "id"
        }},
        credentials: "include"
    }})
    .then(response => {{
        if (!response.ok) {{
            return {{ status: response.status, data: null, error: "HTTP_ERROR_STATUS_" + response.status }};
        }}
        return response.json().then(res => ({{
            status: response.status,
            data: (res && res.data) ? res.data : null,
            error: (res && res.error) ? "API_ERROR_CODE_" + res.error : null
        }}));
    }})
    .catch(err => ({{ status: 0, data: null, error: err.message }}));
    """
    try:
        res = driver.execute_script(script)
        if not isinstance(res, dict):
            return {"status": 0, "data": None, "error": "unknown_js_response"}
        return res
    except Exception as e:
        return {"status": 0, "data": None, "error": str(e)}


def main():
    print("=" * 55)
    print("  SHOPEE DESKRIPSI PRODUK SCRAPER")
    print("=" * 55)

    if not os.path.exists(INPUT_FILE):
        print(f"[-] File input {INPUT_FILE} tidak ditemukan!")
        return

    produk = pd.read_csv(INPUT_FILE)
    print(f"[+] Berhasil memuat {len(produk)} produk dari {INPUT_FILE}")

    # Resume Check
    if os.path.exists(OUTPUT_FILE):
        print("\n" + "=" * 55)
        print("  DATA DESKRIPSI PRODUK TERSEDIA:")
        print(f"  File '{OUTPUT_FILE}' sudah ditemukan.")
        print("  [1] Lompati produk yang sudah pernah sukses discrape.")
        print("  [2] Mulai ulang dari awal (Hapus data lama & Scrape ulang semuanya).")
        print("=" * 55)
        pilihan = input("  Pilih tindakan (1 / 2, default 1): ").strip()
        if pilihan == "2":
            hasil = produk[["nama_produk", "link"]].copy()
            hasil["deskripsi"] = None
            hasil["atribut"] = None
            hasil["status"] = None
            print("  [+] Memulai ulang dari awal...")
        else:
            hasil = pd.read_csv(OUTPUT_FILE)
            print(f"  [+] Melanjutkan scraping. {hasil['status'].eq('ok').sum()} produk sudah discrape sebelumnya.")
    else:
        hasil = produk[["nama_produk", "link"]].copy()
        hasil["deskripsi"] = None
        hasil["atribut"] = None
        hasil["status"] = None

    # Input indeks awal untuk memulai dari baris tertentu di CSV (opsional)
    indeks_awal_input = input("\n  Masukkan indeks produk awal untuk memulai (atau tekan ENTER untuk mulai dari 0): ").strip()
    indeks_awal = 0
    if indeks_awal_input.isdigit():
        indeks_awal = int(indeks_awal_input)
        print(f"  [+] Memulai scraping dari indeks ke-{indeks_awal}")
    
    # Input batas maksimal scraping sesi ini
    limit_input = input("  Masukkan batas maksimal produk untuk discrape sesi ini (default: 50, ketik 0 untuk tanpa batas): ").strip()
    limit_scrape = 50
    if limit_input.isdigit():
        limit_scrape = int(limit_input)
    elif limit_input == "":
        limit_scrape = 50

    if limit_scrape > 0:
        print(f"  [+] Batas maksimal scraping sesi ini disetel ke: {limit_scrape} produk")
    else:
        print("  [+] Scraping tanpa batas maksimal produk (akan berjalan sampai selesai/dihentikan)")
    
    driver = buat_driver()

    try:
        # Buka Shopee homepage di awal agar origin browser diset ke shopee.co.id
        print("\n[*] Menghubungkan browser ke Shopee homepage untuk inisialisasi session...")
        driver.get("https://shopee.co.id")
        check_and_solve_verification(driver)

        print("\n" + "=" * 60)
        print(" 💡 SCRAPER AKAN BERJALAN DALAM GUEST MODE (TANPA LOGIN)")
        print(" Dengan tidak login, akun Anda tidak akan terancam terblokir.")
        print(" Jika halaman utama Shopee (shopee.co.id) sudah terbuka normal,")
        print(" kembali ke terminal ini, lalu ketik 'mulai' dan tekan ENTER.")
        print("=" * 60 + "\n")
        
        user_input = ""
        while user_input.strip().lower() != "mulai":
            user_input = input("Ketik 'mulai' lalu tekan ENTER jika browser sudah siap: ")

        total = len(hasil)
        scraped_count = 0
        for i in range(indeks_awal, total):
            # Cek jika statusnya sudah sukses 'ok' dan kita pilih resume
            if pd.notna(hasil.loc[i, "status"]) and hasil.loc[i, "status"] == "ok":
                continue

            # Cek batas maksimal scraping sesi ini
            if limit_scrape > 0 and scraped_count >= limit_scrape:
                print(f"\n[+] Batas maksimal scraping sesi ini ({limit_scrape} produk) telah tercapai. Menghentikan scraping...")
                break

            # Tambahkan jeda lebih lama secara acak setiap 5-8 produk yang diproses untuk menghindari deteksi bot
            if scraped_count > 0 and scraped_count % random.randint(5, 8) == 0:
                jeda_panjang = random.uniform(45.0, 90.0)
                print(f"\n[Istirahat] Jeda panjang selama {jeda_panjang:.1f} detik untuk menghindari deteksi bot...")
                time.sleep(jeda_panjang)

            nama_produk = hasil.loc[i, "nama_produk"]
            link = hasil.loc[i, "link"]
            
            # Pengaman jika nama_produk atau link bernilai NaN/kosong
            nama_produk_str = str(nama_produk) if pd.notna(nama_produk) else "Tanpa Nama"
            print(f"  [{i + 1}/{total}] [*] {nama_produk_str[:40]}...")

            if pd.isna(link) or not isinstance(link, str):
                hasil.loc[i, "status"] = "error: link kosong atau tidak valid"
                print(f"      [-] Link kosong atau tidak valid: {link}")
                continue

            shopid, itemid = extract_shopid_itemid(link)
            if not shopid or not itemid:
                hasil.loc[i, "status"] = "error: link tidak match format"
                print(f"      [-] Format link tidak cocok: {link}")
                continue

            # Naikkan hitungan produk yang diproses pada sesi ini
            scraped_count += 1

            # Proses scraping dengan retry & cooldown agar tidak mudah kena limit.
            # PENTING: berbeda dari versi sebelumnya, di sini kita TIDAK membuka halaman produk
            # secara fisik untuk tiap produk — API dipanggil langsung dari halaman yang sedang
            # aktif, persis seperti pola ambil_ulasan_produk() di 02_scrape_shopee.py. Guest
            # session Shopee jauh lebih cepat kena rate-limit kalau tiap produk memicu full page
            # load (semua JS/gambar/tracking script ikut ke-load dan dianalisis anti-bot mereka).
            # driver.get(link) hanya dipakai sebagai cadangan: saat API gagal, atau saat
            # butuh HTML halaman produk untuk ekstraksi JSON-LD.
            max_retries = 3
            info = {"deskripsi": "", "atribut": "", "status": "failed_all_retries"}
            halaman_dimuat = False  # apakah halaman produk sudah dibuka fisik untuk produk ini

            def buka_halaman_fallback():
                """Buka halaman produk secara fisik — hanya dipanggil saat benar-benar dibutuhkan."""
                nonlocal halaman_dimuat
                if halaman_dimuat:
                    return
                print("      [*] Membuka halaman produk secara fisik untuk fallback...")
                driver.get(link)
                delay()
                scroll_halaman(driver)
                check_and_solve_verification(driver)
                halaman_dimuat = True

            for attempt in range(max_retries):
                try:
                    # Pastikan verifikasi terlewati jika tab saat ini sedang diblokir
                    check_and_solve_verification(driver)

                    # Ambil deskripsi langsung lewat API tanpa navigasi fisik ke halaman produk
                    print(f"      [*] Mengambil data produk via API (Percobaan {attempt + 1}/{max_retries})...")
                    res = ambil_deskripsi_api(driver, shopid, itemid)
                    status = res.get("status", 0)
                    data = res.get("data")
                    error = res.get("error")
                except Exception as e:
                    status = 0
                    data = None
                    error = str(e)

                # Jika sukses lewat API
                if status == 200:
                    if data:
                        deskripsi = data.get("description", "")
                        attributes = data.get("attributes", [])
                        attr_text = " | ".join(
                            f"{a.get('name','')}:{a.get('value','')}" for a in attributes
                        ) if attributes else ""

                        info = {
                            "deskripsi": deskripsi,
                            "atribut": attr_text,
                            "status": "ok"
                        }
                        break
                    else:
                        # API kosong (status 200 tapi data null) -> fallback JSON-LD butuh HTML
                        # halaman produk, jadi baru di sini kita buka halaman secara fisik.
                        buka_halaman_fallback()
                        fallback_desc = ambil_deskripsi_fallback_jsonld(driver)
                        if fallback_desc:
                            print("      [+] Berhasil mengambil deskripsi via JSON-LD fallback (API data kosong).")
                            info = {
                                "deskripsi": fallback_desc,
                                "atribut": "JSON-LD Fallback",
                                "status": "ok"
                            }
                            break
                        else:
                            info = {
                                "deskripsi": "",
                                "atribut": "",
                                "status": "empty_data"
                            }
                            break

                # Jika API gagal (kena 429 atau 403, dll), baru buka halaman fisik & coba fallback JSON-LD
                else:
                    print(f"      [!] API gagal (Status: {status}, Error: {error}). Mencoba fallback JSON-LD...")
                    buka_halaman_fallback()
                    fallback_desc = ambil_deskripsi_fallback_jsonld(driver)
                    if fallback_desc:
                        print("      [+] Berhasil mengambil deskripsi via JSON-LD fallback!")
                        info = {
                            "deskripsi": fallback_desc,
                            "atribut": "JSON-LD Fallback",
                            "status": "ok"
                        }
                        break

                    # Jika fallback JSON-LD juga gagal, mari kita cooldown atau pecahkan captcha
                    if status == 429:
                        cooldown = 120 * (attempt + 1)
                        print(f"      [!] Terkena Rate Limit (HTTP 429). Mengambil jeda cooldown selama {cooldown} detik...")
                        time.sleep(cooldown)
                    elif status == 403 or (error and "verify" in str(error).lower()) or (error and "403" in str(error).lower()):
                        print("      [!] Deteksi blokir/CAPTCHA. Silakan verifikasi di browser.")
                        check_and_solve_verification(driver)
                    else:
                        print(f"      [!] Error tidak dikenal. Menunggu 10 detik sebelum percobaan berikutnya...")
                        time.sleep(10)
                    # Reset supaya percobaan berikutnya boleh coba buka halaman lagi kalau perlu
                    # (mis. setelah cooldown/verifikasi manual, state browser mungkin sudah berubah).
                    halaman_dimuat = False
                    continue

            # Simpan hasil ke dataframe
            hasil.loc[i, "deskripsi"] = info["deskripsi"]
            hasil.loc[i, "atribut"] = info["atribut"]
            hasil.loc[i, "status"] = info["status"]

            print(f"      [+] Status: {info['status']}")

            # Simpan checkpoint berkala
            if (i + 1) % CHECKPOINT_EVERY == 0 or (i + 1) == total:
                hasil.to_csv(OUTPUT_FILE, index=False)
                print(f"      [Checkpoint] Checkpoint disimpan -> {OUTPUT_FILE}")

            # Jeda reguler antar request
            delay()

    except KeyboardInterrupt:
        print("\n\n  [-] Dihentikan manual — progress yang sudah tersimpan tetap aman.")
        hasil.to_csv(OUTPUT_FILE, index=False)

    finally:
        print("\n" + "=" * 55)
        print("  SELESAI")
        if os.path.exists(OUTPUT_FILE):
            print(f"  [+] Deskripsi Produk : {OUTPUT_FILE}")
            print("-" * 55)
            # Tampilkan statistik status
            print(hasil["status"].value_counts())
        print("=" * 55)

        print("\n[+] Browser dibiarkan tetap terbuka.")
        input("Tekan ENTER di terminal ini untuk menutup browser Chrome dan keluar...")
        
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    main()
