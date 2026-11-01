# Detached restart of the ocr-app stack (run.py supervises OCR + app + worker).
# STARTUP_WAIT_S=240 so the OCR model server has room to load on CPU.
Set-Location 'C:\Users\PC\Documents\GitHub\ocr-app'
$env:STARTUP_WAIT_S = '240'
Start-Process -FilePath '.venv\Scripts\python.exe' `
    -ArgumentList 'run.py', '--no-browser' `
    -WorkingDirectory 'C:\Users\PC\Documents\GitHub\ocr-app' `
    -WindowStyle Hidden `
    -RedirectStandardOutput 'data\run_detached.out' `
    -RedirectStandardError 'data\run_detached.err'
Write-Host 'start-process issued'

$deadline = (Get-Date).AddSeconds(300)
$ok = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8090/health' -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if ($ok) {
    Write-Host "HEALTH_200 after $([int]((Get-Date) - ($deadline.AddSeconds(-300))).TotalSeconds)s"
} else {
    Write-Host 'HEALTH_TIMEOUT_300S'
    exit 1
}
