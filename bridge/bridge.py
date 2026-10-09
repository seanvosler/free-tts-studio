"""Free TTS Studio -- bridge sidecar.

A stdlib-only HTTP service that:

  * Sits in front of the Kokoro engine (`app.py`) which stays bound to
    127.0.0.1:7860 and untouched.
  * Authenticates every request with a bearer token read from
    `TTS_BRIDGE_API_KEY`.
  * Accepts TTS jobs, assigns them a UUID, dispatches them to a small
    worker pool, and returns immediately (async) or blocks until done
    (`?wait=true`).
  * Streams finished WAV files back to clients without copying them.
  * Heartbeats a session id on the engine every 30s so the engine's
    auto-stop watchdog never fires while the bridge is up.

External exposure (e.g. via cloudflared) is documented in README.md --
this file deliberately knows nothing about TLS or auth beyond the key.
"""

import argparse
import collections
import json
import mimetypes
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import auth
import cleaner
import dashboard
from jobs import (
    ALL_STATUSES, Job, JobStore,
    STATUS_DONE, STATUS_FAILED, STATUS_QUEUED, STATUS_RUNNING,
    TERMINAL_STATUSES,
)

# --- defaults (overridable via env) ---------------------------------------
ENGINE_URL = os.environ.get('TTS_ENGINE_URL', 'http://127.0.0.1:7860').rstrip('/')
KITTEN_URL = os.environ.get('TTS_KITTEN_URL', 'http://127.0.0.1:7862').rstrip('/')
BRIDGE_HOST = os.environ.get('TTS_BRIDGE_HOST', '127.0.0.1')
BRIDGE_PORT = int(os.environ.get('TTS_BRIDGE_PORT', '7861'))
WORKERS = max(1, int(os.environ.get('TTS_BRIDGE_WORKERS', '2')))
RATE_PER_MIN = max(1, int(os.environ.get('TTS_BRIDGE_RATE_PER_MIN', '60')))
WAIT_TIMEOUT = float(os.environ.get('TTS_BRIDGE_WAIT_TIMEOUT', '300'))
# Kitten voice-clone jobs run 8+ minutes; bump the wait timeout when
# the request hits the kitten route, regardless of the global setting.
KITTEN_WAIT_TIMEOUT = float(os.environ.get('TTS_BRIDGE_KITTEN_WAIT_TIMEOUT', '1200'))
MAX_BODY = 1 * 1024 * 1024                 # 1 MiB; synth text is tiny
HEARTBEAT_SECONDS = 30
AUDIT_LOG = os.environ.get(
    'TTS_BRIDGE_AUDIT_LOG',
    # Default: write the audit log next to the parent of the `bridge/`
    # package so it doesn't end up inside the package directory. Falls back
    # to the script directory if the package layout isn't detected.
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))) or
        os.path.dirname(os.path.abspath(__file__)),
        'bridge-audit.log',
    ),
)

# --- shared state ---------------------------------------------------------
_job_store = JobStore(AUDIT_LOG)
_job_queue: 'queue.Queue[Job]' = queue.Queue()
_rate_lock = threading.Lock()
_rate_buckets: dict = collections.defaultdict(collections.deque)
_engine_session = None                  # set at startup; used by heartbeat thread
_known_voices_cache = {'value': None, 'fetched': 0.0}
_known_voices_lock = threading.Lock()


# --- helpers --------------------------------------------------------------
def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def json_response(handler, obj, code=200):
    body = json.dumps(obj).encode('utf-8')
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_error(handler, code, msg):
    json_response(handler, {'error': msg}, code)


def rate_limit_check(ip):
    """Sliding 60-second window. Returns (allowed, retry_after_seconds)."""
    now = time.time()
    with _rate_lock:
        bucket = _rate_buckets[ip]
        # Drop timestamps older than 60s.
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= RATE_PER_MIN:
            retry = max(1, int(60 - (now - bucket[0])))
            return False, retry
        bucket.append(now)
        return True, 0


def client_ip(handler):
    # Honor X-Forwarded-For only when explicitly configured.
    if os.environ.get('TTS_BRIDGE_TRUST_XFF'):
        xff = handler.headers.get('X-Forwarded-For')
        if xff:
            return xff.split(',')[0].strip()
    return handler.client_address[0]


def engine_get(path):
    req = urllib.request.Request(ENGINE_URL + path, method='GET')
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read()


def kitten_get(path, timeout=10):
    req = urllib.request.Request(KITTEN_URL + path, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def kitten_post(path, payload, timeout=None):
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        KITTEN_URL + path,
        data=body,
        method='POST',
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=timeout or (WAIT_TIMEOUT + 30)) as r:
        return r.status, r.read()


def engine_post(path, payload):
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        ENGINE_URL + path,
        data=body,
        method='POST',
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=WAIT_TIMEOUT + 30) as r:
        return r.status, r.read()


def refresh_voice_cache(force=False):
    """Cache the engine's voice list; refreshes every 5 minutes."""
    with _known_voices_lock:
        if not force and _known_voices_cache['value'] is not None \
                and time.time() - _known_voices_cache['fetched'] < 300:
            return _known_voices_cache['value']
        try:
            _, body = engine_get('/api/voices')
            data = json.loads(body)
            voices = data.get('voices', [])
            _known_voices_cache['value'] = voices
            _known_voices_cache['fetched'] = time.time()
            return voices
        except Exception:
            return _known_voices_cache.get('value') or []


# --- worker pool ----------------------------------------------------------
def worker_loop():
    while True:
        job = _job_queue.get()
        if job is None:
            _job_queue.task_done()
            return
        _job_store.mark_running(job)
        try:
            payload = {
                'text': job.text,
                'voice': job.voice,
                'speed': job.speed,
            }
            if job.output_file_name:
                payload['output_file_name'] = job.output_file_name
            status, body = engine_post('/api/synth', payload)
            data = json.loads(body)
            if status >= 400 or 'error' in data:
                err = data.get('error', f'engine returned HTTP {status}')
                _job_store.mark_failed(job, err)
            else:
                _job_store.mark_done(job, data['file'], data['duration'])
        except urllib.error.URLError as e:
            _job_store.mark_failed(job, f'engine unreachable: {e.reason}')
        except Exception as e:
            _job_store.mark_failed(job, f'{type(e).__name__}: {e}')
        finally:
            _job_queue.task_done()


def enqueue_job(job):
    _job_store.add(job)
    _job_queue.put(job)


# --- engine session heartbeat -------------------------------------------
def engine_health():
    """Returns (up: bool, status_code: int|None)."""
    try:
        s, _ = engine_get('/api/voices')
        return s == 200, s
    except Exception:
        return False, None


def acquire_engine_session():
    """Acquire (or refresh) a session id from the engine. Returns True on success."""
    global _engine_session
    try:
        _, body = engine_get('/api/session')
        _engine_session = json.loads(body).get('session_id')
    except Exception as e:
        log(f'heartbeat: engine unreachable ({e})')
        _engine_session = None
    return bool(_engine_session)


def send_heartbeat():
    """Send a single heartbeat. Reacquires session on failure."""
    global _engine_session
    if not _engine_session:
        if not acquire_engine_session():
            return False
    try:
        engine_post('/api/heartbeat', {'id': _engine_session})
        return True
    except Exception:
        # Session probably aged out; drop it so next tick reacquires.
        _engine_session = None
        return False


def heartbeat_loop():
    """Keep the engine's auto-stop watchdog at bay forever."""
    # Send a heartbeat immediately, then every HEARTBEAT_SECONDS.
    # During the first few minutes we send more aggressively (every 20s)
    # because the engine's grace window is 60s and we want a wide margin.
    initial_phase_until = time.time() + 120
    while True:
        ok = send_heartbeat()
        if time.time() < initial_phase_until:
            time.sleep(20)
        else:
            time.sleep(HEARTBEAT_SECONDS)
        if not ok:
            log('heartbeat: lost session, will retry')


# --- HTTP handler ---------------------------------------------------------
class BridgeHandler(BaseHTTPRequestHandler):
    server_version = 'TTSBridge/1.0'

    def log_message(self, *args):
        # Silence the default stderr access log; we have our own minimal one.
        pass

    # ---- low-level helpers ----------------------------------------------
    def _read_json_body(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length > MAX_BODY:
            raise ValueError(f'body too large ({length} bytes; max {MAX_BODY})')
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode('utf-8'))
        except Exception:
            raise ValueError('body is not valid JSON')

    def _auth(self):
        ip = client_ip(self)
        allowed, retry = rate_limit_check(ip)
        if not allowed:
            self.send_response(429)
            self.send_header('Retry-After', str(retry))
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            body = json.dumps({'error': 'rate_limited', 'retry_after': retry}).encode()
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return False
        if not auth.check(self.headers):
            send_error(self, 401, 'unauthorized')
            return False
        return True

    # ---- routing --------------------------------------------------------
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path

        # /healthz is intentionally unauthenticated so monitoring works.
        if path == '/healthz':
            up, _ = engine_health()
            json_response(self, {'ok': True, 'engine': 'up' if up else 'down'})
            return

        # /dashboard is a no-auth HTML page; the JSON it polls requires auth.
        if path == '/dashboard' or path == '/dashboard/':
            body = dashboard.render_dashboard_html().encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return

        if not self._auth():
            return

        if path == '/api/dashboard-data':
            data = dashboard.build_dashboard_data(
                _job_store, engine_health, engine_get)
            json_response(self, data)
            return

        if path == '/v1/voices':
            voices = refresh_voice_cache()
            json_response(self, {'voices': voices})
            return

        # ---- KittenTTS-2 routes ------------------------------------------
        if path == '/v1/kitten/voices':
            try:
                _, body = kitten_get('/api/voices', timeout=15)
                data = json.loads(body)
                json_response(self, data)
            except Exception as e:
                send_error(self, 502, f'kitten engine unreachable: {e}')
            return
        if path.startswith('/v1/kitten/jobs/'):
            jid = urllib.parse.unquote(path[len('/v1/kitten/jobs/'):])
            try:
                _, body = kitten_get('/api/jobs/' + urllib.parse.quote(jid, safe=''), timeout=10)
                data = json.loads(body)
                json_response(self, data)
            except urllib.error.HTTPError as he:
                send_error(self, he.code, he.read().decode('utf-8', 'replace'))
            except Exception as e:
                send_error(self, 502, f'kitten engine unreachable: {e}')
            return
        if path == '/v1/kitten/files':
            try:
                _, body = kitten_get('/api/files', timeout=10)
                data = json.loads(body)
                json_response(self, data)
            except Exception as e:
                send_error(self, 502, f'kitten engine unreachable: {e}')
            return
        if path.startswith('/v1/kitten/files/'):
            fname = urllib.parse.unquote(path[len('/v1/kitten/files/'):])
            self._proxy_kitten_file(fname)
            return
        # -------------------------------------------------------------------

        if path == '/v1/jobs':
            limit = 100
            try:
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                if 'limit' in q:
                    limit = max(1, min(500, int(q['limit'][0])))
            except Exception:
                pass
            json_response(self, {'jobs': _job_store.list_recent(limit)})
            return

        if path.startswith('/v1/jobs/'):
            jid = urllib.parse.unquote(path[len('/v1/jobs/'):])
            job = _job_store.get(jid)
            if job is None:
                send_error(self, 404, 'unknown job id')
                return
            # `?wait=true` blocks until the job is terminal, so callers can
            # do an async submit + single blocking poll instead of round-tripping.
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if qs.get('wait', [''])[0].lower() in ('1', 'true', 'yes'):
                finished = job._event.wait(timeout=WAIT_TIMEOUT)
                if not finished:
                    json_response(self, {
                        'job_id': job.id,
                        'status': 'timeout',
                        'message': 'still processing or failed',
                        'poll_url': f'/v1/jobs/{job.id}',
                    }, 504)
                    return
            json_response(self, job.to_dict())
            return

        if path.startswith('/v1/files/'):
            fname = urllib.parse.unquote(path[len('/v1/files/'):])
            self._proxy_file(fname)
            return

        if path == '/v1/files':
            try:
                _, body = engine_get('/api/files')
                data = json.loads(body)
                json_response(self, data)
            except Exception as e:
                send_error(self, 502, f'engine unreachable: {e}')
            return

        send_error(self, 404, 'no such route')

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path

        if not self._auth():
            return

        if path == '/v1/synthesize':
            self._do_synth()
            return

        if path == '/v1/kitten/synthesize':
            self._do_kitten_synth()
            return

        send_error(self, 404, 'no such route')

    def do_DELETE(self):
        path = urllib.parse.urlsplit(self.path).path
        if not self._auth():
            return
        if path.startswith('/v1/jobs/'):
            jid = urllib.parse.unquote(path[len('/v1/jobs/'):])
            job = _job_store.get(jid)
            if job is None:
                send_error(self, 404, 'unknown job id')
                return
            if job.is_terminal():
                json_response(self, {'ok': True, 'status': job.status})
                return
            # Best-effort cancel: mark failed. We cannot un-cancel a job
            # that's already mid-synth on the engine, but we can stop the
            # caller from waiting further.
            _job_store.mark_failed(job, 'cancelled by client')
            json_response(self, {'ok': True, 'status': 'failed'})
            return
        send_error(self, 404, 'no such route')

    # ---- handlers -------------------------------------------------------
    def _do_synth(self):
        try:
            payload = self._read_json_body()
        except ValueError as e:
            send_error(self, 400, str(e))
            return

        text = str(payload.get('text', ''))
        voice = str(payload.get('voice', ''))
        try:
            speed = float(payload.get('speed', 1.0))
        except Exception:
            send_error(self, 400, 'speed must be a number')
            return
        speed = min(max(speed, 0.5), 2.0)
        if not text.strip():
            send_error(self, 400, 'text is required')
            return
        voices = refresh_voice_cache()
        valid = {v['id'] for v in voices}
        if voice and voice not in valid:
            # The engine would catch this too; friendlier early reply.
            send_error(self, 400, f'unknown voice: {voice}')
            return
        if not voice:
            voice = (voices[0]['id'] if voices else 'af_heart')

        # Optional custom output filename. Sanitized in the engine, but
        # we also validate here to fail fast with a clear error.
        custom_name = payload.get('output_file_name')
        if custom_name is not None:
            custom_name = str(custom_name).strip() or None
            if custom_name is not None:
                if len(custom_name) > 120:
                    send_error(self, 400, 'output_file_name too long (max 120 chars)')
                    return
                if any(c in custom_name for c in ('/', '\\', '\x00')):
                    send_error(self, 400, 'output_file_name must not contain path separators')
                    return

        # Optional markdown cleaner. Default off so existing callers see no
        # change. The cleaner preserves paragraph breaks and never raises;
        # any unexpected error falls back to the raw text with a log line.
        clean_md = bool(payload.get('clean_markdown'))
        if clean_md:
            try:
                cleaned = cleaner.clean_markdown(text)
            except Exception as e:
                log(f'cleaner error (passing through raw text): {e!r}')
            else:
                if cleaned != text:
                    log(f'clean_markdown: {len(text)} -> {len(cleaned)} chars')
                    text = cleaned
                if not text.strip():
                    send_error(self, 400, 'text is required (empty after markdown cleaning)')
                    return

        # Optional TTS-specific normalization (acronyms, long-sentence pauses).
        # Default off; runs AFTER clean_markdown if both are enabled.
        tts_norm = bool(payload.get('tts_normalize'))
        if tts_norm:
            try:
                normalized = cleaner.tts_normalize(text)
            except Exception as e:
                log(f'tts_normalize error (passing through): {e!r}')
            else:
                if normalized != text:
                    log(f'tts_normalize: {len(text)} -> {len(normalized)} chars')
                    text = normalized

        up, _ = engine_health()
        if not up:
            send_error(self, 502, 'engine_down')
            return

        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        wait = q.get('wait', [''])[0].lower() in ('1', 'true', 'yes')

        job = Job(text=text, voice=voice, speed=speed, wait=wait,
                  client_ip=client_ip(self), output_file_name=custom_name)
        enqueue_job(job)
        log(f'job {job.id} queued (voice={voice}, {len(text)} chars, wait={wait}, name={custom_name or "auto"}, clean_md={clean_md}, tts_norm={tts_norm})')

        if not wait:
            json_response(self, {'job_id': job.id, 'status': job.status}, 202)
            return

        # Sync mode: block until terminal or timeout.
        finished = job._event.wait(timeout=WAIT_TIMEOUT)
        if not finished:
            # Don't fail the job -- it's still running. Tell caller
            # exactly that so they can poll.
            json_response(self, {
                'job_id': job.id,
                'status': 'timeout',
                'message': 'still processing or failed',
                'poll_url': f'/v1/jobs/{job.id}',
            }, 504)
            return

        if job.status == STATUS_DONE:
            json_response(self, {
                'job_id': job.id,
                'status': job.status,
                'file': job.file,
                'duration': job.duration,
                'url': f'{ENGINE_URL}{job.file}',
            })
            return

        # STATUS_FAILED or anything else.
        send_error(self, 500, job.error or 'synthesis failed')

    # ---- KittenTTS-2 route ---------------------------------------------
    def _do_kitten_synth(self):
        try:
            payload = self._read_json_body()
        except ValueError as e:
            send_error(self, 400, str(e))
            return

        text = str(payload.get('text', ''))
        if not text.strip():
            send_error(self, 400, 'text is required')
            return

        voice = str(payload.get('voice', '') or 'Bella')
        try:
            speed = float(payload.get('speed', 1.0))
        except Exception:
            send_error(self, 400, 'speed must be a number')
            return
        speed = min(max(speed, 0.5), 2.0)

        emotion = payload.get('emotion')
        if emotion is not None:
            emotion = str(emotion).strip().lower() or None
        normalize = bool(payload.get('normalize', True))
        reference = payload.get('reference_audio') or payload.get('reference')
        if reference is not None:
            reference = str(reference)
        custom_name = payload.get('output_file_name')
        if custom_name is not None:
            custom_name = str(custom_name).strip() or None
            if custom_name and any(c in custom_name for c in ('/', '\\', '\x00')):
                send_error(self, 400, 'output_file_name must not contain path separators')
                return

        # Validate engine reachability before doing anything.
        try:
            s, _ = kitten_get('/healthz', timeout=5)
            if s != 200:
                send_error(self, 502, f'kitten engine not healthy ({s})')
                return
        except Exception as e:
            send_error(self, 502, f'kitten engine unreachable: {e}')
            return

        # Run the same cleaner + tts_normalize passes if requested.
        clean_md = bool(payload.get('clean_markdown'))
        if clean_md:
            try:
                text = cleaner.clean_markdown(text)
            except Exception as e:
                log(f'cleaner error (kitten path, passing through): {e!r}')
            if not text.strip():
                send_error(self, 400, 'text is required (empty after markdown cleaning)')
                return
        tts_norm = bool(payload.get('tts_normalize'))
        if tts_norm:
            try:
                text = cleaner.tts_normalize(text)
            except Exception as e:
                log(f'tts_normalize error (kitten path): {e!r}')

        # Voice cloning is too slow for sync (8+ min). Force async so
        # callers get a job_id immediately and can poll.
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        wait = q.get('wait', [''])[0].lower() in ('1', 'true', 'yes')
        if reference and wait:
            wait = False

        # Build the engine request body. Only forward fields Kitten knows
        # about; custom_name is handled by the engine via renaming.
        body = {
            'text': text,
            'voice': voice,
            'speed': speed,
            'normalize': normalize,
        }
        if emotion:
            body['emotion'] = emotion
        if reference:
            body['reference_audio'] = reference
        if custom_name:
            body['output_file_name'] = custom_name

        timeout = KITTEN_WAIT_TIMEOUT if reference else (WAIT_TIMEOUT + 60)
        engine_q = '?wait=true' if wait else ''
        try:
            status, raw = kitten_post('/api/synth' + engine_q, body, timeout=timeout)
        except urllib.error.HTTPError as he:
            send_error(self, he.code, he.read().decode('utf-8', 'replace'))
            return
        except Exception as e:
            send_error(self, 502, f'kitten engine call failed: {e}')
            return

        data = json.loads(raw)
        # 202 from the engine means async; surface a poll_url.
        if status == 202:
            data.setdefault('status', 'queued')
            data['poll_url'] = f'/v1/kitten/jobs/{data.get("job_id", "")}'
            json_response(self, data, 202)
            return
        # 200 sync: translate the engine's file path into the bridge's
        # public URL (matches the Kokoro response shape).
        fname = (data.get('filename')
                 or (data.get('file', '').split('/')[-1] if data.get('file') else None))
        json_response(self, {
            'ok': True,
            'status': 'done',
            'engine': 'kitten',
            'job_id': None,
            'filename': fname,
            'duration': data.get('duration'),
            'url': (f'{KITTEN_URL}{data.get("file", "")}' if data.get('file') else None),
        })

    def _proxy_kitten_file(self, fname):
        if '/' in fname or '\\' in fname or '..' in fname or not fname:
            send_error(self, 400, 'invalid filename')
            return
        try:
            req = urllib.request.Request(
                f'{KITTEN_URL}/output/{urllib.parse.quote(fname)}',
                method='GET',
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                ctype = r.headers.get('Content-Type', 'application/octet-stream')
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                send_error(self, 404, 'no such file')
            else:
                send_error(self, 502, f'kitten engine returned {e.code}')
        except Exception as e:
            send_error(self, 502, f'kitten engine unreachable: {e}')

    def _proxy_file(self, fname):
        # Defense-in-depth against path traversal.
        if '/' in fname or '\\' in fname or '..' in fname or not fname:
            send_error(self, 400, 'invalid filename')
            return
        try:
            req = urllib.request.Request(
                f'{ENGINE_URL}/output/{urllib.parse.quote(fname)}',
                method='GET',
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                ctype = r.headers.get('Content-Type', 'application/octet-stream')
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                send_error(self, 404, 'no such file')
            else:
                send_error(self, 502, f'engine returned {e.code}')
        except Exception as e:
            send_error(self, 502, f'engine unreachable: {e}')


# --- bootstrap -----------------------------------------------------------
def preflight():
    key = auth.get_api_key()
    if not key:
        sys.stderr.write(
            'FATAL: TTS_BRIDGE_API_KEY is not set.\n'
            '       Generate one with:  python -c "import secrets; print(secrets.token_urlsafe(32))"\n'
            '       Then export it (e.g. set TTS_BRIDGE_API_KEY=...) before running.\n'
        )
        sys.exit(2)
    if not auth.key_is_strong(key):
        sys.stderr.write(
            f'FATAL: TTS_BRIDGE_API_KEY is too short '
            f'({len(key)} chars; need >=24).\n'
        )
        sys.exit(2)
    log(f'auth: API key loaded ({len(key)} chars, OK)')
    log(f'engine: {ENGINE_URL}')
    log(f'bind: {BRIDGE_HOST}:{BRIDGE_PORT}  workers={WORKERS}  rate={RATE_PER_MIN}/min  wait_timeout={WAIT_TIMEOUT}s')


def main():
    parser = argparse.ArgumentParser(description='Free TTS Studio bridge')
    parser.add_argument('--host', default=None, help='override TTS_BRIDGE_HOST')
    parser.add_argument('--port', type=int, default=None, help='override TTS_BRIDGE_PORT')
    parser.add_argument('--engine-url', default=None, help='override TTS_ENGINE_URL')
    args = parser.parse_args()

    global BRIDGE_HOST, BRIDGE_PORT, ENGINE_URL
    if args.host:
        BRIDGE_HOST = args.host
    if args.port:
        BRIDGE_PORT = args.port
    if args.engine_url:
        ENGINE_URL = args.engine_url.rstrip('/')

    preflight()

    # Worker pool.
    threads = [threading.Thread(target=worker_loop, daemon=True)
               for _ in range(WORKERS)]
    for t in threads:
        t.start()
    log(f'workers: started {len(threads)}')

    # Acquire an engine session synchronously BEFORE serving traffic.
    # This prevents the engine's 60s auto-stop grace from expiring while
    # the bridge is mid-startup.
    deadline = time.time() + 30
    while time.time() < deadline:
        if acquire_engine_session():
            log(f'engine session acquired: {_engine_session[:8]}...')
            break
        log('engine not reachable yet, retrying in 2s...')
        time.sleep(2)
    if not _engine_session:
        log('WARNING: engine still unreachable after 30s; bridge will keep trying in background.')

    # Heartbeat thread (keeps engine auto-stop at bay).
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    log('heartbeat: started (20s for first 2 min, then 30s)')

    # Eagerly warm the voice cache so the first /v1/synthesize is fast.
    refresh_voice_cache(force=True)

    server = ThreadingHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    log(f'listening: http://{BRIDGE_HOST}:{BRIDGE_PORT}')
    log('ready.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log('shutting down (Ctrl+C).')
        server.shutdown()


if __name__ == '__main__':
    main()
