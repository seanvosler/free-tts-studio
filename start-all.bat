@echo off
rem ============================================================
rem  Free TTS Studio -- single-process orchestrator.
rem  Starts (or restarts) the engine, bridge, and tunnel in
rem  the right order with health checks between each step.
rem
rem  This is what Task Scheduler launches at logon.
rem ============================================================
cd /d "%~dp0"

rem --- locations (override via env if installed elsewhere) --------
set "REPO=%~dp0"
set "BRIDGE_DIR=%REPO%"
set "ENGINE_DIR=%TTS_ENGINE_DIR%"
if "%ENGINE_DIR%"=="" set "ENGINE_DIR=%USERPROFILE%\OneDrive\Documents\My ARK Mods\generalProjects\kokoro-tts"
set "KITTEN_DIR=%TTS_KITTEN_DIR%"
if "%KITTEN_DIR%"=="" set "KITTEN_DIR=%USERPROFILE%\OneDrive\Documents\My ARK Mods\generalProjects\kitten-tts"
set "TUNNEL_NAME=%TTS_TUNNEL_NAME%"
if "%TUNNEL_NAME%"=="" set "TUNNEL_NAME=tts-bridge"
set "CLOUDFLARED=%CLOUDFLARED_PATH%"
if "%CLOUDFLARED%"=="" set "CLOUDFLARED=%LOCALAPPDATA%\Microsoft\WindowsApps\cloudflared.exe"

rem --- output dir for synthesized WAVs ---------------------------------
rem Override by setting TTS_OUTPUT_DIR before calling start-all.bat.
rem Default: Google Drive folder (auto-syncs to the cloud).
if "%TTS_OUTPUT_DIR%"=="" set "TTS_OUTPUT_DIR=G:\My Drive\voicesseancoTTSfiles"

echo.
echo  ============================================
echo   Free TTS Studio -- orchestrator
echo   %DATE% %TIME%
echo  ============================================
echo   kokoro:   %ENGINE_DIR%
echo   kitten:   %KITTEN_DIR%
echo   bridge:   %BRIDGE_DIR%
echo   tunnel:   %TUNNEL_NAME%  (%CLOUDFLARED%)
echo.

rem --- 1. Kokoro engine --------------------------------------------------
echo [1/4] starting Kokoro engine on 7860...
set NLTK_ALLOW_PROXIED_URLOPEN=1
if not exist "%ENGINE_DIR%\.venv\Scripts\python.exe" (
    echo   WARNING: engine venv not found at %ENGINE_DIR%\.venv
    echo   continuing anyway (engine start will likely fail)
)

rem Detect already-running engine
"%ENGINE_DIR%\.venv\Scripts\python.exe" -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',7860)); s.close(); exit(0 if r==0 else 1)" 2>nul
if not errorlevel 1 (
    echo   kokoro already running on 7860
) else (
    if not exist "%ENGINE_DIR%\app.py" (
        echo   WARNING: engine app.py not found -- skipping engine start
    ) else (
rem Start engine detached via the v2 launcher (uses cmd shell for reliable stdin redirect).
set "TTS_ENGINE_DIR=%ENGINE_DIR%"
"%ENGINE_DIR%\.venv\Scripts\python.exe" "%BRIDGE_DIR%\_orchestrator_launch_engine_v2.py"
        echo   waiting for kokoro port 7860...
        set /a tries=0
        :wait_kokoro
        set /a tries+=1
        if !tries! gtr 60 (
            echo   TIMEOUT: kokoro engine did not come up in 60s
            goto :no_kokoro
        )
        "%ENGINE_DIR%\.venv\Scripts\python.exe" -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',7860)); s.close(); exit(0 if r==0 else 1)" 2>nul
        if errorlevel 1 (
            timeout /t 2 >nul
            goto :wait_kokoro
        )
        echo   kokoro UP
    )
)
:no_kokoro

rem --- 1b. Kitten engine --------------------------------------------
echo [2/4] starting KittenTTS-2 engine on 7862...
rem Kitten shares the kokoro venv (junction at KITTEN_DIR\.venv) so we
rem only need ONE PyTorch install (~2 GB). PYTHONUTF8=1 is required by
rem kittenml on Windows.
if not exist "%KITTEN_DIR%\app.py" (
    echo   WARNING: %KITTEN_DIR%\app.py not found -- skipping kitten start
) else (
    "%ENGINE_DIR%\.venv\Scripts\python.exe" -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',7862)); s.close(); exit(0 if r==0 else 1)" 2>nul
    if not errorlevel 1 (
        echo   kitten already running on 7862
    ) else (
        set "TTS_ENGINE_DIR=%KITTEN_DIR%"
        set "TTS_OUTPUT_DIR=%TTS_OUTPUT_DIR%"
        set "PYTHONUTF8=1"
        "%ENGINE_DIR%\.venv\Scripts\python.exe" "%KITTEN_DIR%\_orchestrator_launch_kitten.py"
        echo   waiting for kitten port 7862...
        set /a tries=0
        :wait_kitten
        set /a tries+=1
        if !tries! gtr 90 (
            echo   TIMEOUT: kitten engine did not come up in 90s
            goto :no_kitten
        )
        "%ENGINE_DIR%\.venv\Scripts\python.exe" -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',7862)); s.close(); exit(0 if r==0 else 1)" 2>nul
        if errorlevel 1 (
            timeout /t 2 >nul
            goto :wait_kitten
        )
        echo   kitten UP
    )
)
:no_kitten

rem --- 2. Bridge ---------------------------------------------------
echo [3/4] starting bridge...
if not exist "%BRIDGE_DIR%\bridge.py" (
    echo   WARNING: bridge.py not found -- skipping bridge start
    goto :no_bridge
)

rem Detect already-running bridge by port (reliable, no PowerShell quoting issues).
"%ENGINE_DIR%\.venv\Scripts\python.exe" -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',7861)); s.close(); exit(0 if r==0 else 1)" 2>nul
if not errorlevel 1 (
    echo   bridge already running on 7861
    goto :no_bridge
)

rem Generate API key if missing -- delegated to _orchestrator_launch_bridge.py
if not exist "%BRIDGE_DIR%\bridge.key" (
    echo   bridge.key missing; launcher will generate one
)
if not defined TTS_BRIDGE_HOST set "TTS_BRIDGE_HOST=0.0.0.0"
if not defined TTS_BRIDGE_PORT set "TTS_BRIDGE_PORT=7861"
if not defined TTS_ENGINE_URL set "TTS_ENGINE_URL=http://127.0.0.1:7860"

rem Launch bridge detached via a small launcher script (no quote hell in cmd).
set "TTS_BRIDGE_DIR=%BRIDGE_DIR%"
set "TTS_ENGINE_DIR=%ENGINE_DIR%"
"%ENGINE_DIR%\.venv\Scripts\python.exe" "%BRIDGE_DIR%\_orchestrator_launch_bridge.py"

echo   waiting for bridge port 7861...
set /a tries=0
:wait_bridge
set /a tries+=1
if !tries! gtr 30 (
    echo   TIMEOUT: bridge did not come up in 30s
    goto :no_bridge
)
"%ENGINE_DIR%\.venv\Scripts\python.exe" -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('127.0.0.1',7861)); s.close(); exit(0 if r==0 else 1)" 2>nul
if errorlevel 1 (
    timeout /t 1 >nul
    goto :wait_bridge
)
echo   bridge UP
:no_bridge

rem --- 3. Tunnel ---------------------------------------------------
echo [4/4] starting cloudflared tunnel "%TUNNEL_NAME%"...
if not exist "%CLOUDFLARED%" (
    echo   WARNING: cloudflared not found at %CLOUDFLARED%
    echo   install with:  winget install --id Cloudflare.cloudflared
    goto :no_tunnel
)

rem Start tunnel via start_tunnel.py --detach (proven reliable).
rem If a named-tunnel config exists, it uses that; otherwise it falls
rem back to a quick tunnel and writes the URL to %TEMP%\cf_tunnel_url.txt.
"%ENGINE_DIR%\.venv\Scripts\python.exe" "%BRIDGE_DIR%\start_tunnel.py" --detach --port 7861
:no_tunnel

echo.
echo  Orchestrator done.
timeout /t 5 >nul
