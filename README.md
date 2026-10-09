# Free TTS Studio — Bridge

A small, **stdlib-only** HTTP sidecar that turns the local
[Kokoro-82M narration studio](https://github.com/seanvosler/free-tts-studio)
into a programmable API. The engine itself (`app.py`) is left **untouched**
and stays bound to loopback. The bridge owns authentication, the public
contract, the dashboard, and the path from "remote caller" to "WAV on disk".

```
                   +-------------------+        +-------------------+
  remote caller -->|  bridge.py :7861  |------->|  app.py :7860     |
  (curl, app, ...) +-------------------+  HTTP  +-------------------+
        |                                                      |
        | Bearer auth                                           v
        |                                              output/*.wav
        v
  JSON responses  +  /dashboard HTML
```

## Features

- **Async + sync TTS API** — `POST /v1/synthesize` with `?wait=true` for blocking calls
- **28 Kokoro voices** across US and UK accents
- **KittenTTS-2 engine** — 47 voices, multilingual (German, French, Spanish, Chinese, Hindi, Italian, Portuguese, Russian, Arabic), expression markup (`[joyful]`, `<laugh>`, `(((emphasis)))`), and 5-30s voice cloning
- **Dashboard** at `/dashboard` — engine status, uptime, job counts, recent clips
- **Job tracking** — every state transition in an append-only JSONL audit log
- **Bearer-token auth** — `hmac.compare_digest`, ≥24-char tokens enforced
- **Per-IP rate limit** (60/min default) + 1 MiB body cap + 300s sync timeout (1200s for Kitten voice clones)
- **Optional Cloudflare tunnel** — `voice.yourdomain.com` over HTTPS in minutes

## Quick start

```bat
:: 1. Engine (the public Kokoro TTS Studio; unchanged)
cd ..\free-tts-studio
.\run.bat

:: 2. Bridge (separate process; same machine, different port)
cd ..\free-tts-studio-bridge
.\run-bridge.bat
```

The launcher auto-generates a fresh `TTS_BRIDGE_API_KEY` and writes it to
`bridge.key` (gitignored). The console prints a masked key on first run;
the full key is in `bridge.key`.

Once both are up: `http://localhost:7861/dashboard`.

## API

All endpoints except `/healthz` and `/dashboard` require
`Authorization: Bearer <key>`. JSON in, JSON out.

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/healthz` | Engine liveness (no auth) |
| `GET`  | `/dashboard` | Auto-refreshing HTML (no auth) |
| `GET`  | `/api/dashboard-data` | Dashboard JSON |
| `POST` | `/v1/synthesize` | Submit a job (202 + job_id; or 200 with `?wait=true`) |
| `GET`  | `/v1/jobs/<id>` | Poll a job |
| `GET`  | `/v1/jobs?limit=N` | Recent jobs (default 100, max 500) |
| `DELETE` | `/v1/jobs/<id>` | Best-effort cancel |
| `GET`  | `/v1/voices` | List available voices |
| `GET`  | `/v1/files` | List WAVs in engine's `output/` |
| `GET`  | `/v1/files/<name>` | Stream a WAV |

### Synthesize (async)

```bash
curl -sS -X POST http://127.0.0.1:7861/v1/synthesize \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"hello world","voice":"af_heart","speed":1.0}'
# HTTP/1.1 202 Accepted
# { "job_id": "5f1c…", "status": "queued" }
```

### Synthesize (sync, blocks until done)

```bash
curl -sS -X POST "http://127.0.0.1:7861/v1/synthesize?wait=true" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"hello world","voice":"af_heart"}'
# { "job_id": "5f1c…", "status": "done",
#   "file": "/output/20260915_141022_af_heart.wav",
#   "duration": 3.21,
#   "url": "http://127.0.0.1:7860/output/20260915_141022_af_heart.wav" }
```

On `?wait=true` timeout the bridge returns **504** with the job id and a
`poll_url` so the caller can keep polling:

```json
{ "job_id": "5f1c…", "status": "timeout",
  "message": "still processing or failed",
  "poll_url": "/v1/jobs/5f1c…" }
```

### Dashboard

Open `http://localhost:7861/dashboard` in a browser (no auth). It polls
`/api/dashboard-data` every 5s and shows engine status, uptime, total jobs
in flight, completed audio duration, recent jobs table, and recent output files.

### Status codes

| Code | Meaning |
|---|---|
| 200 | OK |
| 202 | Job enqueued (async) |
| 400 | Bad payload (empty text, bad speed, unknown voice) |
| 401 | Missing or wrong bearer token |
| 404 | Unknown job id, unknown route, missing file |
| 429 | Per-IP rate limit; `Retry-After` header tells you when to retry |
| 500 | Synthesis failed (engine returned an error) |
| 502 | Engine is unreachable (`engine_down`) |
| 504 | `?wait=true` timed out; job may still complete |

## Configuration

All knobs are environment variables. See `.env.example` for the full list.
The launcher sets sane defaults; you only need to touch them if you want
LAN exposure or a different port.

| Var | Default | Purpose |
|---|---|---|
| `TTS_BRIDGE_API_KEY` | (required, auto-gen) | Bearer token for every request |
| `TTS_BRIDGE_HOST` | `127.0.0.1` | Bind address; `0.0.0.0` for LAN |
| `TTS_BRIDGE_PORT` | `7861` | Bridge listen port |
| `TTS_ENGINE_URL` | `http://127.0.0.1:7860` | Engine base URL |
| `TTS_BRIDGE_WORKERS` | `2` | Concurrent synth jobs in flight |
| `TTS_BRIDGE_RATE_PER_MIN` | `60` | Per-IP rate limit |
| `TTS_BRIDGE_WAIT_TIMEOUT` | `300` | Max `?wait=true` block, in seconds |
| `TTS_BRIDGE_AUDIT_LOG` | `bridge-audit.log` | JSONL audit log path |
| `TTS_BRIDGE_TRUST_XFF` | `0` | `1` to honor `X-Forwarded-For` |
| `TTS_TUNNEL_NAME` | `tts-bridge` | Named tunnel name (cloudflared) |
| `CLOUDFLARED_PATH` | auto-detected | Path to cloudflared.exe |

## Auto-start on boot

```
powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1 install
```

This registers a Task Scheduler entry that runs `start-all.bat` at logon.
`start-all.bat` is a single orchestrator that brings up engine → bridge
→ cloudflared tunnel in order, with health checks between each step.

```
powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1 remove
powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1 status
powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1 run-now
```

## Exposing to the public web (HTTPS)

The bridge is plain HTTP. For external access, terminate TLS in front of
it (do **not** bind the bridge to `0.0.0.0` without TLS).

### cloudflared (quickest, stable URL via named tunnel)

Install once:
```
winget install --id Cloudflare.cloudflared
```

Then:
```
cloudflared tunnel login
cloudflared tunnel create tts-bridge
```

`run-bridge.bat` auto-detects the named-tunnel credentials and uses them
when present; otherwise it falls back to a `*.trycloudflare.com` quick tunnel.

For a custom domain, add the DNS route:
```
cloudflared tunnel route dns tts-bridge voice.yourdomain.com
```

`voice.yourdomain.com` will route to your local bridge over HTTPS via
Cloudflare's edge. Detailed walkthrough in `TUNNEL-SETUP.md`.

### Caddy (when you want your own reverse proxy)

```
voice.yourdomain.com {
  reverse_proxy 127.0.0.1:7861
}
```

For higher-security setups, put the bridge behind Cloudflare Access or
Tailscale Funnel and keep `TTS_BRIDGE_HOST=127.0.0.1`.

## Security

- The **bridge** is the only thing reachable from outside the box.
  The engine stays loopback-only — that's intentional.
- Bearer tokens are compared with `hmac.compare_digest` (constant time).
- Tokens shorter than 24 characters are refused at startup.
- A 1 MiB request body cap prevents accidental DoS.
- Per-IP rate limiting (default 60/min) prevents naïve scraping.
- The audit log records `{job_id, status, voice, ip}` per state transition;
  it never contains the API key, the text payload, or the file contents.
- See `SECURITY.md` (in the engine repo) for the disclosure policy.

## Operations

- **Liveness:** `GET /healthz` (no auth) tells you whether the engine is up.
- **History:** `GET /v1/jobs?limit=200` shows the last 200 jobs.
- **Dashboard:** `GET /dashboard` (no auth).
- **Audit:** `bridge-audit.log` is append-only JSONL; rotate externally.
- **Cancel a runaway job:** `DELETE /v1/jobs/<id>` marks it failed
  on the bridge side. The engine will still finish whatever it was
  synthesizing; you can `taskkill /F /IM python.exe` to hard-stop.

### About auto-stop

The engine has a watchdog: if no browser tab has sent a heartbeat in 90s,
it shuts itself down. The bridge prevents this by registering its own
session with the engine **before** it starts serving traffic, then
heartbeating every 20s for the first two minutes and every 30s
thereafter.

**Practical consequence:** if you start the engine, wait more than
~60 seconds, and then start the bridge, the engine may have already
auto-stopped. Start the bridge promptly after the engine, or launch
the engine with `--no-auto-stop` (the orchestrator does this for you).

## Layout

```
free-tts-studio-bridge/
├── bridge.py                            # the sidecar (stdlib HTTP)
├── auth.py                              # bearer-token check
├── jobs.py                              # in-memory JobStore + JSONL audit
├── dashboard.py                         # /dashboard HTML + data builder
├── start_tunnel.py                      # cloudflared launcher (auto-detect mode)
├── start-all.bat                        # engine + bridge + tunnel orchestrator
├── install-autostart.ps1                # Task Scheduler entry installer
├── _orchestrator_launch_engine_v2.py    # cmd-shell engine launcher
├── _orchestrator_launch_bridge.py       # bridge launcher
├── _orchestrator_launch_tunnel.py       # tunnel launcher
├── tunnel-config.yml                    # template for named tunnel
├── setup-tunnel.ps1                     # interactive named-tunnel helper
├── TUNNEL-SETUP.md                      # named-tunnel walkthrough
├── run-bridge.bat / run-bridge.ps1      # bridge-only launchers
├── run-tunnel.bat / run-tunnel.ps1      # tunnel-only launchers
├── tunnel.bat / tunnel.ps1              # manual cloudflared launchers
├── .env.example                         # all config knobs
├── .gitignore
└── README.md
```

## License

MIT. See `../free-tts-studio/LICENSE` for the parent project's license.
