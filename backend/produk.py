"""
produk.py

Aturan data produk untuk panel admin (tambah & edit produk). Divalidasi di
backend karena dropdown/checkbox di form dapat dilewati dengan request langsung,
sedangkan nilai di luar kosakata baku membuat produk tidak pernah cocok dengan
profil pengguna mana pun.

Aturan (dari tabel ketentuan rancangan):
  - nama_produk, kategori, harga WAJIB. Kategori harus PERSIS salah satu
    kategori yang dikenal chatbot (models/nlu.py: KATEGORI) -- "Serum " atau
    "Serum" ditolak, bukan ditebak.
  - tipe_kulit_cocok / masalah_kulit_cocok: daftar yang isinya PERSIS nilai
    baku (5 tipe, 6 masalah, huruf kecil). "Kering" / "Kemerahan & Iritasi"
    ditolak.
  - minimal SALAH SATU dari tipe kulit, masalah kulit, kandungan, deskripsi
    terisi (aturan pembersihan dataset awal) -- produk tanpa satu pun sinyal
    itu tidak punya bahan untuk dicocokkan CBF.
  - harga > 0; di atas Rp10 juta tetap disimpan tapi ditandai harga_outlier
    (tidak pernah direkomendasikan, lihat cbf_engine.py).
  - kandungan dibersihkan dari kata generik ("dll", "original", "premium",
    ...) -- sama dengan pipeline/build_products_final.py.
  - link & brand opsional. Link yang diisi harus http(s):// (link lain,
    mis. "javascript:...", bisa dieksekusi browser kalau ditampilkan).
Teks disimpan apa adanya (setelah dirapikan) -- SQL selalu pakai parameter
(bukan string yang digabung), dan frontend meng-escape HTML saat menampilkan,
jadi "<script>" / "'; DROP TABLE" hanya jadi teks biasa.
"""
import math
import re
from typing import Any, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator

import nlu
from cbf_engine import HARGA_OUTLIER_THRESHOLD, MASALAH_KULIT_VALID, TIPE_KULIT_VALID

KATEGORI_VALID = tuple(nlu.KATEGORI)
# urutan tampil/simpan tag (bukan urutan yang diklik admin), sama dengan dataset
URUTAN_TIPE = ("berminyak", "kering", "kombinasi", "sensitif", "normal")
URUTAN_MASALAH = ("jerawat", "kusam", "hiperpigmentasi", "penuaan", "kemerahan_iritasi", "dehidrasi")
assert set(URUTAN_TIPE) == TIPE_KULIT_VALID and set(URUTAN_MASALAH) == MASALAH_KULIT_VALID

# sama dengan KANDUNGAN_NOISE di pipeline/build_products_final.py
KANDUNGAN_NOISE = {
    "other", "lainnya", "premium", "original", "dll", "masker", "produk",
    "bahan", "campuran", "-", "n/a", "na",
}

NAMA_MAKS, BRAND_MAKS, LINK_MAKS = 300, 100, 2000
KANDUNGAN_MAKS, DESKRIPSI_MAKS = 3000, 20000
HARGA_MAKS = 1_000_000_000_000  # batas kewajaran angka, bukan batas outlier

# pesan berbahasa Inggris: dipakai halaman admin (keputusan user, 30 Sep 2026)
PESAN_SINYAL = ("Invalid data: fill in at least one of suitable skin types, skin concerns, ingredients, or "
                "description. Without them the product will never match anyone's profile. (Ingredients that only "
                "contain generic words such as \"dll\" or \"original\" don't count.)")

_KONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def bersihkan_kandungan(teks):
    """'Niacinamide, dll, original' -> 'Niacinamide'. Kosong -> None."""
    if not teks:
        return None
    kept = [t.strip() for t in re.split(r"[,|]", teks)
            if t.strip() and t.strip().lower() not in KANDUNGAN_NOISE and not re.fullmatch(r"\d+", t.strip())]
    return ", ".join(kept) or None


def _teks(v, satu_baris=True):
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("invalid format")
    v = _KONTROL.sub("", v)
    v = " ".join(v.split()) if satu_baris else "\n".join(" ".join(b.split()) for b in v.strip().splitlines())
    return v.strip() or None


def _tag(v, valid, urutan, nama):
    """Daftar tag -> list baku. Menerima list, atau teks "a; b" (format dataset)."""
    if v is None:
        return []
    if isinstance(v, str):  # spasi di sekitar pemisah boleh ("kering; sensitif"), isinya tetap harus persis
        v = [t.strip() for t in re.split(r"[;,]", v) if t.strip()]
    if not isinstance(v, list) or not all(isinstance(t, str) for t in v):
        raise ValueError("invalid format")
    # elemen daftar harus PERSIS nilai baku -- "kering " / "Kering" ditolak, sama seperti kategori "Serum "
    salah = [t for t in v if t not in valid]
    if salah:
        raise ValueError(f"{nama} {', '.join(repr(t) for t in salah)} is not recognized. Choose from: "
                         f"{', '.join(urutan)} (exact, lowercase).")
    return [t for t in urutan if t in v]


def teks_tag(daftar):
    """['kering', 'sensitif'] -> 'kering; sensitif' (format kolom dataset). Kosong -> None."""
    return "; ".join(daftar) if daftar else None


def ada_sinyal(tipe, masalah, kandungan, deskripsi):
    return bool(tipe or masalah or bersihkan_kandungan(kandungan) or (deskripsi or "").strip())


class _AturanProduk(BaseModel):
    """Aturan per field -- dipakai bersama oleh tambah (ProdukBaru) dan edit
    (ProdukUbah), jadi form edit tidak mungkin lebih longgar dari form tambah.
    Field lain yang dikirim klien (id, harga_outlier, is_active, rating, ...)
    DIABAIKAN -- itu ditentukan server."""
    nama_produk: Any = None
    brand: Any = None
    kategori: Any = None
    harga: Any = None
    tipe_kulit_cocok: Any = None
    masalah_kulit_cocok: Any = None
    kandungan: Any = None
    deskripsi: Any = None
    link: Any = None

    @field_validator("nama_produk")
    @classmethod
    def _cek_nama(cls, v):
        v = _teks(v)
        if not v:
            raise ValueError("Product name is required.")
        if len(v) > NAMA_MAKS:
            raise ValueError(f"Product name can be at most {NAMA_MAKS} characters.")
        return v

    @field_validator("brand")
    @classmethod
    def _cek_brand(cls, v):
        v = _teks(v)
        if v and len(v) > BRAND_MAKS:
            raise ValueError(f"Brand can be at most {BRAND_MAKS} characters.")
        return v

    @field_validator("kategori")
    @classmethod
    def _cek_kategori(cls, v):
        if v is None or (isinstance(v, str) and not v):
            raise ValueError("Category is required.")
        if v not in KATEGORI_VALID:
            raise ValueError(f"Category {v!r} is not recognized. Choose one of: {', '.join(KATEGORI_VALID)}.")
        return v

    @field_validator("harga")
    @classmethod
    def _cek_harga(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("Price is required.")
        if isinstance(v, bool):
            raise ValueError("Price must be a number.")
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ValueError("Price must be a number.")
        if not math.isfinite(v) or v <= 0:
            raise ValueError("Price must be greater than 0.")
        if v > HARGA_MAKS:
            raise ValueError("Price is unrealistic.")
        return v

    @field_validator("tipe_kulit_cocok")
    @classmethod
    def _cek_tipe(cls, v):
        return _tag(v, TIPE_KULIT_VALID, URUTAN_TIPE, "Skin type")

    @field_validator("masalah_kulit_cocok")
    @classmethod
    def _cek_masalah(cls, v):
        return _tag(v, MASALAH_KULIT_VALID, URUTAN_MASALAH, "Skin concern")

    @field_validator("kandungan")
    @classmethod
    def _cek_kandungan(cls, v):
        v = _teks(v)
        if v and len(v) > KANDUNGAN_MAKS:
            raise ValueError(f"Ingredients can be at most {KANDUNGAN_MAKS} characters.")
        return bersihkan_kandungan(v)

    @field_validator("deskripsi")
    @classmethod
    def _cek_deskripsi(cls, v):
        v = _teks(v, satu_baris=False)
        if v and len(v) > DESKRIPSI_MAKS:
            raise ValueError(f"Description can be at most {DESKRIPSI_MAKS} characters.")
        return v

    @field_validator("link")
    @classmethod
    def _cek_link(cls, v):
        v = _teks(v)
        if not v:
            return None
        bagian = urlparse(v)
        if len(v) > LINK_MAKS or bagian.scheme not in ("http", "https") or not bagian.netloc:
            raise ValueError("Link must be a full web address starting with http:// or https://.")
        return v


class ProdukBaru(_AturanProduk):
    # field yang tidak dikirim tetap divalidasi (nama/kategori/harga kosong -> ditolak)
    model_config = ConfigDict(validate_default=True)
    # bukan isian: dicek terakhir, setelah 4 field sinyal, supaya pesan "minimal 1
    # dari 4 field" dilaporkan BERSAMAAN dengan error field lain
    sinyal_rekomendasi: Any = None

    @field_validator("sinyal_rekomendasi")
    @classmethod
    def _cek_sinyal(cls, _v, info):
        d = info.data
        if all(k in d for k in ("tipe_kulit_cocok", "masalah_kulit_cocok", "kandungan", "deskripsi")) and \
                not ada_sinyal(d["tipe_kulit_cocok"], d["masalah_kulit_cocok"], d["kandungan"], d["deskripsi"]):
            raise ValueError(PESAN_SINYAL)
        return None

    def ke_baris(self):
        """Isi kolom tabel products untuk produk baru."""
        return {
            "nama_produk": self.nama_produk, "brand": self.brand, "kategori": self.kategori,
            "harga": self.harga, "harga_outlier": self.harga > HARGA_OUTLIER_THRESHOLD,
            "tipe_kulit_cocok": teks_tag(self.tipe_kulit_cocok),
            "masalah_kulit_cocok": teks_tag(self.masalah_kulit_cocok),
            "sumber_label_tipe_kulit": "admin" if self.tipe_kulit_cocok else None,
            "sumber_label_masalah_kulit": "admin" if self.masalah_kulit_cocok else None,
            "kandungan": self.kandungan, "deskripsi": self.deskripsi, "link": self.link,
            "rating": None, "skor_sentimen": None, "jml_ulasan": 0, "sumber": "admin",
        }


class ProdukUbah(_AturanProduk):
    """Edit: HANYA field yang dikirim yang diubah (field lain tidak tersentuh),
    tiap field yang dikirim melewati aturan yang sama dengan tambah produk.
    versi = versi produk saat form dibuka (lihat db.ubah_produk)."""
    versi: int

    def perubahan(self, lama: dict):
        """-> (kolom yang berubah untuk db.ubah_produk, pesan error sinyal atau None)."""
        dikirim = self.model_fields_set - {"versi"}
        ubah = {}
        # hanya yang benar-benar beda dari data sekarang
        for k in dikirim & {"nama_produk", "brand", "kategori", "kandungan", "deskripsi", "link", "harga"}:
            if _beda(lama.get(k), getattr(self, k)):
                ubah[k] = getattr(self, k)
        if "harga" in ubah:
            ubah["harga_outlier"] = self.harga > HARGA_OUTLIER_THRESHOLD
        for k, sumber in (("tipe_kulit_cocok", "sumber_label_tipe_kulit"),
                          ("masalah_kulit_cocok", "sumber_label_masalah_kulit")):
            if k in dikirim and set(getattr(self, k)) != set(_pecah_tag(lama.get(k))):
                ubah[k] = teks_tag(getattr(self, k))
                ubah[sumber] = "admin" if ubah[k] else None
        hasil = {**lama, **ubah}
        sinyal_ok = ada_sinyal(hasil.get("tipe_kulit_cocok"), hasil.get("masalah_kulit_cocok"),
                               hasil.get("kandungan"), hasil.get("deskripsi"))
        return ubah, None if sinyal_ok else PESAN_SINYAL


def ke_json(p: dict) -> dict:
    """Baris products -> response API admin. Tag jadi list; info_terbatas =
    tanpa link, jadi RAG tidak bisa mengambil kutipan ulasan asli produk ini."""
    p = {k: (None if isinstance(v, float) and v != v else v) for k, v in p.items()}
    p["tipe_kulit_cocok"] = _pecah_tag(p.get("tipe_kulit_cocok"))
    p["masalah_kulit_cocok"] = _pecah_tag(p.get("masalah_kulit_cocok"))
    p["info_terbatas"] = not p.get("link")
    return p


def _pecah_tag(teks):
    """'kering; sensitif' -> ['kering', 'sensitif'] (format kolom dataset)."""
    return [t.strip() for t in (teks or "").split(";") if t.strip()]


def _beda(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) != float(b)
    return (a or None) != (b or None)
