import time
import random
import pandas as pd
import os
import re
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

os.makedirs("data", exist_ok=True)
# root repo (folder di atas pipeline/) -- profil Chrome disimpan di sini, di mana pun repo-nya diletakkan
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Konfigurasi ───────────────────────────────────────────
# Kategori Perawatan Wajah (Skincare)
CATEGORY_URL = "https://shopee.co.id/Perawatan-Wajah-cat.11043145.11043253"
# Halaman 1 s.d. 15 (index page dimulai dari 0 di Shopee)
PAGES_TO_SCRAPE = list(range(15))

TARGET_PRODUK = 500   # Jumlah target produk yang ingin dikumpulkan (disesuaikan menjadi 500)
DELAY_MIN     = 3.0
DELAY_MAX     = 7.0
MAX_ULASAN_PER_PRODUK = 50  # Batas maksimal ulasan per produk yang di-scrape

FILE_PRODUK = "data/raw_shopee_produk.csv"
FILE_ULASAN = "data/raw_shopee_ulasan.csv"

DEBUG_HTML       = True  # set False kalau sudah tidak perlu debug lagi
DEBUG_HTML_DIR   = "data/debug_html"
os.makedirs(DEBUG_HTML_DIR, exist_ok=True)


def delay():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


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
                print(f"    [-] Gagal menghapus lock file {path} (mungkin Chrome sedang berjalan): {e}")


def check_and_solve_verification(driver):
    """Mendeteksi apakah halaman saat ini adalah halaman verifikasi/blokir Shopee,
    lalu meminta user menyelesaikannya secara manual sebelum melanjutkan.
    """
    url_aktif = driver.current_url
    if "verify/traffic" in url_aktif or "verify" in url_aktif:
        print("\n" + "!" * 60)
        print(" 🛑 DETEKSI BOT / TRAFFIC VERIFICATION TERJADI!")
        print(f" URL Terdeteksi: {url_aktif}")
        print(" Silakan selesaikan CAPTCHA / Verifikasi di browser Chrome sekarang.")
        print(" Setelah selesai verifikasi dan halaman normal kembali (atau masuk ke Shopee),")
        print(" kembali ke terminal ini, lalu ketik 'lanjut' dan tekan ENTER.")
        print("!" * 60 + "\n")
        
        user_input = ""
        while user_input.strip().lower() != "lanjut":
            user_input = input("Ketik 'lanjut' lalu tekan ENTER jika sudah selesai verifikasi di browser: ")
            
        # Refresh halaman untuk memastikan keadaan baru
        print(" [!] Me-refresh halaman untuk verifikasi status...")
        driver.refresh()
        time.sleep(3)
        
        # Rekursif jika masih terdeteksi blokir
        if "verify/traffic" in driver.current_url or "verify" in driver.current_url:
            print(" [!] Browser masih mendeteksi halaman verifikasi/blokir.")
            check_and_solve_verification(driver)
        else:
            print(" [+] Verifikasi terlewati, melanjutkan scraping...\n")


def get_chrome_major_version():
    """Mengambil major version Google Chrome yang terinstall di Windows."""
    try:
        import winreg
        # 1. Coba dari HKEY_CURRENT_USER
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
            version, _ = winreg.QueryValueEx(key, "version")
            return int(version.split(".")[0])
        except:
            pass
            
        # 2. Coba dari HKEY_LOCAL_MACHINE
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Google\Chrome\BLBeacon")
            version, _ = winreg.QueryValueEx(key, "version")
            return int(version.split(".")[0])
        except:
            pass
            
        # 3. Fallback HKEY_LOCAL_MACHINE Wow6432Node
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Google Chrome")
            version, _ = winreg.QueryValueEx(key, "DisplayVersion")
            return int(version.split(".")[0])
        except:
            pass
    except Exception as e:
        print(f"    [Warning] Gagal mendeteksi versi Chrome via Registry: {e}")
    return None


def buat_driver():
    """Buat Chrome driver dengan setting anti-deteksi."""
    import shutil
    import sys
    
    profile_base = os.path.join(ROOT, "chrome_profile")
    profile_dir = profile_base
    
    reset = input(" Apakah Anda ingin mereset cache/cookies Chrome? (y untuk Ya / ENTER untuk Tidak): ").strip().lower()
    if reset == "y":
        # Hapus proses background agar tidak mengunci file
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
            print(f" [!] Gagal menghapus folder profile lama karena sedang dikunci oleh proses lain.")
            # Fallback ke folder baru
            suffix = 2
            while True:
                new_profile_dir = f"{profile_base}_v{suffix}"
                try:
                    if os.path.exists(new_profile_dir):
                        shutil.rmtree(new_profile_dir)
                    os.makedirs(new_profile_dir, exist_ok=True)
                    profile_dir = new_profile_dir
                    print(f" [+] Menggunakan folder profile alternatif baru: {profile_dir} (bebas lock & cookie lama!)")
                    break
                except Exception:
                    suffix += 1
    else:
        os.makedirs(profile_dir, exist_ok=True)
        hapus_lock_files(profile_dir)

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-data-dir={profile_dir}")

    major_version = get_chrome_major_version()
    if major_version:
        print(f"[*] Mendeteksi Google Chrome versi: {major_version}")
        try:
            # Coba pakai versi spesifik
            driver = uc.Chrome(options=options, version_main=major_version)
        except Exception:
            # Fallback ke default patcher jika gagal
            print("    [!] Gagal menginisialisasi dengan versi Chrome spesifik. Mencoba default patcher...")
            driver = uc.Chrome(options=options)
    else:
        print("[*] Menggunakan default undetected_chromedriver...")
        driver = uc.Chrome(options=options)
    return driver


def scroll_halaman(driver, kali=3):
    """Scroll ke bawah agar produk ter-load."""
    for _ in range(kali):
        driver.execute_script("window.scrollBy(0, 800)")
        time.sleep(1.5)


def debug_simpan_html(driver, page: int):
    """
    [DEBUG] Simpan HTML mentah halaman kategori + outerHTML dari beberapa
    card produk pertama, supaya bisa dibaca untuk memperbaiki selector.
    Aktif/nonaktif lewat flag DEBUG_HTML di atas.
    """
    if not DEBUG_HTML:
        return

    try:
        # 1) Simpan seluruh HTML halaman
        html_path = os.path.join(DEBUG_HTML_DIR, f"halaman_{page}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"    🐞 [debug] HTML halaman disimpan: {html_path}")

        # 2) Coba ambil beberapa kandidat "card" produk dengan selector yang lebar,
        #    lalu simpan outerHTML-nya satu per satu (3 contoh saja) agar mudah dibaca
        kandidat_selectors = [
            "div[data-sqe='item']",
            "li.shopee-search-item-result__item",
            "div.shopee-search-item-result__item",
            "[class*='shopee-search-item-result']",
            "a[href*='/product/']",
            "a[href*='-i.']",
        ]

        contoh_disimpan = 0
        for sel in kandidat_selectors:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
            except:
                elems = []

            if not elems:
                continue

            print(f"    🐞 [debug] selector '{sel}' → {len(elems)} elemen ditemukan")

            for i, el in enumerate(elems[:3]):
                try:
                    outer = driver.execute_script(
                        "return arguments[0].outerHTML;", el)
                except:
                    continue

                sel_aman = re.sub(r'[^a-zA-Z0-9]', '_', sel)[:40]
                nama_file = f"card_page{page}_{sel_aman}_{i}.html"

                card_path = os.path.join(DEBUG_HTML_DIR, nama_file)
                with open(card_path, "w", encoding="utf-8") as f:
                    f.write(outer)
                contoh_disimpan += 1

            # cukup 1 selector yang berhasil per halaman agar file tidak terlalu banyak
            break

        if contoh_disimpan:
            print(f"    🐞 [debug] {contoh_disimpan} contoh card produk disimpan ke {DEBUG_HTML_DIR}/")
        else:
            print("    🐞 [debug] Tidak ada elemen card yang cocok dengan selector kandidat manapun")

    except Exception as e:
        print(f"    🐞 [debug] Gagal menyimpan HTML debug: {e}")


def ambil_produk_dari_halaman(driver) -> list:
    """Ambil semua produk (termasuk link card produknya) yang tampil di halaman pencarian."""
    produk_list = []

    # Coba beberapa selector umum untuk item hasil pencarian Shopee
    selectors = [
        "div[data-sqe='item']",
        "div.shopee-search-item-result__item",
        "li.shopee-search-item-result__item",
        "[class*='shopee-search-item-result']",
        "a[href*='/product/']"
    ]

    items = []
    for selector in selectors:
        try:
            # Tunggu produk muncul
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            items = driver.find_elements(By.CSS_SELECTOR, selector)
            if items:
                break
        except:
            continue

    if not items:
        print("    ✗ Produk tidak ditemukan di halaman ini")
        return []

    # Lencana promo untuk disaring
    badge_labels = {"Garansi Harga Terbaik", "Pilih Lokal", "Stok Terbatas", "Star+", "Star", "Mall", "Grosir", "Cashback", "Diskon"}

    for item in items:
        try:
            # 1. Link produk (card)
            link = ""
            try:
                if item.tag_name == "a":
                    link = item.get_attribute("href")
                else:
                    link = item.find_element(By.TAG_NAME, "a").get_attribute("href")
            except:
                link = ""

            # Lewati produk yang tidak punya link (misal skeleton card)
            if not link:
                continue

            # 2. Nama produk
            # Sesuai saran, nama produk ada di div dengan class line-clamp-2 atau whitespace-normal
            nama = ""
            name_selectors = [
                "div[class*='line-clamp-2']",
                "div[class*='whitespace-normal']",
                "[class*='line-clamp-2']",
                "[data-sqe='name']",
                "div.ellipsis",
                "div[class*='ellipsis']"
            ]
            for name_sel in name_selectors:
                try:
                    nama = item.find_element(By.CSS_SELECTOR, name_sel).text.strip()
                    if nama:
                        break
                except:
                    continue

            # Lewati skeleton card atau card badge iklan yang salah deteksi
            if not nama or nama in badge_labels or len(nama) < 8:
                continue

            # 3. Harga
            # Sesuai saran, harga dipecah jadi span Rp dan nominalnya. Kita ambil parent dari span Rp untuk nominal gabungan.
            harga = ""
            try:
                rp_elem = item.find_element(By.XPATH, ".//span[text()='Rp']")
                parent_elem = rp_elem.find_element(By.XPATH, "..")
                harga = parent_elem.text.strip().replace("\n", "")
            except:
                # Fallback ke selector kelas harga jika XPath gagal
                for price_sel in ["[data-sqe='price']", "span[class*='price']", "div[class*='price']", "[class*='Price']", "[class*='text-base']"]:
                    try:
                        harga = item.find_element(By.CSS_SELECTOR, price_sel).text.strip().replace("\n", "")
                        if harga:
                            break
                    except:
                        continue

            if not harga:
                continue

            # 4. Rating
            rating = ""
            for rating_sel in ["span[class*='rating']", "div[class*='rating']", "[class*='Rating']"]:
                try:
                    rating = item.find_element(By.CSS_SELECTOR, rating_sel).text.strip()
                    if rating:
                        break
                except:
                    continue

            # 5. Terjual
            terjual = ""
            for sold_sel in ["[data-sqe='sold']", "div[class*='sold']", "[class*='Sold']", "[class*='sold']"]:
                try:
                    terjual = item.find_element(By.CSS_SELECTOR, sold_sel).text.strip()
                    if terjual:
                        break
                except:
                    continue

            produk_list.append({
                "nama_produk": nama,
                "harga":       harga,
                "rating":      rating,
                "terjual":     terjual,
                "link":        link,
                "scraped_at":  datetime.now().isoformat(),
                "sumber":      "shopee",
            })

        except Exception:
            continue

    return produk_list


def ambil_ulasan_produk(driver, link: str, nama_produk: str) -> list:
    """Ambil ulasan menggunakan Ratings API via fetch latar belakang dengan handling rate limit & auto-cooldown."""
    ulasan_list = []

    # Ekstrak shop_id dan item_id dari link produk
    shop_id, item_id = None, None
    try:
        # Pola 1: i.SHOP_ID.ITEM_ID
        match = re.search(r'i\.(\d+)\.(\d+)', link)
        if match:
            shop_id, item_id = match.group(1), match.group(2)
        else:
            # Pola 2: /product/SHOP_ID/ITEM_ID
            match = re.search(r'product/(\d+)/(\d+)', link)
            if match:
                shop_id, item_id = match.group(1), match.group(2)
    except Exception as e:
        print(f"    ✗ Gagal mengekstrak ID dari URL: {e}")

    if not shop_id or not item_id:
        print(f"    ✗ Format URL tidak didukung untuk API: {link}")
        return []

    # Gunakan API internal Shopee untuk mengambil rating bintang & ulasan teks
    api_url = f"https://shopee.co.id/api/v2/item/get_ratings?filter=0&limit={MAX_ULASAN_PER_PRODUK}&offset=0&shopid={shop_id}&itemid={item_id}&type=0"

    # Eksekusi fetch Javascript di context browser agar bypass CORS dan memanfaatkan cookies user aktif
    # Mengembalikan status HTTP dan detail error jika gagal agar Python bisa melakukan penanganan yang tepat.
    script = f"""
    return fetch("{api_url}", {{
        headers: {{
            "x-api-source": "pc-pc",
            "x-requested-with": "XMLHttpRequest",
            "x-shopee-language": "id"
        }}
    }})
    .then(response => {{
        if (!response.ok) {{
            return {{ status: response.status, ratings: null, error: "HTTP_ERROR_STATUS_" + response.status }};
        }}
        return response.json().then(data => ({{
            status: response.status,
            ratings: (data && data.data) ? data.data.ratings : null,
            error: (data && data.error) ? "API_ERROR_CODE_" + data.error : null
        }}));
    }})
    .catch(err => ({{ status: 0, ratings: null, error: err.message }}));
    """

    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Pastikan verifikasi terlewati jika browser saat ini sedang di halaman blokir
            check_and_solve_verification(driver)

            res = driver.execute_script(script)

            if not isinstance(res, dict):
                res = {"status": 0, "ratings": None, "error": "unknown_js_response"}

            status = res.get("status", 0)
            ratings = res.get("ratings")
            error = res.get("error")

            if status == 200:
                if ratings:
                    for rate in ratings:
                        teks = rate.get("comment", "")
                        bintang = rate.get("rating_star", 0)

                        # Filter ulasan: memiliki teks dan panjang > 5 karakter
                        if teks and len(teks.strip()) > 5:
                            ulasan_list.append({
                                "nama_produk":  nama_produk,
                                "link_produk":  link,
                                "teks_ulasan":  teks.strip().replace("\n", " "),
                                "rating":       bintang,
                                "sumber":       "shopee",
                                "scraped_at":   datetime.now().isoformat(),
                            })
                    return ulasan_list
                else:
                    print("    ✓ Tidak ada ulasan yang didapat dari API (status 200)")
                    return []

            elif status == 429:
                cooldown = 60 * (attempt + 1)
                print(f"    [!] Terkena Rate Limit (HTTP 429) pada percobaan {attempt + 1}/{max_retries}.")
                print(f"        Mengambil jeda cooldown selama {cooldown} detik sebelum mencoba kembali...")
                time.sleep(cooldown)
                continue

            elif status == 403 or (error and "verify" in str(error).lower()) or (error and "http_error_status_403" in str(error).lower()):
                print(f"    [!] Deteksi blokir/CAPTCHA (HTTP {status}, Error: {error}) pada percobaan {attempt + 1}/{max_retries}.")
                print("        Mencoba memuat halaman produk secara fisik untuk menyelesaikan verifikasi...")
                driver.get(link)
                delay()
                check_and_solve_verification(driver)
                continue

            else:
                print(f"    [!] Error Fetch API (Status: {status}, Error: {error}) pada percobaan {attempt + 1}/{max_retries}.")
                print("        Mencoba memuat halaman produk secara fisik sebagai fallback...")
                driver.get(link)
                delay()
                check_and_solve_verification(driver)
                continue

        except Exception as e:
            print(f"    ✗ Gagal eksekusi fetch pada percobaan {attempt + 1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
            continue

    print("    ✗ Gagal mendapatkan ulasan setelah semua percobaan.")
    return []


def ambil_produk_via_api(driver, match_id: str, page: int, sort_by: str = "relevancy") -> list:
    """Ambil daftar produk di halaman kategori menggunakan fetch API internal Shopee."""
    limit = 60
    offset = page * limit
    api_url = f"https://shopee.co.id/api/v4/search/search_items?by={sort_by}&limit={limit}&match_id={match_id}&newest={offset}&order=desc&page_type=search&scenario=PAGE_OTHERS&version=5"
    
    script = f"""
    return fetch("{api_url}", {{
        headers: {{
            "x-api-source": "pc-pc",
            "x-requested-with": "XMLHttpRequest",
            "x-shopee-language": "id"
        }}
    }})
        .then(response => response.json())
        .then(data => data.items || [])
        .catch(err => null);
    """
    
    try:
        items = driver.execute_script(script)
        produk_list = []
        if items:
            for item in items:
                basic = item.get("item_basic")
                if not basic:
                    continue
                
                itemid = basic.get("itemid")
                shopid = basic.get("shopid")
                nama = basic.get("name", "").strip()
                
                # Konversi harga (Shopee menyimpan harga dikali 100.000)
                price_raw = basic.get("price")
                if price_raw is not None:
                    harga = f"Rp{int(price_raw / 100000):,}".replace(",", ".")
                else:
                    harga = ""
                    
                rating_star = basic.get("item_rating", {}).get("rating_star", 0.0)
                rating = f"{rating_star:.1f}" if rating_star else ""
                
                sold = basic.get("historical_sold", 0)
                terjual = f"{sold} terjual" if sold else ""
                
                # Tautkan URL produk
                # Format standar Shopee: https://shopee.co.id/Nama-Produk-i.shopid.itemid
                nama_slug = re.sub(r'[^a-zA-Z0-9]+', '-', nama).strip("-")
                link = f"https://shopee.co.id/{nama_slug}-i.{shopid}.{itemid}"
                
                produk_list.append({
                    "nama_produk": nama,
                    "harga":       harga,
                    "rating":      rating,
                    "terjual":     terjual,
                    "link":        link,
                    "scraped_at":  datetime.now().isoformat(),
                    "sumber":      "shopee",
                })
        return produk_list
    except Exception as e:
        print(f"    ✗ Error ambil produk via API: {e}")
        return []


# ─────────────────────────────────────────────────────────
# TAHAP 1 — Scraping produk per halaman (+ kumpulkan link)
# ─────────────────────────────────────────────────────────
def tahap1_scrape_produk(driver) -> pd.DataFrame:
    print("\n" + "=" * 55)
    print("  TAHAP 1: SCRAPING PRODUK PER HALAMAN")
    print("=" * 55)
    print(f"  Target  : {TARGET_PRODUK} produk\n")

    semua_produk = []
    produk_seen  = set()

    # Ekstrak category_id dari CATEGORY_URL
    match = re.search(r'cat\.\d+\.(\d+)', CATEGORY_URL)
    category_id = match.group(1) if match else "11043253"

    # Kalau sudah ada file sebelumnya, lanjutkan (resume) berdasarkan link yang sudah tersimpan
    if os.path.exists(FILE_PRODUK):
        df_lama = pd.read_csv(FILE_PRODUK)
        if not df_lama.empty:
            semua_produk = df_lama.to_dict("records")
            produk_seen  = set(df_lama["nama_produk"].tolist())
            print(f"  ↻ Resume: {len(semua_produk)} produk sudah ada di {FILE_PRODUK}")

    # Menggunakan beberapa metode sorting agar bisa melewati limit 500 produk dari Shopee
    sort_options = ["relevancy", "sales", "ctime"]

    for sort_opt in sort_options:
        if len(semua_produk) >= TARGET_PRODUK:
            break

        print(f"\n=======================================================")
        print(f"  MENGGUNAKAN METODE SORTING: '{sort_opt.upper()}'")
        print(f"=======================================================")

        for page in PAGES_TO_SCRAPE:
            if len(semua_produk) >= TARGET_PRODUK:
                break

            print(f"\n🔍  Scraping Halaman Kategori ({sort_opt}): Halaman {page + 1} (page={page})")

            # Menggunakan query params untuk pencarian/kategori agar refresh token
            url_kategori = f"{CATEGORY_URL}?page={page}&sortBy={sort_opt}"
            driver.get(url_kategori)
            delay()

            # Cek dan tunggu jika ada halaman verifikasi
            check_and_solve_verification(driver)

            # Coba ambil via API internal dulu (lebih cepat dan aman dari skeleton loading)
            print("    🔎 Mengambil produk via Shopee API...")
            produk_halaman = ambil_produk_via_api(driver, category_id, page, sort_by=sort_opt)

            # Jika API mengembalikan kosong (biasanya karena limit offset/halaman di Shopee),
            # coba fallback ke DOM. Jika DOM juga kosong, maka break sort_opt ini
            if not produk_halaman:
                print("    ⚠ Gagal mengambil via API. Mencoba fallback ke scroll & DOM selector...")
                scroll_halaman(driver, kali=5)
                # [DEBUG] Simpan HTML debug untuk dianalisis
                debug_simpan_html(driver, page)
                produk_halaman = ambil_produk_dari_halaman(driver)
                print(f"    [Fallback] {len(produk_halaman)} produk ditemukan via DOM")
                
                # Jika fallback juga kosong, artinya halaman kategori memang sudah habis
                if not produk_halaman:
                    print("    ⚠ Halaman kosong via DOM & API. Selesai untuk sorting ini, pindah ke sorting berikutnya...")
                    break
            else:
                print(f"    ✓ {len(produk_halaman)} produk ditemukan via API")
                # [DEBUG] Tetap simpan HTML untuk keperluan debug
                debug_simpan_html(driver, page)

            produk_baru_di_halaman = 0
            for produk in produk_halaman:
                if len(semua_produk) >= TARGET_PRODUK:
                    break

                nama = produk["nama_produk"]
                if nama in produk_seen:
                    continue

                produk_seen.add(nama)
                semua_produk.append(produk)
                produk_baru_di_halaman += 1

            print(f"    ✓ {produk_baru_di_halaman} produk baru ditambahkan "
                  f"(total: {len(semua_produk)}/{TARGET_PRODUK})")

            # Simpan progress setiap selesai 1 halaman
            pd.DataFrame(semua_produk).to_csv(FILE_PRODUK, index=False)
            print(f"    💾 Tersimpan ke {FILE_PRODUK}")

    df_produk = pd.DataFrame(semua_produk)
    df_produk.to_csv(FILE_PRODUK, index=False)

    print("\n" + "-" * 55)
    print(f"  ✓ TAHAP 1 SELESAI — {len(df_produk)} produk → {FILE_PRODUK}")
    print("-" * 55)

    return df_produk


# ─────────────────────────────────────────────────────────
# TAHAP 2 — Buka tiap link produk satu per satu, scrape ulasan
# ─────────────────────────────────────────────────────────
def parse_rating_untuk_sort(rating_val):
    """Ubah rating jadi angka buat sorting. Yang kosong/tidak valid dianggap
    prioritas tinggi juga (ditaruh di depan bareng rating rendah) karena
    belum tentu produk itu bagus — perlu dicek juga."""
    try:
        return float(rating_val)
    except (ValueError, TypeError):
        return 0.0  # rating kosong -> prioritas tinggi (ikut discrape duluan)


def urutkan_produk_prioritas(df_produk: pd.DataFrame) -> pd.DataFrame:
    """Urutkan produk: rating rendah/kosong duluan, rating 5 sempurna belakangan.
    Tujuannya supaya ulasan yang terkumpul duluan lebih beragam."""
    df = df_produk.copy()
    df["_rating_sort"] = df["rating"].apply(parse_rating_untuk_sort)
    df = df.sort_values("_rating_sort", ascending=True).drop(columns=["_rating_sort"])
    return df.reset_index(drop=True)


def tahap2_scrape_ulasan_v2(driver, df_produk: pd.DataFrame):
    """Versi revisi: memproses ulasan berdasarkan urutan asli CSV, mendukung kelanjutan indeks."""
    FILE_ULASAN = "data/raw_shopee_ulasan.csv"

    print("\n" + "=" * 55)
    print("  TAHAP 2 (REVISI): SCRAPING ULASAN PER PRODUK")
    print("=" * 55)

    total_asli = len(df_produk)
    print(f"  Total produk asli di CSV: {total_asli}")

    # Input indeks awal untuk memulai dari baris tertentu di CSV
    indeks_awal_input = input("  Masukkan indeks produk awal untuk memulai (misal: 410, atau tekan ENTER untuk mulai dari 0): ").strip()
    indeks_awal = 0
    if indeks_awal_input.isdigit():
        indeks_awal = int(indeks_awal_input)

    if indeks_awal > 0:
        df_produk = df_produk.iloc[indeks_awal:]
        print(f"  ⏭️  Memotong data produk, memulai dari indeks ke-{indeks_awal} (tersisa {len(df_produk)} produk)")
    else:
        print("  ▶️  Memulai dari indeks 0")

    semua_ulasan = []
    link_sudah_discrape = set()

    # Lanjutan: produk yang sudah pernah di-scrape otomatis dilewati
    if os.path.exists(FILE_ULASAN):
        try:
            df_lama = pd.read_csv(FILE_ULASAN)
            if not df_lama.empty and "link_produk" in df_lama.columns:
                semua_ulasan = df_lama.to_dict("records")
                link_sudah_discrape = set(df_lama["link_produk"].dropna().tolist())
                print(f"  ↻ Resume: {len(link_sudah_discrape)} produk sudah pernah discrape, akan dilewati\n")
        except Exception as e:
            print(f"  [Warning] Gagal memuat data lama {FILE_ULASAN}: {e}. Memulai dari awal...")

    for idx, row in df_produk.iterrows():
        link = row.get("link", "")
        nama = row.get("nama_produk", "")
        rating = row.get("rating", "")

        if not link:
            continue
        if link in link_sudah_discrape:
            continue

        # Tambahkan jeda istirahat panjang (coffee break) setiap 10 produk untuk meniru pola manusia
        if idx > indeks_awal and idx % 10 == 0:
            jeda_panjang = random.uniform(30.0, 60.0)
            print(f"\n☕ [Istirahat] Jeda panjang selama {jeda_panjang:.1f} detik untuk menghindari deteksi bot...")
            time.sleep(jeda_panjang)

        print(f"  [{idx + 1}/{total_asli}] 🔎 (rating: {rating}) {nama[:40]}...")

        # Panggil fungsi ambil_ulasan_produk()
        ulasan = ambil_ulasan_produk(driver, link, nama)
        semua_ulasan.extend(ulasan)
        link_sudah_discrape.add(link)

        print(f"      ✓ {len(ulasan)} ulasan didapat (total terkumpul: {len(semua_ulasan)})")

        # Jeda regular antar produk
        delay()

        # Simpan progress tiap 10 produk
        if (idx + 1) % 10 == 0:
            pd.DataFrame(semua_ulasan).to_csv(FILE_ULASAN, index=False)
            print(f"      💾 Progress tersimpan: {len(semua_ulasan)} ulasan total\n")

    df_ulasan = pd.DataFrame(semua_ulasan)
    df_ulasan.to_csv(FILE_ULASAN, index=False)

    print("\n" + "-" * 55)
    print(f"  ✓ TAHAP 2 (REVISI) SELESAI — {len(df_ulasan)} ulasan → {FILE_ULASAN}")
    print("-" * 55)

    return df_ulasan

# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  SHOPEE SELENIUM SCRAPER (2 TAHAP)")
    print("=" * 55)

    skip_tahap1 = False
    if os.path.exists(FILE_PRODUK):
        print("\n" + "=" * 55)
        print("  DATA PRODUK TERSEDIA:")
        print("  File 'data/raw_shopee_produk.csv' sudah ditemukan.")
        print("  [1] Lompati Tahap 1, langsung scrape ulasan (Tahap 2) dari CSV ini.")
        print("  [2] Mulai ulang dari awal (Hapus data lama & Scrape produk baru).")
        print("=" * 55)
        pilihan_tahap = input("  Pilih tindakan (1 / 2, default 1): ").strip()
        if pilihan_tahap != "2":
            skip_tahap1 = True

    driver = buat_driver()

    try:
        if not skip_tahap1:
            # Buka Shopee dulu agar dapat cookies & bisa login manual
            print("\n[*] Membuka Shopee...")
            driver.get("https://shopee.co.id")
            
            # Cek dan tunggu jika ada halaman verifikasi saat awal masuk
            check_and_solve_verification(driver)

            print("\n" + "=" * 60)
            print(" SILAKAN LOGIN / SELESAIKAN VERIFIKASI DI BROWSER CHROME SEKARANG")
            print(" Setelah selesai login dan masuk ke beranda Shopee,")
            print(" kembali ke terminal ini untuk memulai scraping.")
            print("=" * 60 + "\n")
            
            # Mencegah bypass otomatis akibat buffer tombol enter dengan mewajibkan ketik 'mulai'
            user_input = ""
            while user_input.strip().lower() != "mulai":
                user_input = input("Ketik 'mulai' lalu tekan ENTER jika Anda sudah selesai login di Chrome: ")

            df_produk = tahap1_scrape_produk(driver)

            if df_produk.empty:
                print("\n  ⚠ Tidak ada produk yang berhasil diambil.")
                return
        else:
            print("\n[+] Membaca daftar produk dari data/raw_shopee_produk.csv...")
            df_produk = pd.read_csv(FILE_PRODUK)
            
            # PENTING: Buka Shopee homepage sekali di awal agar origin browser diset ke shopee.co.id
            print("\n[*] Menghubungkan browser ke Shopee homepage untuk inisialisasi session...")
            driver.get("https://shopee.co.id")
            check_and_solve_verification(driver)

        # ── TAHAP 2 ──
        tahap2_scrape_ulasan_v2(driver, df_produk)

    except KeyboardInterrupt:
        print("\n\n  ⚠ Dihentikan manual — data yang sudah tersimpan tetap aman "
              "(progress sudah disimpan bertahap).")

    finally:
        print("\n" + "=" * 55)
        print("  SELESAI (Tahap 1 & 2)")
        if os.path.exists(FILE_PRODUK):
            print(f"  ✓ Produk : {FILE_PRODUK}")
        if os.path.exists(FILE_ULASAN):
            print(f"  ✓ Ulasan : {FILE_ULASAN}")
        print("=" * 55)

        # Biarkan browser tetap terbuka agar user bisa melihat dan tidak memicu WinError 6 secara tiba-tiba
        print("\n[+] Browser dibiarkan tetap terbuka.")
        input("Tekan ENTER di terminal ini untuk menutup browser Chrome dan keluar...")
        
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    main()