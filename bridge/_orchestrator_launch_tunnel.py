"""Internal launcher used by start-all.bat to start cloudflared tunnel.

Reads TTS_CLOUDFLARED and TTS_TUNNEL_NAME from env, launches the tunnel
detached with proper Windows flags. Writes cloudflared output to
tunnel.out.log / tunnel.err.log in the bridge directory. For quick
tunnels, extracts the trycloudflare.com URL from cloudflared's stderr
and writes it to %TEMP%\\cf_tunnel_url.txt.

Tries the named tunnel first; falls back to quick tunnel if config is
missing. The named tunnel config lives at
%USERPROFILE%\\.cloudflared\\config.yml; the named-tunnel credentials
JSON at %USERPROFILE%\\.cloudflared\\<tunnel-name>.json.
"""
import os
import re
import subprocess
import sys
import threading
import time


def main():
    cf = os.environ.get('TTS_CLOUDFLARED')
    bridge_dir = os.environ.get('TTS_BRIDGE_DIR')
    tunnel_name = os.environ.get('TTS_TUNNEL_NAME', 'tts-bridge')

    if not cf or not bridge_dir:
        sys.stderr.write('TTS_CLOUDFLARED and TTS_BRIDGE_DIR must be set.\n')
        sys.exit(2)
    if not os.path.exists(cf):
        sys.stderr.write(f'cloudflared missing: {cf}\n')
        sys.exit(2)

    # cloudflared errors immediately if ~/.cloudflared doesn't exist,
    # even in --url quick-tunnel mode. Make sure it exists.
    user_home = os.environ.get('USERPROFILE', os.path.expanduser('~'))
    os.makedirs(os.path.join(user_home, '.cloudflared'), exist_ok=True)
    cred_file = os.path.join(user_home, '.cloudflared', f'{tunnel_name}.json')
    url_file = os.path.join(os.environ.get('TEMP', '.'), 'cf_tunnel_url.txt')

    is_quick = not os.path.exists(cred_file)
    if is_quick:
        # Quick tunnel fallback
        sys.stderr.write(
            f'named tunnel config not found at {cred_file}\n'
            f'falling back to quick tunnel (URL will change between sessions)\n'
        )
        # --output is a global option; must come before the subcommand.
        cmd = [cf, '--output', 'json',
               'tunnel', '--url', 'http://localhost:7861', '--no-autoupdate']
    else:
        sys.stderr.write(f'using named tunnel: {tunnel_name}\n')
        cmd = [cf, '--output', 'json', 'tunnel', 'run', tunnel_name]

    out_log = open(os.path.join(bridge_dir, 'tunnel.out.log'), 'ab')
    err_log = open(os.path.join(bridge_dir, 'tunnel.err.log'), 'ab')

    if is_quick:
        # Quick tunnels print the URL to stderr. We need to capture it,
        # so don't redirect stderr to a file -- read it in a thread.
        # BREAKAWAY_FROM_JOB lets cloudflared survive after the orchestrator
        # batch script ends and Windows closes the cmd.exe job object.
        p = subprocess.Popen(
            cmd, cwd=os.path.dirname(cf),
            stdin=subprocess.DEVNULL,
            stdout=out_log, stderr=subprocess.PIPE,
            creationflags=0x00000008 | 0x00000200 | 0x01000000,
            close_fds=True, text=True, bufsize=1,
        )

        def capture_url():
            for line in p.stderr:
                m = re.search(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com', line)
                if m:
                    with open(url_file, 'w') as f:
                        f.write(m.group(0))
                    sys.stderr.write(f'tunnel URL: {m.group(0)}\n')
                    sys.stderr.write(f'wrote to {url_file}\n')
                    return
                # mirror to err_log too
                err_log.write(line)

        threading.Thread(target=capture_url, daemon=True).start()
        print(f'cloudflared launched: pid {p.pid} (quick tunnel)')
    else:
        # Named tunnel -- no URL to capture, just stream stderr to log.
        p = subprocess.Popen(
            cmd, cwd=os.path.dirname(cf),
            stdin=subprocess.DEVNULL,
            stdout=out_log, stderr=err_log,
            creationflags=0x00000008 | 0x00000200,
            close_fds=True,
        )
        print(f'cloudflared launched: pid {p.pid} (named tunnel)')


if __name__ == '__main__':
    main()
