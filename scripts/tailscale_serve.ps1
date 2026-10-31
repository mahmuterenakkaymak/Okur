<#
tailscale_serve.ps1 - HTTPS for the receipt OCR app, tailnet only.

    .\scripts\tailscale_serve.ps1              enable on the app port
    .\scripts\tailscale_serve.ps1 -Status      what tailscale serves right now
    .\scripts\tailscale_serve.ps1 -Rollback    take HTTPS back down

`tailscale serve` terminates TLS itself with the certificate Tailscale issues for
this machine's own ts.net name, so uvicorn keeps listening plain HTTP on
127.0.0.1:<AppPort> and run.py needs no TLS flags. The certificate is also written
under -CertDir (default data\certs) so the operator can inspect it; that folder
holds a private key and sits inside the gitignored data/ tree.

v1 rule (PROJECT_BRIEF.md 8): the tailnet is the only ingress. This script runs
`tailscale serve` and never `tailscale funnel` - funnel is the command that would
publish the app to the public internet.
#>
[CmdletBinding()]
param(
    [int]$AppPort = 8090,
    [int]$HttpsPort = 443,
    [string]$CertDir = "data\certs",
    [switch]$Status,
    [switch]$Rollback
)

$ErrorActionPreference = "Stop"
# ASSUMPTION: rollback only takes HTTPS down; the exported key under $CertDir
# stays on disk, because this project never deletes anything silently.
$RollbackCommand = "tailscale serve --https=$HttpsPort off"

function Invoke-Tailscale {
    param([string[]]$Arguments, [switch]$AllowFailure)
    $lines = @(& tailscale @Arguments 2>&1 | ForEach-Object { "$_" })
    $code = $LASTEXITCODE
    foreach ($line in $lines) { Write-Host $line }
    if ($code -ne 0 -and -not $AllowFailure) {
        Write-Host "hata: tailscale $($Arguments -join ' ') (çıkış $code)"
        exit 1
    }
    @{ code = $code; lines = $lines }
}

if ($Status) {
    Invoke-Tailscale -Arguments @("serve", "status") | Out-Null
    exit 0
}

if ($Rollback) {
    Invoke-Tailscale -Arguments @("serve", "--https=$HttpsPort", "off") | Out-Null
    Write-Host "HTTPS kaldırıldı: $RollbackCommand"
    Write-Host "sertifika dosyaları yerinde kaldı: $CertDir (silme kararı operatöre ait)"
    exit 0
}

if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
    Write-Host "hata: 'tailscale' yol üzerinde değil — önce Tailscale'i kurun."
    exit 1
}
if ((Invoke-Tailscale -Arguments @("status") -AllowFailure).code -ne 0) {
    Write-Host "hata: Tailscale oturumu kapalı — 'tailscale up' çalıştırın."
    exit 1
}

$hostName = (Invoke-Tailscale -Arguments @("status", "--json")).lines -join ""
$hostName = ((ConvertFrom-Json $hostName).Self.DNSName).TrimEnd(".")
if (-not $hostName) {
    Write-Host "hata: bu makinenin bir tailnet adı yok — admin konsolundan ayarlayın."
    exit 1
}

$probe = New-Object System.Net.Sockets.TcpClient
try {
    $probe.Connect("127.0.0.1", $AppPort)
} catch {
    Write-Host "uyarı: 127.0.0.1:$AppPort yanıt vermiyor — önce 'python run.py' çalıştırın."
} finally {
    $probe.Close()
}

New-Item -ItemType Directory -Force -Path $CertDir | Out-Null
$certFile = Join-Path $CertDir "$hostName.crt"
$keyFile = Join-Path $CertDir "$hostName.key"

Invoke-Tailscale -Arguments @("serve", "--bg", "--https=$HttpsPort", "http://127.0.0.1:$AppPort") | Out-Null

$cert = Invoke-Tailscale -Arguments @("cert", "--cert-file", $certFile, "--key-file", $keyFile, $hostName) -AllowFailure
if ($cert.code -ne 0) {
    Write-Host "uyarı: sertifika dışa aktarılamadı (tailnet ACL'sinde HTTPS sertifikaları kapalı olabilir); HTTPS yine çalışır."
}

Write-Host "HTTPS      ✓  https://$hostName/"
Write-Host "PWA        https://$hostName/app"
Write-Host "yönetim    https://$hostName/admin"
Write-Host "sertifika  $certFile"
Write-Host "geri alma  $RollbackCommand"
