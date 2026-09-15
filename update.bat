@echo off
rem Kokoro TTS Studio updater - works without PowerShell execution policy changes.
cd /d "%~dp0"

set NLTK_ALLOW_PROXIED_URLOPEN=1

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment with Python 3.11...
    py -3.11 -m venv .venv
    if errorlevel 1 exit /b 1
)

echo Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip

echo Upgrading the Kokoro stack...
".venv\Scripts\python.exe" -m pip install --upgrade kokoro phonemizer espeakng-loader misaki

".venv\Scripts\python.exe" -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

echo.
echo Done. You can now run run.bat
pause