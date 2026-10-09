"""Launch the Kokoro engine (kokoro-tts/app.py) detached.

Reads engine dir from TTS_ENGINE_DIR env. Uses cmd shell so the
NUL stdin redirection and file-output redirection work correctly
on Windows. Returns once the engine is bound to port 7860.

This is the launcher used by start-all.bat (step 1) and was the
fix that made the engine reliably start in ~3s instead of hanging
forever on a stdin EOF race in detached subprocess.Popen.
"""
import os
import socket
import subprocess
import sys
import time

engine_dir = os.environ.get('TTS_ENGINE_DIR')
if not engine_dir:
    sys.stderr.write('TTS_ENGINE_DIR must be set\n')
    sys.exit(2)

venv_py = os.path.join(engine_dir, '.venv', 'Scripts', 'python.exe')
app_py = os.path.join(engine_dir, 'app.py')
out_log = os.path.join(engine_dir, 'server.out.log')
err_log = os.path.join(engine_dir, 'server.err.log')

# Build a cmd.exe command. The < NUL redirect closes stdin so nltk (or
# anything else) can't hang waiting for input. >> appends to the log.
# TTS_OUTPUT_DIR (if set) is propagated to the engine so writes land in
# the user-configured location (e.g. a cloud-synced folder).
out_dir = os.environ.get('TTS_OUTPUT_DIR', '').strip()
out_dir_clause = f'set "TTS_OUTPUT_DIR={out_dir}"&& ' if out_dir else ''
cmd = (
    f'set NLTK_ALLOW_PROXIED_URLOPEN=1&& '
    f'{out_dir_clause}'
    f'"{venv_py}" "{app_py}" --no-auto-stop '
    f'< NUL >> "{out_log}" 2>> "{err_log}"'
)

# CREATE_NEW_PROCESS_GROUP so the engine survives cmd.exe exit.
flags = subprocess.CREATE_NEW_PROCESS_GROUP

p = subprocess.Popen(
    cmd, cwd=engine_dir,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=flags, close_fds=True,
    shell=True,
)
print(f'engine launched: pid {p.pid}')

# Wait for port 7860
for i in range(90):
    time.sleep(1)
    s = socket.socket()
    s.settimeout(1)
    r = s.connect_ex(('127.0.0.1', 7860))
    s.close()
    if r == 0:
        print(f'engine UP after {i+1}s')
        sys.exit(0)
print('TIMEOUT waiting for engine')
sys.exit(1)
