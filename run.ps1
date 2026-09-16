# Launch the Kokoro TTS Studio (same behaviour as run.bat).
# Double-click run.bat instead if you'd rather avoid PowerShell anyway.
# Stop: close the browser tab (auto-stop) or press Ctrl+C here.
#
# OPTIONAL: $env:TTS_ENABLE_BRIDGE = '1' before launching to also start
# the experimental local API sidecar (see README -> "Experimental:
# local API mode"). When enabled, --no-auto-stop is required so the
# engine stays alive while the bridge is the only client.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
$py = '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $py)) {
    Write-Host 'venv not found - run update.ps1 first' -ForegroundColor Red
    exit 1
}

$env:NLTK_ALLOW_PROXIED_URLOPEN = '1'

# --- Optional bridge mode (experimental) ----------------------------------
$bridgeEnabled = ($env:TTS_ENABLE_BRIDGE -eq '1')
$argsContainNoAutoStop = ($args -contains '--no-auto-stop')

if ($bridgeEnabled -and -not $argsContainNoAutoStop) {
    Write-Host 'ERROR: TTS_ENABLE_BRIDGE=1 requires --no-auto-stop so the engine' -ForegroundColor Red
    Write-Host '       stays alive for the bridge. Use:' -ForegroundColor Red
    Write-Host '           $env:TTS_ENABLE_BRIDGE = "1"' -ForegroundColor Yellow
    Write-Host '           .\run.ps1 --no-auto-stop' -ForegroundColor Yellow
    exit 1
}

$bridgeProc = $null
if ($bridgeEnabled) {
    if (-not (Test-Path -LiteralPath 'bridge\bridge.py')) {
        Write-Host 'ERROR: bridge\bridge.py not found.' -ForegroundColor Red
        exit 1
    }
    $keyFile = Join-Path $root 'bridge.key'
    if (-not (Test-Path -LiteralPath $keyFile)) {
        Write-Host 'Generating a fresh bridge API key...' -ForegroundColor Cyan
        $key = & $py -c "import secrets; print(secrets.token_urlsafe(32))"
        Set-Content -LiteralPath $keyFile -Value $key -Encoding ascii -NoNewline
        $env:TTS_BRIDGE_API_KEY = $key
    } else {
        $env:TTS_BRIDGE_API_KEY = (Get-Content -LiteralPath $keyFile -Raw).Trim()
    }

    if (-not $env:TTS_BRIDGE_HOST) { $env:TTS_BRIDGE_HOST = '127.0.0.1' }
    if (-not $env:TTS_BRIDGE_PORT) { $env:TTS_BRIDGE_PORT = '7861' }
    if (-not $env:TTS_ENGINE_URL)  { $env:TTS_ENGINE_URL  = 'http://127.0.0.1:7860' }

    $mask = $env:TTS_BRIDGE_API_KEY
    if ($mask.Length -ge 12) {
        $masked = $mask.Substring(0,8) + '...' + $mask.Substring($mask.Length - 4)
    } else {
        $masked = '(short key - regenerate)'
    }

    Write-Host ''
    Write-Host '  Bridge mode ENABLED.  Engine will not auto-stop.' -ForegroundColor Cyan
    Write-Host ('    Bridge:  http://{0}:{1}' -f $env:TTS_BRIDGE_HOST, $env:TTS_BRIDGE_PORT) -ForegroundColor Cyan
    Write-Host ('    Engine:  {0}' -f $env:TTS_ENGINE_URL) -ForegroundColor Cyan
    Write-Host ('    API key: {0}  (full key in bridge.key)' -f $masked) -ForegroundColor Cyan
    Write-Host ''

    # Launch the bridge in a separate window so the engine can keep the foreground.
    $bridgeCmd = "`$env:TTS_BRIDGE_API_KEY='$($env:TTS_BRIDGE_API_KEY)'; `$env:TTS_BRIDGE_HOST='$($env:TTS_BRIDGE_HOST)'; `$env:TTS_BRIDGE_PORT='$($env:TTS_BRIDGE_PORT)'; `$env:TTS_ENGINE_URL='$($env:TTS_ENGINE_URL)'; & '$py' 'bridge\bridge.py'"
    Start-Process -FilePath 'powershell' `
                  -ArgumentList '-NoProfile','-Command', $bridgeCmd `
                  -WindowStyle Minimized `
                  -WorkingDirectory $root | Out-Null
}

# --- Standard engine start -------------------------------------------------
$inUse = & $py -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',7860)); s.close(); exit(0 if r==0 else 1)"
if ($LASTEXITCODE -eq 0) {
    Write-Host 'TTS Studio is already running - opening the browser tab.' -ForegroundColor Cyan
    Start-Process 'http://localhost:7860'
    exit 0
}

Write-Host 'Starting TTS Studio at http://localhost:7860 ...' -ForegroundColor Cyan
Write-Host 'Close the browser tab to stop the engine (Ctrl+C force-stops).'
Start-Job -ScriptBlock { Start-Sleep -Seconds 3; Start-Process 'http://localhost:7860' } | Out-Null

# Append --no-auto-stop to the engine invocation if the bridge needs the engine alive.
$engineArgs = @('app.py')
if ($bridgeEnabled) { $engineArgs += '--no-auto-stop' }

& $py @engineArgs 2>&1 | Tee-Object -FilePath 'app.log'
Write-Host 'Engine stopped.' -ForegroundColor Cyan
