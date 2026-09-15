# Update the Kokoro TTS stack (models, voices, tooling).
# Usage:  .\update.ps1

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    Write-Host 'Creating virtual environment with Python 3.11...' -ForegroundColor Cyan
    py -3.11 -m venv .venv
    if (-not $?) { exit 1 }
}

$py = '.venv\Scripts\python.exe'

Write-Host 'Upgrading pip...' -ForegroundColor Cyan
& $py -m pip install --upgrade pip

Write-Host 'Upgrading Kokoro stack...' -ForegroundColor Cyan
& $py -m pip install --upgrade kokoro phonemizer espeakng-loader misaki

Write-Host 'Verifying optional native bits (torch/CUDA)...' -ForegroundColor Cyan
& $py -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

Write-Host 'Done.' -ForegroundColor Green