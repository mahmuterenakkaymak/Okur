<#
install_small_brain.ps1 - küçük beyni kurar: llama.cpp (CPU) + Qwen3-VL-4B-Instruct.

    .\scripts\install_small_brain.ps1           eksikleri indirir, kurulu olana dokunmaz
    .\scripts\install_small_brain.ps1 -Check    kurulu/eksik raporu; her zaman çıkış 0
    .\scripts\install_small_brain.ps1 -Force    her satırı yeniden indirir

İndirilecek her şey scripts\small_brain_manifest.json'da satır satır durur:
{id, url, mirror_url?, dest, sha256, size_bytes}. `dest` kurulum dizinine göredir ve
o dizinin dışına çıkamaz. Kurulum yeri %LOCALAPPDATA%\ocr-small-brain'dir;
OCR_SMALL_BRAIN_DIR verilirse oraya kurulur (R7: model dosyaları repoya inmez).

İndirme sırası (R7): birincil CDN $PrimaryAttempts kez denenir — yani bir kez
tekrar —, tutmazsa ayna denenir; aynalar hf-mirror.com'dadır, çünkü HF'in Xet CDN'i
2026-11-06'da 2 GB'lık dosyada 30 sn üzerinde takıldı.

Her satır önce "<dest>.part" geçici dosyasına iner; boyutu ve SHA-256'sı o geçici
dosyada doğrulanmadan yerine taşınmaz (arşivse açılmaz). Doğrulama tutmazsa geçici
dosya silinir, kurulu dosyaya dokunulmaz ve çıkış 1 olur.
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ManifestPath = Join-Path $PSScriptRoot "small_brain_manifest.json"
$MirrorHost = "hf-mirror.com"
# ASSUMPTION: 2 = birincil CDN'ın ilk denemesi + bir tekrarı; ayna ancak ondan sonra.
$PrimaryAttempts = 2
# ASSUMPTION: manifest dest'leri app/config.py'nin baktığı üç yoldur. Qwen dosyası HF
# deposunda hangi adla yayınlanıyorsa (Qwen3-VL-4B-Instruct-IQ4_XS.gguf) o adla iner;
# yeniden adlandırma yoktur, böylece python run.py onu bulur ve dosya içinde
# olmadığı bir quant'ı adında taşımaz.

function Get-InstallDir {
    if ($env:OCR_SMALL_BRAIN_DIR) { return $env:OCR_SMALL_BRAIN_DIR }
    if (-not $env:LOCALAPPDATA) {
        Write-Host "hata: LOCALAPPDATA tanımlı değil — OCR_SMALL_BRAIN_DIR ile kurulum dizinini ver."
        exit 1
    }
    Join-Path $env:LOCALAPPDATA "ocr-small-brain"
}

function Get-DestPath {
    param([string]$InstallDir, [string]$Relative, [string]$Id)
    $tail = $Relative -replace "/", "\"
    $escapes = (@($tail -split "\\") -contains "..")
    if ([System.IO.Path]::IsPathRooted($Relative) -or $escapes) {
        Write-Host "hata: manifest satırı kurulum dizininin dışına yazıyor: $Id -> $Relative"
        exit 1
    }
    $root = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd("\")
    $target = [System.IO.Path]::GetFullPath((Join-Path $root $tail))
    if (-not $target.StartsWith($root + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "hata: manifest satırı kurulum dizininin dışına yazıyor: $Id -> $Relative"
        exit 1
    }
    $target
}

function Invoke-DownloadTry {
    param([string]$Url, [string]$OutFile)
    try {
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -UserAgent "ocr-app install_small_brain"
        return $true
    } catch {
        Write-Host "  uyarı: indirilemedi: $Url"
        Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
        return $false
    }
}

function Receive-Row {
    # birincil CDN $PrimaryAttempts kez denenir, tutmazsa ayna (hf-mirror.com) denenir
    param($Row, [string]$PartFile)
    for ($attempt = 1; $attempt -le $PrimaryAttempts; $attempt++) {
        if (Invoke-DownloadTry -Url $Row.url -OutFile $PartFile) { return }
        Start-Sleep -Seconds (2 * $attempt)
    }
    if (-not $Row.mirror_url) {
        Write-Host "hata: $($Row.id) — birincil CDN yanıt vermedi; bu satırda ayna tanımlı değil."
        exit 1
    }
    Write-Host "  aynaya düşülüyor ($MirrorHost): $($Row.mirror_url)"
    if (Invoke-DownloadTry -Url $Row.mirror_url -OutFile $PartFile) { return }
    Write-Host "hata: $($Row.id) — ne birincil CDN ne $MirrorHost verdi; bağlantıyı denetleyin."
    exit 1
}

function Test-DownloadedRow {
    # boyut ve SHA-256 geçici (.part) dosya üzerinde doğrulanır: kurulu dosyaya
    # yarım ya da bozuk indirme asla ulaşmaz.
    param($Row, [string]$PartFile)
    $size = (Get-Item -LiteralPath $PartFile).Length
    if ($size -ne [long]$Row.size_bytes) {
        Write-Host "hata: $($Row.id) boyutu tutmadı: $size / $($Row.size_bytes) bayt"
        Remove-Item -LiteralPath $PartFile -Force -ErrorAction SilentlyContinue
        exit 1
    }
    $expected = $Row.sha256.ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $PartFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        Write-Host "hata: $($Row.id) sha256 tutmadı: $actual != $expected"
        Remove-Item -LiteralPath $PartFile -Force -ErrorAction SilentlyContinue
        exit 1
    }
}

function Install-Row {
    param($Row, [string]$InstallDir)
    $dest = Get-DestPath -InstallDir $InstallDir -Relative $Row.dest -Id $Row.id
    if (-not $Force -and (Test-Path -LiteralPath $dest -PathType Leaf)) {
        Write-Host "kurulu, atlandı: $($Row.dest)"
        return $null
    }
    $parent = Split-Path -Parent $dest
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $partFile = "$dest.part"
    Write-Host ("indiriliyor: {0} ({1:N1} MB)" -f $Row.id, ($Row.size_bytes / 1MB))
    Receive-Row -Row $Row -PartFile $partFile
    Test-DownloadedRow -Row $Row -PartFile $partFile
    if ($Row.url -like "*.zip") {
        # arşiv doğrulandı; yerine llama-server.exe (ve yanındaki dll'ler) açılır
        Expand-Archive -LiteralPath $partFile -DestinationPath $parent -Force
        Remove-Item -LiteralPath $partFile -Force
        if (-not (Test-Path -LiteralPath $dest -PathType Leaf)) {
            Write-Host "hata: arşiv açıldı ama llama-server.exe yerinde değil: $dest"
            exit 1
        }
        Write-Host "açıldı: llama-server.exe, $parent"
    } else {
        Move-Item -LiteralPath $partFile -Destination $dest -Force
    }
    [pscustomobject]@{ Id = $Row.id; Path = $dest }
}

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    Write-Host "hata: manifest bulunamadı: $ManifestPath"
    exit 1
}
$rows = @(Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json)
$InstallDir = Get-InstallDir

if ($Check) {
    Write-Host "küçük beyin kurulumu: $InstallDir"
    $missing = @()
    foreach ($row in $rows) {
        $dest = Get-DestPath -InstallDir $InstallDir -Relative $row.dest -Id $row.id
        if (Test-Path -LiteralPath $dest -PathType Leaf) {
            Write-Host ("  ✓ {0,-26} {1,8:N1} MB" -f $row.id, ((Get-Item -LiteralPath $dest).Length / 1MB))
        } else {
            Write-Host "  ✗ $($row.dest) — eksik"
            $missing += $row.dest
        }
    }
    if ($missing.Count -eq 0) {
        Write-Host "durum: kurulu — python run.py yeterli."
    } else {
        Write-Host "durum: $($missing.Count) dosya eksik — kurmak için: .\scripts\install_small_brain.ps1"
    }
    exit 0
}

Write-Host "kurulum dizini: $InstallDir"
$installed = @()
foreach ($row in $rows) {
    $placed = Install-Row -Row $row -InstallDir $InstallDir
    if ($placed) { $installed += $placed }
}

Write-Host ""
Write-Host "kurulan küçük beyin:"
foreach ($entry in $installed) {
    $file = Get-Item -LiteralPath $entry.Path
    Write-Host ("  {0,-26} {1,8:N1} MB  {2}" -f $entry.Id, ($file.Length / 1MB), $file.FullName)
}
if ($installed.Count -eq 0) {
    Write-Host "  (yerine gelen yoktu; hepsi kurulu — yeniden indirmek için -Force)"
}
Write-Host "çalıştır: python run.py"
Write-Host "durumu:   .\scripts\install_small_brain.ps1 -Check"
