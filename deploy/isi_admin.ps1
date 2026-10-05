<#
isi_admin.ps1 -- isi akun Admin pertama (ADMIN_EMAIL, ADMIN_PASSWORD) di /etc/dewai/dewai.env server.
Password diketik tersembunyi dan hanya dikirim lewat koneksi SSH -- tidak tampil di layar atau log.
Jalankan dari root repo (PowerShell):
  powershell -ExecutionPolicy Bypass -File deploy\isi_admin.ps1 -Server azureuser@<domain>
Akun admin dibuat backend SEKALI saat pertama menyala dengan database baru; mengubah nilai ini
setelahnya tidak mengganti password admin yang sudah ada (ganti lewat halaman Profile).
#>
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$Key = "$HOME\.ssh\dewai-key.pem"
)
$ErrorActionPreference = "Stop"

function Get-TeksBiasa([Security.SecureString]$aman) {
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($aman)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

Write-Host ""
Write-Host "Akun Admin pertama Dew AI (server: $Server)" -ForegroundColor Cyan
while ($true) {
    $email = (Read-Host "Email admin").Trim()
    if ($email -match '^[^@\s"''\\`$]+@[^@\s"''\\`$]+\.[A-Za-z]{2,}$') { break }
    Write-Host "Format email tidak valid, ulangi." -ForegroundColor Yellow
}
while ($true) {
    $pw1 = Get-TeksBiasa (Read-Host "Password admin (12-72 karakter, tidak tampil saat diketik)" -AsSecureString)
    $pw2 = Get-TeksBiasa (Read-Host "Ulangi password" -AsSecureString)
    if ($pw1 -cne $pw2) { Write-Host "Password tidak sama, ulangi." -ForegroundColor Yellow; continue }
    if ($pw1.Length -lt 12 -or $pw1.Length -gt 72) { Write-Host "Panjang harus 12-72 karakter." -ForegroundColor Yellow; continue }
    if ($pw1 -cnotmatch '^[!-~]+$' -or $pw1 -match '["''\\`$]') {
        Write-Host "Pakai huruf, angka, dan simbol biasa -- tanpa spasi, tanda kutip, \, `` atau `$." -ForegroundColor Yellow
        continue
    }
    if ($pw1 -eq "12345678" -or $pw1 -match '^(.)\1+$') { Write-Host "Password terlalu mudah ditebak." -ForegroundColor Yellow; continue }
    break
}

$OutputEncoding = [Text.Encoding]::ASCII
"ADMIN_EMAIL=$email`nADMIN_PASSWORD=$pw1`n" | & ssh -i $Key -o BatchMode=yes $Server "sudo python3 /opt/dewai/app/deploy/set_env.py"
$kode = $LASTEXITCODE
$pw1 = $null; $pw2 = $null
if ($kode -ne 0) { Write-Host "Gagal menyimpan ke server (kode $kode)." -ForegroundColor Red; exit $kode }
Write-Host ""
Write-Host "Tersimpan di server. Catat email & password ini di tempat aman -- dipakai untuk login admin." -ForegroundColor Green
Write-Host "Kabari Claude: 'admin sudah diisi'." -ForegroundColor Green
