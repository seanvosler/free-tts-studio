# Free TTS Bridge — API Reference

> **Unofficial cheat sheet.** Not in git (gitignored). For the canonical docs
> see the bridge `README.md`. Keep this next to your other working notes.

## Base URLs

| Context | URL |
|---|---|
| Localhost (this machine) | `http://127.0.0.1:7861` |
| LAN (when bridge is bound to `0.0.0.0`) | `http://10.117.3.48:7861` |
| Stable public URL | `https://voice.sean.co` |

Engine listens separately on `127.0.0.1:7860` (loopback only, not reachable from outside).

## Auth

All endpoints except `/healthz` and `/dashboard` require:

```
Authorization: Bearer <TTS_BRIDGE_API_KEY>
```

The key lives in `bridge/bridge.key` (43 chars, gitignored). On the bridge side it's compared with `hmac.compare_digest` (constant-time), and tokens <24 chars are refused at startup.

## Quick example

```bash
KEY=$(cat /c/Users/me/OneDrive/Documents/My\ ARK\ Mods/generalProjects/free-tts-studio-bridge/bridge.key)

# Synthesize (sync — waits for completion, max 300s)
curl -sS -X POST "https://voice.sean.co/v1/synthesize?wait=true" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello from the bridge.","voice":"af_heart","speed":1.0}'
```

## Endpoints

### `GET /healthz` — no auth

Quick liveness probe (used by cloudflared, monitoring, scripts).

```bash
curl https://voice.sean.co/healthz
# {"ok": true, "engine": "up"}
```

### `GET /dashboard` — no auth

Auto-refreshing HTML page. Open in a browser.

```
https://voice.sean.co/dashboard
```

Shows: engine dot, bridge uptime, total jobs, in-flight count, done/failed, total audio duration, recent 20 jobs, recent 20 files.

### `POST /v1/synthesize` — auth

Submit a TTS job. Default is async (returns 202 + job_id). Add `?wait=true` to block until done.

**Body:**
```json
{
  "text": "Your narration text here.",
  "voice": "af_heart",
  "speed": 1.0,
  "output_file_name": "my-clip"
}
```

| Field | Required | Default | Notes |
|---|---|---|---|
| `text` | yes | — | Empty / whitespace-only returns 400 |
| `voice` | no | first voice from `/api/voices` | Must be one of the 28 voice IDs (see below) |
| `speed` | no | `1.0` | Clamped to `[0.5, 2.0]` |
| `output_file_name` | no | auto: `YYYYMMDD_HHMMSS_<voice>.wav` | See "Output filename" below |
| `clean_markdown` | no | `false` | See "Markdown cleaning" below |
| `tts_normalize` | no | `false` | See "TTS normalization" below |

**Async response (default, 202):**
```json
{ "job_id": "5f1c8a3b9e4d2", "status": "queued" }
```

**Sync response (`?wait=true`, 200):**
```json
{
  "job_id": "5f1c8a3b9e4d2",
  "status": "done",
  "file": "/output/20260916_141022_af_heart.wav",
  "duration": 3.21,
  "url": "http://127.0.0.1:7860/output/20260916_141022_af_heart.wav"
}
```

#### Output filename

Optional `output_file_name` lets you control the on-disk filename. Rules:

- Only the **basename** is accepted — no path separators (`/`, `\`), no `..`, no NUL bytes.
- Any extension you include is **stripped** — the engine always writes `.wav` (Kokoro outputs PCM WAV). `"hello.mp3"` becomes `hello.wav`. Use a post-step to transcode if you really need MP3.
- Allowed characters: `[A-Za-z0-9._- ]`. Anything else is replaced with `_`.
- Max 80 chars for the basename (120 for the whole string).
- If a file with the resulting name already exists, the engine appends `_2`, `_3`, ... so nothing is silently overwritten.

```bash
# Custom name -- lands at G:\My Drive\voicesseancoTTSfiles\my-clip.wav
curl -sS -X POST "https://voice.sean.co/v1/synthesize?wait=true" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Custom name.","voice":"af_heart","output_file_name":"my-clip"}'
```

The destination directory is controlled by the engine's `TTS_OUTPUT_DIR` env var (default: `<engine-repo>/output`). The launchers set it to `G:\My Drive\voicesseancoTTSfiles` so files auto-sync to Google Drive.

#### Markdown cleaning

Set `"clean_markdown": true` to run the text through a stdlib regex-based
markdown normalizer before it hits the engine. The cleaner:

- drops code fences (` ``` ... ``` `) and front-matter (`--- ... ---`) entirely
- drops images, keeps link labels (drops the URL)
- strips header (`#`), list (`-`, `*`, `1.`), blockquote (`>`), and HR (`---`) markers
- drops inline-code backticks but keeps the inner text
- drops bold / italic markers but keeps the inner text
- strips HTML tags, decodes common HTML entities, decodes markdown escapes (`\*` → `*`)
- preserves paragraph breaks (blank lines); collapses single newlines within a paragraph to spaces

```bash
curl -sS -X POST "https://voice.sean.co/v1/synthesize?wait=true" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "# Hello\n\nThis is **bold** and *italic*.\n\n- one\n- two",
    "voice": "af_heart",
    "clean_markdown": true
  }'
```

**Verified**: 487 chars of real README-style markdown → 342 chars of clean prose, ~32% shorter audio. Default is `false`, so existing callers see no behavior change.

#### Phonetic hints (Kokoro's `[word](/ipa/)` syntax)

The cleaner **preserves** Kokoro's official pronunciation-override syntax even when `clean_markdown: true`. The model card uses this:

```bash
# "Kokoro" will be pronounced like "koh-KOH-roh", not "kuh-KOR-oh"
curl -sS -X POST "https://voice.sean.co/v1/synthesize?wait=true" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{
    "text": "[Kokoro](/kˈOkəɹO/) is an open-weight TTS model.",
    "voice": "af_heart",
    "clean_markdown": true
  }'
```

The `(...)` part can be **IPA** (with combining marks) or **ARPAbet** ASCII:

| You write | What Kokoro says |
|---|---|
| `[Kokoro](/kˈOkəɹO/)` | "koh-KOH-roh" |
| `[SQL](/ˌɛskjuːˈɛl/)` | "ess-cue-ell" |
| `[Nguyen](/wɪn/)` | "win" |
| `[coup](/ku/)` | "koo" |

#### TTS normalization

Set `"tts_normalize": true` to apply two extra passes after markdown cleaning:

1. **Acronym capitalization** — known acronyms (`api`, `gpu`, `cpu`, `html`, `css`, `json`, `http`, `url`, `tls`, `ui`, `ux`, `sql`, `aws`, `pdf`, ...) are uppercased so Kokoro reads them letter-by-letter rather than guessing. ~60 acronyms in the list.
2. **Long-sentence pauses** — sentences ≥ 30 words get an extra `", , "` injected after the first comma, giving Kokoro room for natural prosody. Short sentences are untouched.

```bash
curl -sS -X POST "https://voice.sean.co/v1/synthesize?wait=true" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{
    "text": "The api and the gpu are both fast.",
    "voice": "af_heart",
    "tts_normalize": true
  }'
# Engine receives: "The API and the GPU are both fast."
```

`tts_normalize` runs **after** `clean_markdown` if both are enabled. Default is `false`. The two fields compose cleanly — markdown first (drop code blocks, preserve `[word](/ipa/)`), then normalize.

#### Best practices

A few formatting patterns that consistently improve output quality with Kokoro:

| Pattern | What it does |
|---|---|
| `[word](/phonetic/)` | Override the pronunciation of one word. The single highest-impact technique. |
| Short sentences (<25 words) | Better prosody. Long sentences sound rushed. |
| Strategic commas | Each comma is a short pause. Use them as breathing room. |
| `…` ellipsis | Dramatic pause, useful for suspenseful reads. |
| Em-dash `—` | Mid-sentence break. |
| Uppercase acronyms | `GPU` → "G P U"; `gpu` → "gpu" (one syllable). Combine with `tts_normalize` to do this automatically. |
| Spell out numbers | `2026` → "twenty twenty-six" (works by default). |
| Quote consistently | Use straight `"..."` rather than curly `"..."`. |

## KittenTTS-2 engine (multilingual, voice cloning, expression)

A second engine is wired into the same bridge on a separate port. The Kokoro
endpoints (`/v1/...`) are unchanged; Kitten lives under `/v1/kitten/...`. Both
engines write to the same `TTS_OUTPUT_DIR` (the Google Drive folder).

| Method | Path | Notes |
|---|---|---|
| `GET`  | `/v1/kitten/voices` | 47 voices; first 38 named (Bella, Bruno, Kiki, …), last 9 are language-accent voices (Arabic, Chinese, French, German, Hindi, Italian, Portuguese, Russian, Spanish). |
| `POST` | `/v1/kitten/synthesize?wait=true` | Block until the WAV is ready. Same body shape as `/v1/synthesize` plus Kitten-specific fields. |
| `POST` | `/v1/kitten/synthesize` | Async (returns 202 + job_id). Auto-forced when `reference_audio` is set. |
| `GET`  | `/v1/kitten/jobs/<id>` | Poll status of an async job. |
| `GET`  | `/v1/kitten/files` | List WAVs in the engine's output dir. |
| `GET`  | `/v1/kitten/files/<name>` | Stream a WAV. |

### Body fields (Kokoro → Bridge fields that also pass through to Kitten)

| Field | Type | Notes |
|---|---|---|
| `text` | string | required |
| `voice` | string | 47 built-in voices; defaults to `Bella` |
| `speed` | number | `[0.5, 2.0]`. **Applied as a post-process resample** — Kitten's `generate()` doesn't take speed natively. |
| `output_file_name` | string | optional basename; `_2`, `_3` suffix on collision |
| `clean_markdown` | bool | run the markdown cleaner first (Kokoro-compatible) |
| `tts_normalize` | bool | acronym cap + long-sentence pauses |
| `emotion` | string | **Kitten only**: `angry`/`contemplative`/`excited`/`joyful`/`mundane`/`nervous`/`sad`/`stern`/`surprised`/`tender`. Leading tag only. |
| `reference_audio` | string | **Kitten only**: path to a 5-30s reference WAV for voice cloning. Forces async (8+ min inference). |
| `normalize` | bool | **Kitten only**: defaults to `true`; pass `false` for non-English text. |
| `key_file_path` | string | override for `bridge.key` location |
| `drive_dir` | string | override for the Google Drive output dir |

### Sync response

```json
{
  "ok": true, "status": "done", "engine": "kitten", "job_id": null,
  "filename": "german_morning.wav", "duration": 3.8,
  "url": "http://127.0.0.1:7862/output/german_morning.wav"
}
```

### Async / voice-clone response (always for `reference_audio`)

```json
{
  "ok": true, "engine": "kitten", "status": "queued",
  "job_id": "5f1c8a3b9e4d2", "output_file_name": "my_voice_clip",
  "poll_url": "https://voice.sean.co/v1/kitten/jobs/5f1c8a3b9e4d2"
}
```

### Expression markup (Kitten only)

Inline markup, sent as part of `text`:

- **Leading emotion tag**: `[joyful] We won the grant.` — sets the emotion for the whole line.
- **Vocal events**: `<laugh>`, `<gasp>`, `<sigh>`, `<sob>`, `<giggle>`, `<growl>`, `<gulp>`, `<scoff>`, `<um>`, `<pause>`.
- **Emphasis**: `(((word)))` — stresses a word or short phrase.

### Multilingual example

```bash
curl -sS -X POST "https://voice.sean.co/v1/kitten/synthesize?wait=true" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{
    "text": "Guten Morgen. Heute ist ein schöner Tag.",
    "voice": "German",
    "normalize": false,
    "output_file_name": "german_demo"
  }'
```

### Voice-clone example (async, ~8 minutes)

```bash
curl -sS -X POST "https://voice.sean.co/v1/kitten/synthesize" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{
    "text": "This is my own voice, cloned from a short sample.",
    "voice": "Bella",
    "reference_audio": "C:/path/to/5s_sample.wav",
    "output_file_name": "my_voice_clip"
  }'
# Returns 202 with job_id; poll https://voice.sean.co/v1/kitten/jobs/<job_id>
```

### Performance notes

- Cold load of the 1.7B model takes ~14s on first request. Subsequent calls are warm.
- Built-in voices: ~3-23s per short clip on RTX 5070 (5-10x slower than Kokoro).
- Voice cloning: ~8 minutes for a 3.7s clip — the bridge auto-forces async and the wait timeout defaults to 1200s for Kitten (`TTS_BRIDGE_KITTEN_WAIT_TIMEOUT`).

### License note

KittenTTS-2 weights are released under the **Stellon Labs Community License** —
free for non-commercial use and commercial use under $1M annual revenue /
total funding. Past that threshold you'll need a separate commercial license
from Stellon Labs. The Kokoro-82M weights remain Apache 2.0; the bridge itself
is MIT-licensed.

**Sync timeout (`?wait=true`, 504):**
```json
{
  "job_id": "5f1c8a3b9e4d2",
  "status": "timeout",
  "message": "still processing or failed",
  "poll_url": "/v1/jobs/5f1c8a3b9e4d2"
}
```

### `GET /v1/jobs/<id>` — auth

Poll the current state of a job.

```bash
curl -sS -H "Authorization: Bearer $KEY" \
  https://voice.sean.co/v1/jobs/5f1c8a3b9e4d2
```

```json
{
  "job_id": "5f1c8a3b9e4d2",
  "status": "done",
  "voice": "af_heart",
  "speed": 1.0,
  "created_at": 1789578485.93,
  "started_at": 1789578485.95,
  "finished_at": 1789578488.88,
  "file": "/output/20260916_141022_af_heart.wav",
  "duration": 2.58
}
```

`status` is one of: `queued`, `running`, `done`, `failed`.

### `GET /v1/jobs?limit=N` — auth

List recent jobs (newest first; default 100, max 500).

### `DELETE /v1/jobs/<id>` — auth

Best-effort cancel. Already-running jobs can't be pulled off the engine, but the bridge marks them `failed` so a sync waiter unblocks.

### `GET /v1/voices` — auth

List available voices. Cached for 5 minutes.

```bash
curl -sS -H "Authorization: Bearer $KEY" https://voice.sean.co/v1/voices
```

Returns `{"voices": [{"label": "US - Heart (light)", "id": "af_heart"}, ...]}`. 28 voices total — see "Voice IDs" below.

### `GET /v1/files` — auth

List WAVs in the engine's `output/` directory (newest first).

### `GET /v1/files/<name>` — auth

Stream a WAV. Path-traversal protected (flat basenames only).

```bash
curl -sS -H "Authorization: Bearer $KEY" \
  -o out.wav \
  https://voice.sean.co/v1/files/20260916_141022_af_heart.wav
```

### `GET /api/dashboard-data` — auth

JSON for the dashboard widget.

```json
{
  "ok": true,
  "engine": "up",
  "bridge_uptime_s": 3126,
  "counts": { "total": 2, "queued": 0, "running": 0, "done": 2, "failed": 0 },
  "total_audio_s": 7.28,
  "jobs": [ ... up to 20 most recent ... ],
  "files": [ ... up to 20 most recent ... ],
  "fetched_at": 1789578485.93
}
```

## Status codes

| Code | Meaning | What to do |
|---|---|---|
| `200` | OK | proceed |
| `202` | Job enqueued (async mode) | poll `/v1/jobs/<id>` |
| `400` | Bad payload (empty text, bad speed, unknown voice) | fix the request |
| `401` | Missing or wrong bearer token | check `bridge.key` / auth header |
| `404` | Unknown job id, route, or file | check the id / path |
| `429` | Rate limit (60/min per IP) | back off; respect `Retry-After` |
| `500` | Synthesis failed (engine error) | check engine log; retry |
| `502` | Engine unreachable | check engine process / port 7860 |
| `504` | `?wait=true` timed out | poll `/v1/jobs/<id>` |

## Voice IDs

| Accent | Voices |
|---|---|
| US female (af_) | `af_heart`, `af_alloy`, `af_aoede`, `af_bella`, `af_jessica`, `af_kore`, `af_nicole`, `af_nova`, `af_river`, `af_sarah`, `af_sky` |
| US male (am_)   | `af_adam` → wait that's `am_adam`. Full list: `am_adam`, `am_echo`, `am_eric`, `am_fenrir`, `am_liam`, `am_michael`, `am_onyx`, `am_puck`, `am_santa` |
| UK female (bf_) | `bf_alice`, `bf_emma`, `bf_isabella`, `bf_lily` |
| UK male (bm_)   | `bm_daniel`, `bm_fable`, `bm_george`, `bm_lewis` |

Default voice (when omitted): `af_heart` (US - Heart, light).

## Common workflows

### One-shot, just give me the audio

```bash
KEY=$(cat /c/Users/me/OneDrive/Documents/My\ ARK\ Mods/generalProjects/free-tts-studio-bridge/bridge.key)

curl -sS -X POST "https://voice.sean.co/v1/synthesize?wait=true" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Read me out loud.","voice":"bm_fable","speed":1.1}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['file'])"
```

Returns something like `/output/20260916_163032_bm_fable.wav`. Then:

```bash
curl -sS -H "Authorization: Bearer $KEY" \
  -o clip.wav \
  "https://voice.sean.co/v1/files/20260916_163032_bm_fable.wav"
```

### Async (don't block the connection)

```bash
JOB=$(curl -sS -X POST "https://voice.sean.co/v1/synthesize" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Long narration..."}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

# poll later
curl -sS -H "Authorization: Bearer $KEY" \
  "https://voice.sean.co/v1/jobs/$JOB" | python -m json.tool
```

### Batch (submit N jobs, poll all)

```bash
KEY=$(cat /c/Users/me/OneDrive/Documents/My\ ARK\ Mods/generalProjects/free-tts-studio-bridge/bridge.key)

for text in "first line" "second line" "third line"; do
  curl -sS -X POST "https://voice.sean.co/v1/synthesize" \
    -H "Authorization: Bearer $KEY" \
    -H "Content-Type: application/json" \
    -d "$(jq -nc --arg t "$text" '{text:$t, voice:"af_bella"}')"
  echo
done
```

Each call returns a job_id; the engine has `_synth_lock` so jobs serialize through one inference.

## Things to remember

- **Text size limit:** 1 MiB request body (way more than you need).
- **Sync wait limit:** 300s. Long narrations should use async + poll.
- **Rate limit:** 60/min per IP. For high-volume use, raise `TTS_BRIDGE_RATE_PER_MIN`.
- **Audio duration cap:** effectively unlimited, but each job takes 1-3s per sentence on GPU, ~10-30s per sentence on CPU. The engine serializes requests through `_synth_lock`.
- **The bridge holds a permanent engine session** (heartbeats every 20-30s) so the engine doesn't auto-stop. Don't kill the bridge while jobs are running.

## JSON encoding for the `text` field

The body has to be **valid JSON**, but the *text content itself* can be anything — quotes, newlines, backslashes, unicode, emoji, tabs. Once JSON-parsed, it's just a Python string passed unmodified to Kokoro.

| What you want in the text | How it must appear in the JSON wire format |
|---|---|
| `She said "hi"` | `"She said \"hi\""` |
| `C:\Users\me` | `"C:\\Users\\me"` |
| newline | `"line1\nline2"` |
| tab | `"col1\tcol2"` |
| `café / 日本語 / 🎉` | write as-is (UTF-8 throughout the request) |
| lone control chars (`\x00`-`\x1f`) | escape as `\u00XX` |

**Tested with embedded double quotes, em-dashes, backslashes, Japanese, emoji, tabs, and newlines — 13s of audio, returned 200.** So just make sure your outer JSON is well-formed and the text content can be whatever you want.

Most tools handle this automatically:
- **PowerShell:** `ConvertTo-Json -Depth 8` escapes correctly
- **Python:** `json.dumps({...})` escapes correctly
- **curl from a heredoc:** use single-quoted heredoc to avoid shell escaping, then use double quotes inside the JSON
- **jq:** `jq -nc --arg t "..." '{text:$t, voice:"af_heart"}'`

## Local quick-reference (PowerShell)

```powershell
$key = Get-Content "$env:USERPROFILE\OneDrive\Documents\My ARK Mods\generalProjects\free-tts-studio-bridge\bridge.key" -Raw
$h = @{ 'Authorization' = "Bearer $key"; 'Content-Type' = 'application/json' }
$body = @{ text='Hello'; voice='af_heart' } | ConvertTo-Json -Compress

# Sync synth
$r = Invoke-WebRequest -UseBasicParsing -Method POST -Uri "https://voice.sean.co/v1/synthesize?wait=true" -Headers $h -Body $body
$r.Content | ConvertFrom-Json
```
