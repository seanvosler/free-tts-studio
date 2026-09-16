@echo off
rem ============================================================
rem  Kokoro TTS Studio launcher - double-click to start the engine.
rem  Close the browser tab to stop the engine automatically.
rem  Works without PowerShell execution policy changes.
rem
rem  OPTIONAL: set TTS_ENABLE_BRIDGE=1 before launching to also start
rem  the experimental local API sidecar (see README -> "Experimental:
rem  local API mode"). When enabled, --no-auto-stop is required so the
rem  engine stays alive while the bridge is the only client.
rem ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found - run update.bat first.
    pause
    exit /b 1
)

set NLTK_ALLOW_PROXIED_URLOPEN=1

rem --- Optional bridge mode (experimental) ----------------------------------
set "BRIDGE_FLAGS="
if /I "%TTS_ENABLE_BRIDGE%"=="1" (
    if not "%~1"=="--no-auto-stop" if not "%~2"=="--no-auto-stop" if not "%~3"=="--no-auto-stop" if not "%~4"=="--no-auto-stop" if not "%~5"=="--no-auto-stop" if not "%~6"=="--no-auto-stop" if not "%~7"=="--no-auto-stop" if not "%~8"=="--no-auto-stop" if not "%~9"=="--no-auto-stop" (
        echo ERROR: TTS_ENABLE_BRIDGE=1 requires --no-auto-stop so the engine
        echo        stays alive for the bridge. Use:
        echo            set TTS_ENABLE_BRIDGE=1
        echo            run.bat --no-auto-stop
        pause
        exit /b 1
    )
    if not exist "bridge\bridge.py" (
        echo ERROR: bridge\bridge.py not found. Did you delete the bridge directory?
        pause
        exit /b 1
    )
    if not exist "bridge.key" (
        echo Generating a fresh bridge API key...
        for /f "delims=" %%K in ('".venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(32))"') do set "TTS_BRIDGE_API_KEY=%%K"
        > bridge.key echo !TTS_BRIDGE_API_KEY!
    ) else (
        for /f "usebackq tokens=* delims=" %%K in ("bridge.key") do set "TTS_BRIDGE_API_KEY=%%K"
    )
    if not defined TTS_BRIDGE_HOST set "TTS_BRIDGE_HOST=127.0.0.1"
    if not defined TTS_BRIDGE_PORT set "TTS_BRIDGE_PORT=7861"
    if not defined TTS_ENGINE_URL set "TTS_ENGINE_URL=http://127.0.0.1:7860"
    set "BRIDGE_FLAGS=--no-auto-stop"
    echo.
    echo  Bridge mode ENABLED.  Engine will not auto-stop.
    echo    Bridge:  http://%TTS_BRIDGE_HOST%:%TTS_BRIDGE_PORT%
    echo    Engine:  %TTS_ENGINE_URL%
    if defined TTS_BRIDGE_API_KEY (
        set "KEYLEN=0"
        for /l %%I in (1,1,99) do if not "!TTS_BRIDGE_API_KEY:~%%I,1!"=="" set "KEYLEN=%%I"
        set "KEYTAIL=!TTS_BRIDGE_API_KEY:~-4!"
        echo    API key: !TTS_BRIDGE_API_KEY:~0,8!...!KEYTAIL!  (full key in bridge.key)
    )
    echo.
    rem Start the bridge in a separate window so the engine can keep the foreground.
    start "TTS Studio Bridge" /min cmd /c "set TTS_BRIDGE_API_KEY=%TTS_BRIDGE_API_KEY%&& set TTS_BRIDGE_HOST=%TTS_BRIDGE_HOST%&& set TTS_BRIDGE_PORT=%TTS_BRIDGE_PORT%&& set TTS_ENGINE_URL=%TTS_ENGINE_URL%&& .venv\Scripts\python.exe bridge\bridge.py"
)

rem --- Standard engine start -------------------------------------------------
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

".venv\Scripts\python.exe" app.py %BRIDGE_FLAGS%
echo.
echo Engine stopped. Closing in 5 seconds...
timeout /t 5 >nul
exit /b 0
