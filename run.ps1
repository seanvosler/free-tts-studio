# Launch the Kokoro TTS Studio (same behaviour as run.bat).
# Double-click run.bat instead if you prefer to avoid terminal/PowerShell anyway.
# Stop: close the browser tab (auto-stop) or press Ctrl+C here.

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
$py = '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $py)) {
    Write-Host 'venv not found - run update.ps1 first' -ForegroundColor Red
    exit 1
}

$env:NLTK_ALLOW_PROXIED_URLOPEN = '1'

$inUse = & $py -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',7860)); s.close(); exit(0 if r==0 else 1)"
if ($LASTEXITCODE -eq 0) {
    Write-Host 'TTS Studio is already running - opening the browser tab.' -ForegroundColor Cyan
    Start-Process 'http://localhost:7860'
    exit 0
}

Write-Host 'Starting TTS Studio at http://localhost:7860 ...' -ForegroundColor Cyan
Write-Host 'Close the browser tab to stop the engine (Ctrl+C force-stops).'
Start-Job -ScriptBlock { Start-Sleep -Seconds 3; Start-Process 'http://localhost:7860' } | Out-Null
& $py 'app.py' 2>&1 | Tee-Object -FilePath 'app.log'
Write-Host 'Engine stopped.' -ForegroundColor Cyan