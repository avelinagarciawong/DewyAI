import time
import random
import re
import os
from datetime import datetime, timedelta
import pandas as pd
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

os.makedirs("data", exist_ok=True)

# ── Konfigurasi ───────────────────────────────────────────
KEYWORDS = [
    "review skincare",
    "rekomendasi skincare",
    "skincare cocok",
    "skincare jerawat",
    "somethinc review",
    "skintific review",
    "wardah review",
    "cosrx review",
    "cerave review",
    "sunscreen review",
    "moisturizer review",
    "serum review",
    "toner review",
]

TARGET_TOTAL      = 300   # realistis untuk X; naikkan kalau ternyata lancar
TWEET_PER_WINDOW  = 40    # target ambil per kombinasi (keyword, rentang tanggal)
SCROLL_PER_WINDOW = 12    # batas scroll maksimum per kombinasi sebelum pindah
DELAY_MIN, DELAY_MAX = 2.5, 5.0

# Rentang tanggal yang mau disisir, dipecah per N hari (mengakali limit hasil pencarian)
TANGGAL_MULAI    = datetime(2026, 1, 1)
TANGGAL_AKHIR    = datetime(2026, 7, 2)
LEBAR_WINDOW_HARI = 21

FILE_OUTPUT = "data/raw_x_ulasan.csv"
# profil Chrome di root repo (folder di atas pipeline/), di mana pun repo-nya diletakkan
PROFILE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chrome_profile_x")


def delay():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def buat_windows_tanggal():
    windows = []
    cur = TANGGAL_MULAI
    while cur < TANGGAL_AKHIR:
        nxt = min(cur + timedelta(days=LEBAR_WINDOW_HARI), TANGGAL_AKHIR)
        windows.append((cur, nxt))
        cur = nxt
    return windows


def buat_driver():
    """Chrome dengan profile persisten — sesi login tersimpan antar-run, sama seperti Shopee v2."""
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    os.makedirs(PROFILE_DIR, exist_ok=True)
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    driver = uc.Chrome(options=options)
    return driver


def scroll_halaman(driver, kali=2):
    for _ in range(kali):
        driver.execute_script("window.scrollBy(0, 1200)")
        time.sleep(random.uniform(1.2, 2.2))


def clean_text(text: str) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def ada_link_shopee(text: str) -> bool:
    """Menandai tweet yang isinya hanya link Shopee, bukan opini asli."""
    return bool(re.search(r"shope\.ee|shopee\.co\.id", text, re.IGNORECASE))


def ambil_tweet_dari_halaman(driver) -> list:
    """Ambil semua tweet yang saat ini ter-render di layar."""
    hasil = []
    try:
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "article[data-testid='tweet']"))
        )
    except Exception:
        return []

    articles = driver.find_elements(By.CSS_SELECTOR, "article[data-testid='tweet']")

    for art in articles:
        try:
            # Teks tweet
            try:
                teks = art.find_element(By.CSS_SELECTOR, "div[data-testid='tweetText']").text
            except Exception:
                continue  # tweet tanpa teks (murni gambar/video) dilewati

            teks = clean_text(teks)
            if len(teks) < 10:
                continue

            # Username & tweet_id dari link status
            username, status_url, tweet_id = "", "", ""
            try:
                link_elem = art.find_element(By.CSS_SELECTOR, "a[href*='/status/']")
                status_url = link_elem.get_attribute("href")
                match = re.search(r"/([^/]+)/status/(\d+)", status_url)
                if match:
                    username, tweet_id = match.group(1), match.group(2)
            except Exception:
                pass

            if not tweet_id:
                continue

            # Tanggal
            tanggal = ""
            try:
                tanggal = art.find_element(By.CSS_SELECTOR, "time").get_attribute("datetime")
            except Exception:
                pass

            def ambil_metric(testid):
                try:
                    el = art.find_element(By.CSS_SELECTOR, f"[data-testid='{testid}']")
                    return el.text.strip() or "0"
                except Exception:
                    return "0"

            hasil.append({
                "tweet_id":               tweet_id,
                "username":               username,
                "tanggal":                tanggal,
                "teks":                   teks,
                "likes":                  ambil_metric("like"),
                "retweets":               ambil_metric("retweet"),
                "replies":                ambil_metric("reply"),
                "url":                    status_url,
                "mengandung_link_shopee": ada_link_shopee(teks),
                "sumber":                 "x",
                "scraped_at":             datetime.now().isoformat(),
            })
        except Exception:
            continue

    return hasil


def scrape_satu_window(driver, keyword: str, mulai: datetime, akhir: datetime, tweet_seen: set) -> list:
    """Scrape satu kombinasi keyword + rentang tanggal, scroll bertahap sampai habis/cukup."""
    q = f"{keyword} since:{mulai.strftime('%Y-%m-%d')} until:{akhir.strftime('%Y-%m-%d')} lang:id"
    url = f"https://x.com/search?q={q.replace(' ', '%20')}&src=typed_query&f=live"

    driver.get(url)
    delay()

    kumpulan = []
    scroll_kosong_beruntun = 0

    for _ in range(SCROLL_PER_WINDOW):
        tweet_halaman = ambil_tweet_dari_halaman(driver)
        baru = 0
        for tw in tweet_halaman:
            if tw["tweet_id"] not in tweet_seen:
                tweet_seen.add(tw["tweet_id"])
                kumpulan.append(tw)
                baru += 1

        scroll_kosong_beruntun = 0 if baru else scroll_kosong_beruntun + 1

        # 3x scroll berturut-turut tanpa tweet baru → window ini sudah habis
        if scroll_kosong_beruntun >= 3:
            break
        if len(kumpulan) >= TWEET_PER_WINDOW:
            break

        scroll_halaman(driver, kali=2)

    return kumpulan


def main():
    print("=" * 55)
    print("  X (TWITTER) SELENIUM SCRAPER — SKINCARE")
    print("=" * 55)
    print(f"  Target  : {TARGET_TOTAL} tweet")
    print(f"  Browser : Chrome akan terbuka otomatis\n")

    driver = buat_driver()
    semua_tweet = []
    tweet_seen = set()

    # Resume kalau file sudah ada
    if os.path.exists(FILE_OUTPUT):
        df_lama = pd.read_csv(FILE_OUTPUT)
        if not df_lama.empty:
            semua_tweet = df_lama.to_dict("records")
            tweet_seen = set(df_lama["tweet_id"].astype(str).tolist())
            print(f"  ↻ Resume: {len(semua_tweet)} tweet sudah ada di {FILE_OUTPUT}")

    windows = buat_windows_tanggal()

    try:
        driver.get("https://x.com")
        print("\n" + "=" * 60)
        print(" SILAKAN LOGIN DI BROWSER CHROME SEKARANG (akun X kamu).")
        print(" Setelah masuk ke beranda X, kembali ke terminal ini")
        print(" dan tekan ENTER untuk mulai scraping.")
        print("=" * 60 + "\n")
        input("Tekan ENTER setelah selesai login...")

        for keyword in KEYWORDS:
            if len(semua_tweet) >= TARGET_TOTAL:
                break

            print(f"\n🔍 Keyword: '{keyword}'")

            for (mulai, akhir) in windows:
                if len(semua_tweet) >= TARGET_TOTAL:
                    break

                print(f"    📅 {mulai.date()} → {akhir.date()} ...", end=" ", flush=True)
                hasil = scrape_satu_window(driver, keyword, mulai, akhir, tweet_seen)
                semua_tweet.extend(hasil)
                print(f"+{len(hasil)} tweet (total: {len(semua_tweet)})")

                # Simpan progress tiap window selesai
                pd.DataFrame(semua_tweet).to_csv(FILE_OUTPUT, index=False)

                # Delay lebih panjang antar window — X lebih sensitif rate-limit dari Shopee
                time.sleep(random.uniform(6, 12))

    except KeyboardInterrupt:
        print("\n\n  ⚠ Dihentikan manual — data yang sudah didapat tetap tersimpan.")

    finally:
        df_final = pd.DataFrame(semua_tweet)
        df_final.to_csv(FILE_OUTPUT, index=False)

        print("\n" + "=" * 55)
        print(f"  ✓ Total tweet : {len(df_final)} → {FILE_OUTPUT}")
        if not df_final.empty and "mengandung_link_shopee" in df_final.columns:
            n_link = int(df_final["mengandung_link_shopee"].sum())
            print(f"  ℹ Mengandung link Shopee (bukan opini murni): {n_link} "
                  f"({n_link / len(df_final) * 100:.1f}%)")
        print("=" * 55)

        input("\nTekan ENTER untuk menutup browser...")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()