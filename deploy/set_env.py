"""Isi / ubah nilai di /etc/dewai/dewai.env dari stdin (baris KEY=VALUE) tanpa menampilkan nilainya.

Dijalankan di server dengan sudo, nilai dikirim lewat pipa SSH (tidak muncul di layar, log, atau
daftar proses), mis. dari laptop:
    ... | ssh -i <kunci> azureuser@<domain> "sudo python3 /opt/dewai/app/deploy/set_env.py"
Dipakai deploy/isi_admin.ps1 (akun admin) dan untuk menyalin GROQ_API_KEY dari .env laptop.
"""
import os
import re
import sys
import tempfile

P = "/etc/dewai/dewai.env"
BOLEH = {"GROQ_API_KEY", "ADMIN_EMAIL", "ADMIN_PASSWORD", "ADMIN_NAMA", "RATE_LIMIT_REGISTER",
         "RATE_LIMIT_LOGIN_GAGAL"}
# systemd membaca file ini apa adanya: nilai tanpa kutip, jadi karakter yang bisa ditafsirkan lain ditolak
TERLARANG = re.compile(r"""["'\\`$\r\n]""")

baru = {}
for baris in sys.stdin.read().splitlines():
    baris = baris.strip().lstrip("\ufeff")
    if not baris or baris.startswith("#"):
        continue
    kunci, _, nilai = baris.partition("=")
    kunci, nilai = kunci.strip(), nilai.strip()
    if kunci not in BOLEH:
        sys.exit(f"GAGAL: kunci tidak dikenal: {kunci!r}")
    if not nilai or TERLARANG.search(nilai) or (kunci != "ADMIN_NAMA" and " " in nilai):
        sys.exit(f"GAGAL: nilai {kunci} kosong atau berisi karakter yang tidak diizinkan (spasi, kutip, \\, `, $)")
    baru[kunci] = nilai
if not baru:
    sys.exit("GAGAL: tidak ada baris KEY=VALUE yang diterima")

with open(P, encoding="utf-8") as f:
    isi = f.read().splitlines()
sisa = dict(baru)
for i, baris in enumerate(isi):
    kunci = baris.split("=", 1)[0].strip()
    if not baris.lstrip().startswith("#") and kunci in sisa:
        isi[i] = f"{kunci}={sisa.pop(kunci)}"
isi += [f"{k}={v}" for k, v in sisa.items()]

# tulis atomik, izin tetap root-only
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(P))
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write("\n".join(isi) + "\n")
os.chmod(tmp, 0o600)
os.replace(tmp, P)
print("diperbarui: " + ", ".join(f"{k} ({len(v)} karakter)" for k, v in baru.items()))
