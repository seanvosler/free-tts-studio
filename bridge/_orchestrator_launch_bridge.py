"""Internal launcher used by start-all.bat / orchestrator.

Reads config from env, starts the bridge detached with proper Windows
flags. Writes the bridge log files. Keeps cmd.exe out of the quoting
business.
"""
import os
import subprocess
import sys


def main():
    bridge_dir = os.environ.get('TTS_BRIDGE_DIR')
    engine_dir = os.environ.get('TTS_ENGINE_DIR')
    if not bridge_dir or not engine_dir:
        sys.stderr.write('TTS_BRIDGE_DIR and TTS_ENGINE_DIR must be set.\n')
        sys.exit(2)

    py = os.path.join(engine_dir, '.venv', 'Scripts', 'python.exe')
    bridge_script = os.path.join(bridge_dir, 'bridge.py')
    key_file = os.path.join(bridge_dir, 'bridge.key')

    if not os.path.exists(py):
        sys.stderr.write(f'engine venv python missing: {py}\n')
        sys.exit(2)
    if not os.path.exists(bridge_script):
        sys.stderr.write(f'bridge.py missing: {bridge_script}\n')
        sys.exit(2)

    if os.path.exists(key_file):
        api_key = open(key_file, 'r').read().strip()
    else:
        import secrets
        api_key = secrets.token_urlsafe(32)
        with open(key_file, 'w') as f:
            f.write(api_key)
        sys.stderr.write(f'generated new API key -> {key_file}\n')

    env = os.environ.copy()
    env['TTS_BRIDGE_API_KEY'] = api_key
    env.setdefault('TTS_BRIDGE_HOST', '0.0.0.0')
    env.setdefault('TTS_BRIDGE_PORT', '7861')
    env.setdefault('TTS_ENGINE_URL', 'http://127.0.0.1:7860')

    out_log = open(os.path.join(bridge_dir, 'bridge.out.log'), 'ab')
    err_log = open(os.path.join(bridge_dir, 'bridge.err.log'), 'ab')

    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | BREAKAWAY_FROM_JOB.
    # BREAKAWAY_FROM_JOB prevents cmd.exe's job object from killing the
    # bridge when the orchestrator batch script ends.
    flags = 0x00000008 | 0x00000200 | 0x01000000
    p = subprocess.Popen(
        [py, bridge_script],
        cwd=bridge_dir, env=env,
        stdout=out_log, stderr=err_log,
        creationflags=flags, close_fds=True,
    )
    print(f'bridge launched: pid {p.pid}')


if __name__ == '__main__':
    main()
