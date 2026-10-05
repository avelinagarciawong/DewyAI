"""
pembatas.py -- pembatasan laju (rate limit) sederhana di memori proses.

Dipakai untuk:
  - POST /register: maksimal N percobaan per alamat IP dalam jendela waktu
    (mencegah bot membuat akun massal, skenario login/register 1.9).
  - POST /login: setelah N kali GAGAL untuk pasangan (IP, email) dalam
    jendela waktu, dikunci sementara (anti brute force, skenario 2.4).

Batasan yang disadari (ditulis juga di skripsi):
  - disimpan di memori 1 proses: hilang kalau server restart, dan tidak
    dibagi antar-proses kalau backend dijalankan dengan banyak worker.
    Untuk skala skripsi (1 proses uvicorn) ini cukup; produksi skala besar
    biasanya pakai Redis.
  - IP dibaca dari request.client.host. Frontend Streamlit memanggil backend
    dari server, jadi tanpa bantuan semua pengunjung terlihat ber-IP sama;
    karena itu frontend meneruskan IP asli pengunjung lewat X-Forwarded-For
    (frontend/core.py: ip_pengunjung) dan uvicorn menerjemahkannya ke
    request.client.host -- HANYA untuk request dari alamat di
    --forwarded-allow-ips (default 127.0.0.1 = frontend di mesin yang sama),
    sehingga klien lain tidak bisa memalsukan IP-nya.

Konfigurasi lewat env var dengan format "<maks>/<detik>", mis. "10/600".
"""
import os
import threading
import time
from collections import defaultdict, deque


def _baca_env(nama, default):
    nilai = os.getenv(nama, default)
    try:
        maks, detik = (int(x) for x in nilai.split("/"))
        return maks, detik
    except ValueError:
        maks, detik = (int(x) for x in default.split("/"))
        return maks, detik


class PembatasLaju:
    """Jendela geser: kunci boleh dipakai maksimal `maks` kali dalam
    `jendela` detik terakhir."""

    def __init__(self, maks, jendela):
        self.maks = maks
        self.jendela = jendela
        self._catatan = defaultdict(deque)
        self._kunci = threading.Lock()

    def _bersihkan(self, antrean, sekarang):
        while antrean and antrean[0] <= sekarang - self.jendela:
            antrean.popleft()

    def sisa_tunggu(self, kunci):
        """Detik yang harus ditunggu sebelum kunci boleh dipakai lagi (0 = boleh)."""
        sekarang = time.monotonic()
        with self._kunci:
            antrean = self._catatan[kunci]
            self._bersihkan(antrean, sekarang)
            if len(antrean) < self.maks:
                return 0
            return max(1, int(antrean[0] + self.jendela - sekarang) + 1)

    def catat(self, kunci):
        with self._kunci:
            self._catatan[kunci].append(time.monotonic())

    def coba(self, kunci):
        """Cek + catat sekaligus (untuk hal yang dihitung tiap percobaan,
        mis. register). return: detik tunggu (0 = boleh, sudah dicatat)."""
        sekarang = time.monotonic()
        with self._kunci:
            antrean = self._catatan[kunci]
            self._bersihkan(antrean, sekarang)
            if len(antrean) >= self.maks:
                return max(1, int(antrean[0] + self.jendela - sekarang) + 1)
            antrean.append(sekarang)
            return 0

    def reset(self, kunci):
        with self._kunci:
            self._catatan.pop(kunci, None)


def teks_tunggu(detik):
    menit = -(-detik // 60)
    return f"{menit} menit" if detik >= 60 else f"{detik} detik"


# register: percobaan per IP; login: percobaan GAGAL per (IP, email)
BATAS_REGISTER = PembatasLaju(*_baca_env("RATE_LIMIT_REGISTER", "10/600"))
BATAS_LOGIN_GAGAL = PembatasLaju(*_baca_env("RATE_LIMIT_LOGIN_GAGAL", "5/900"))
