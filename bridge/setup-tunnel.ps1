# Interactive helper for setting up the Cloudflare named tunnel.
#
# Walks you through the post-login steps (config file, DNS route) so
# you don't have to remember the exact incantations.
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\setup-tunnel.ps1

$ErrorActionPreference = 'Stop'

$cloudflared = $env:CLOUDFLARED_PATH
if (-not $cloudflared) {
  $cloudflared = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\cloudflared.exe'
}
if (-not (Test-Path -LiteralPath $cloudflared)) {
  Write-Host "cloudflared not found at $cloudflared" -ForegroundColor Red
  Write-Host "Install with:  winget install --id Cloudflare.cloudflared"
  exit 1
}

$cfDir = Join-Path $env:USERPROFILE '.cloudflared'
if (-not (Test-Path -LiteralPath $cfDir)) {
  New-Item -ItemType Directory -Path $cfDir | Out-Null
}

$tunnelName = 'tts-bridge'
$credFile = Join-Path $cfDir "$tunnelName.json"
$configFile = Join-Path $cfDir 'config.yml'

Write-Host ''
Write-Host '=== Cloudflare tunnel setup ===' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Step 1: log in to Cloudflare' -ForegroundColor Yellow
Write-Host "  I'll open your browser to authenticate. After approval, you'll"
Write-Host "  have a cert.pem at $cfDir\cert.pem"
Write-Host ''
$yn = Read-Host 'Press Enter to open the browser (or "skip" if you already logged in)'
if ($yn -ne 'skip') {
  & $cloudflared tunnel login
  if ($LASTEXITCODE -ne 0) {
    Write-Host "login failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
  }
}

Write-Host ''
Write-Host 'Step 2: create the named tunnel' -ForegroundColor Yellow
if (Test-Path -LiteralPath $credFile) {
  Write-Host "  Tunnel already exists ($credFile); skipping." -ForegroundColor Green
} else {
  & $cloudflared tunnel create $tunnelName
  if ($LASTEXITCODE -ne 0) {
    Write-Host "create failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
  }
}

Write-Host ''
Write-Host 'Step 3: write the config file' -ForegroundColor Yellow
$repourl = (Get-Content -LiteralPath (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'tunnel-config.yml') -Raw)
Write-Host '  Enter the subdomain you want to use (e.g. tts.example.com):'
$hostname = Read-Host '  hostname'
if (-not $hostname -or $hostname -notmatch '\.') {
  Write-Host 'invalid hostname' -ForegroundColor Red; exit 1
}

$config = @"
tunnel: $tunnelName
credentials-file: $credFile

ingress:
  - hostname: $hostname
    service: http://localhost:7861
    originRequest:
      noTLSVerify: true
  - service: http_status:404
"@
Set-Content -LiteralPath $configFile -Value $config -Encoding ascii
Write-Host "  Wrote $configFile" -ForegroundColor Green

Write-Host ''
Write-Host 'Step 4: add the DNS route' -ForegroundColor Yellow
$yn = Read-Host 'Press Enter to add the DNS record (or "skip" to do it later)'
if ($yn -ne 'skip') {
  & $cloudflared tunnel route dns $tunnelName $hostname
  if ($LASTEXITCODE -ne 0) {
    Write-Host "DNS route failed (exit $LASTEXITCODE)" -ForegroundColor Red
    Write-Host "  You can re-run this with:"
    Write-Host "    cloudflared tunnel route dns $tunnelName $hostname"
    exit 1
  }
}

Write-Host ''
Write-Host 'Step 5: done' -ForegroundColor Green
Write-Host "  Run the tunnel with:"
Write-Host "    cloudflared tunnel run $tunnelName"
Write-Host ""
Write-Host "  Or just rerun start-all.bat -- it'll detect the named tunnel"
Write-Host "  and use it instead of the quick tunnel."
Write-Host ""
Write-Host "  Test it:"
Write-Host "    curl https://$hostname/healthz"
Write-Host ''
