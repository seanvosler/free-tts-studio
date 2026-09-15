@echo off
rem ============================================================
rem  Kokoro TTS Studio launcher - double-click to start the engine.
rem  Close the browser tab to stop the engine automatically.
rem  Works without PowerShell execution policy changes.
rem ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found - run update.bat first.
    pause
    exit /b 1
)

set NLTK_ALLOW_PROXIED_URLOPEN=1

rem Is the engine already running? (connect test to port 7860)
".venv\Scripts\python.exe" -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',7860)); s.close(); exit(0 if r==0 else 1)"
if not errorlevel 1 (
    echo TTS Studio is already running - opening the browser tab.
    start "" "http://localhost:7860"
    exit /b 0
)

echo Starting TTS Studio engine at http://localhost:7860 ...
echo Tip: close the browser tab to stop the engine.
start "" /b powershell -NoProfile -Command "Start-Sleep 3; Start-Process 'http://localhost:7860'"

".venv\Scripts\python.exe" app.py
echo.
echo Engine stopped. Closing in 5 seconds...
timeout /t 5 >nul
exit /b 0