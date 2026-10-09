"""Launch a cloudflared tunnel pointing at the local bridge.

Auto-detects mode:
  - Named tunnel: if ~/.cloudflared/config.yml or any *-credentials.json
    exists, runs `cloudflared tunnel run <name>` for the named tunnel
    (stable URL via DNS route configured in Cloudflare).
  - Quick tunnel: otherwise runs `cloudflared tunnel --url ...`
    and writes the trycloudflare.com URL to TEMP/cf_tunnel_url.txt.

Usage:
    python start_tunnel.py [--port 7861] [--detach]

Environment:
    TTS_BRIDGE_PORT    Port the bridge is listening on (default 7861).
    TTS_TUNNEL_NAME    Named tunnel to use (default 'tts-bridge').
    CLOUDFLARED_PATH   Path to cloudflared.exe.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

CLOUDFLARED = os.environ.get(
    'CLOUDFLARED_PATH',
    r'C:\Users\me\AppData\Local\Microsoft\WindowsApps\cloudflared.exe',
)
URL_FILE = os.path.join(os.environ.get('TEMP', '.'), 'cf_tunnel_url.txt')
TUNNEL_NAME = os.environ.get('TTS_TUNNEL_NAME', 'tts-bridge')


def find_named_tunnel(cf_home):
    """Return (name, credentials_file) if a named tunnel can be run, else None.

    Looks for ~/.cloudflared/config.yml first (preferred), then falls back
    to any *-credentials.json file.
    """
    config_path = os.path.join(cf_home, 'config.yml')
    if os.path.exists(config_path):
        # Try to read the tunnel name from the config
        name = TUNNEL_NAME
        try:
            with open(config_path, 'r') as f:
                for line in f:
                    m = re.match(r'^\s*tunnel:\s*(\S+)', line)
                    if m:
                        name = m.group(1).strip()
                        break
        except OSError:
            pass
        # Look for any credentials file with TunnelID
        for fname in os.listdir(cf_home):
            if fname.endswith('.json') and fname != 'cert.pem':
                full = os.path.join(cf_home, fname)
                try:
                    with open(full, 'r') as f:
                        d = json.load(f)
                    if d.get('TunnelID'):
                        return (name, full)
                except Exception:
                    pass

    # No config.yml -- look for any credentials file
    if os.path.isdir(cf_home):
        for fname in os.listdir(cf_home):
            if fname.endswith('.json') and fname != 'cert.pem':
                try:
                    with open(os.path.join(cf_home, fname), 'r') as f:
                        d = json.load(f)
                    if d.get('TunnelID'):
                        return (TUNNEL_NAME, os.path.join(cf_home, fname))
                except Exception:
                    pass
    return None


def main():
    ap = argparse.ArgumentParser(description='Start cloudflared tunnel pointing at local bridge')
    ap.add_argument('--port', type=int,
                    default=int(os.environ.get('TTS_BRIDGE_PORT', '7861')),
                    help='local bridge port (default 7861)')
    ap.add_argument('--detach', action='store_true',
                    help='launch detached and exit (for quick tunnels, writes URL to '
                         'TEMP/cf_tunnel_url.txt; for named tunnels, just exits once '
                         'cloudflared is up)')
    args = ap.parse_args()

    if not os.path.exists(CLOUDFLARED):
        sys.stderr.write(f'cloudflared not found at {CLOUDFLARED}\n')
        sys.stderr.write('install with: winget install --id Cloudflare.cloudflared\n')
        sys.exit(2)

    cf_home = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')),
                           '.cloudflared')
    os.makedirs(cf_home, exist_ok=True)

    # Detect mode
    named = find_named_tunnel(cf_home)

    if named:
        name, cred_file = named
        sys.stderr.write(f'using named tunnel: {name} (credentials: {cred_file})\n')
        # --output is a global option; must come before the subcommand.
        cmd = [CLOUDFLARED, '--output', 'json', 'tunnel', 'run', name]
        mode = 'named'
    else:
        # Quick tunnel -- needs cert.pem from `cloudflared tunnel login`
        cert_path = os.path.join(cf_home, 'cert.pem')
        if not os.path.exists(cert_path):
            sys.stderr.write('')
            sys.stderr.write('!! cert.pem missing !!\n')
            sys.stderr.write(f'   cloudflared needs {cert_path} to authenticate.\n')
            sys.stderr.write('   Run this ONCE in a terminal:\n')
            sys.stderr.write('       cloudflared tunnel login\n')
            sys.stderr.write('   (a browser will open; pick your domain, then re-run this script)\n')
            sys.stderr.write('')
            sys.exit(3)
        sys.stderr.write(f'using quick tunnel (URL will change between sessions)\n')
        cmd = [CLOUDFLARED, '--output', 'json',
               'tunnel', '--url', f'http://localhost:{args.port}', '--no-autoupdate']
        mode = 'quick'

    sys.stderr.write(f'starting cloudflared: {" ".join(cmd)}\n')

    if args.detach:
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | BREAKAWAY_FROM_JOB.
        flags = 0x00000008 | 0x00000200 | 0x01000000
        out_log = open(os.path.join(os.environ.get('TEMP', '.'), 'cf_tunnel_stdout.log'), 'ab')
        err_log = open(os.path.join(os.environ.get('TEMP', '.'), 'cf_tunnel_stderr.log'), 'ab')
        proc = subprocess.Popen(
            cmd,
            cwd=os.path.dirname(CLOUDFLARED),
            stdin=subprocess.DEVNULL,
            stdout=out_log, stderr=err_log,
            creationflags=flags, close_fds=True,
        )
        print(f'cloudflared launched: pid {proc.pid} ({mode} tunnel)')

        if mode == 'named':
            # For named tunnels there's no URL to capture -- the user
            # configured DNS routes via `cloudflared tunnel route dns`.
            time.sleep(5)
            return

        # Quick tunnel: poll for the trycloudflare URL.
        err_path = os.path.join(os.environ.get('TEMP', '.'), 'cf_tunnel_stderr.log')
        url = None
        start = time.time()
        while time.time() - start < 30:
            time.sleep(1)
            if os.path.exists(err_path):
                try:
                    with open(err_path, 'r', errors='ignore') as f:
                        content = f.read()
                    m = re.search(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com', content)
                    if m:
                        url = m.group(0)
                        break
                except OSError:
                    pass
        if url:
            with open(URL_FILE, 'w') as f:
                f.write(url)
            print(url)
            print(f'URL written to {URL_FILE}', file=sys.stderr)
        else:
            print('NOT_FOUND', file=sys.stderr)
            sys.exit(1)
        return

    # Foreground mode: stream cloudflared output to our stdout.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
    except KeyboardInterrupt:
        proc.terminate()


if __name__ == '__main__':
    main()
