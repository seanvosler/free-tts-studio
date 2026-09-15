"""Local Kokoro TTS narration studio - self-contained web UI.

Uses only Python's standard-library HTTP server plus the Kokoro stack, so it
runs on machines where Windows Smart App Control blocks extraneous native
libraries (spaCy, pandas, ...).

Run:  .\run.bat      double-click launcher (opens browser, auto-stops)
      .\run.ps1      PowerShell launcher (same behaviour)
Stop: close the browser tab (auto-stop) or Ctrl+C in the console.
Flags: --no-auto-stop   keep the engine alive with no browser tabs open.
"""

import json
import mimetypes
import os
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import soundfile as sf
import torch

import g2p_nospacy

g2p_nospacy.apply()

from kokoro import KPipeline
from kokoro.model import KModel

REPO_ID = 'hexgrad/Kokoro-82M'
SAMPLE_RATE = 24000
DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
HOST = '127.0.0.1'
PORT = 7860
ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(ROOT, 'output')
STATIC_DIR = os.path.join(ROOT, 'static')

VOICES = [
    ('US - Heart (light)', 'af_heart', 'a'),
    ('US - Alloy', 'af_alloy', 'a'),
    ('US - Aoede', 'af_aoede', 'a'),
    ('US - Bella', 'af_bella', 'a'),
    ('US - Jessica', 'af_jessica', 'a'),
    ('US - Kore', 'af_kore', 'a'),
    ('US - Nicole', 'af_nicole', 'a'),
    ('US - Nova', 'af_nova', 'a'),
    ('US - River', 'af_river', 'a'),
    ('US - Sarah', 'af_sarah', 'a'),
    ('US - Sky', 'af_sky', 'a'),
    ('US - Adam', 'am_adam', 'a'),
    ('US - Echo', 'am_echo', 'a'),
    ('US - Eric', 'am_eric', 'a'),
    ('US - Fenrir', 'am_fenrir', 'a'),
    ('US - Liam', 'am_liam', 'a'),
    ('US - Michael', 'am_michael', 'a'),
    ('US - Onyx', 'am_onyx', 'a'),
    ('US - Puck', 'am_puck', 'a'),
    ('US - Santa', 'am_santa', 'a'),
    ('UK - Alice', 'bf_alice', 'b'),
    ('UK - Emma', 'bf_emma', 'b'),
    ('UK - Isabella', 'bf_isabella', 'b'),
    ('UK - Lily', 'bf_lily', 'b'),
    ('UK - Daniel', 'bm_daniel', 'b'),
    ('UK - Fable', 'bm_fable', 'b'),
    ('UK - George', 'bm_george', 'b'),
    ('UK - Lewis', 'bm_lewis', 'b'),
]

_model = None
_pipelines = {}
_synth_lock = threading.Lock()
_log_lock = threading.Lock()

_sessions = {}
_sessions_lock = threading.Lock()
AUTO_STOP = '--no-auto-stop' not in sys.argv and os.environ.get('KOKORO_AUTO_STOP', '1') != '0'
SESSION_STALE_SECONDS = float(os.environ.get('KOKORO_SESSION_STALE', 90))
ENGINE_GRACE_SECONDS = float(os.environ.get('KOKORO_ENGINE_GRACE', 60))
WATCHDOG_INTERVAL_SECONDS = 5


def log(msg):
    with _log_lock:
        print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def get_model():
    global _model
    if _model is None:
        log(f'Loading Kokoro model on {DEVICE}...')
        _model = KModel(repo_id=REPO_ID).to(DEVICE).eval()
        log('Model loaded.')
    return _model


def get_pipeline(lang_code):
    if lang_code not in _pipelines:
        _pipelines[lang_code] = KPipeline(
            lang_code=lang_code, repo_id=REPO_ID, model=get_model(), device=DEVICE
        )
    return _pipelines[lang_code]


def register_session():
    global _ever_had_session
    sid = uuid.uuid4().hex
    with _sessions_lock:
        _sessions[sid] = time.time()
        _ever_had_session = True
    return sid


def heartbeat_session(sid):
    if not sid:
        return
    with _sessions_lock:
        _sessions[sid] = time.time()


def leave_session(sid):
    if not sid:
        return
    with _sessions_lock:
        _sessions.pop(sid, None)


def prune_sessions():
    cutoff = time.time() - SESSION_STALE_SECONDS
    with _sessions_lock:
        for sid in [s for s in _sessions if _sessions[s] < cutoff]:
            _sessions.pop(sid, None)
        return len(_sessions)


def watchdog_loop(server):
    started = time.time()
    while not server.__dict__.get('_BaseServer__shutdown_request', False):
        time.sleep(WATCHDOG_INTERVAL_SECONDS)
        remaining = prune_sessions()
        if AUTO_STOP and remaining == 0 and time.time() - started > ENGINE_GRACE_SECONDS:
            log('No active browser tabs - stopping engine (auto-stop).')
            server.shutdown()
            return


def synthesize(text, voice_id, speed):
    lang = 'a' if voice_id.startswith('a') else 'b'
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with _synth_lock:
        pipeline = get_pipeline(lang)
        chunks = []
        for _, ps, audio in pipeline(
            text, voice=voice_id, speed=speed,
            split_pattern=r'(?<=[.!?…])\s+|\n+',
        ):
            if audio is not None:
                chunks.append(audio)
        if not chunks:
            raise RuntimeError('No audio produced.')
        audio = torch.cat(chunks).cpu().numpy().astype(np.float32)

    fname = f"{time.strftime('%Y%m%d_%H%M%S')}_{voice_id}.wav"
    path = os.path.join(OUTPUT_DIR, fname)
    sf.write(path, audio, SAMPLE_RATE, subtype='PCM_16')
    log(f'Synthesized {len(audio) / SAMPLE_RATE:.1f}s -> output/{fname}')
    return fname, audio


def list_outputs():
    if not os.path.isdir(OUTPUT_DIR):
        return []
    files = sorted(os.listdir(OUTPUT_DIR), reverse=True)
    return [f for f in files if f.endswith('.wav')]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        if path in ('', '/'):
            path = 'index.html'
        candidate = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip('/')))
        if not candidate.startswith(os.path.normpath(STATIC_DIR)) or not os.path.isfile(candidate):
            self.send_error(404)
            return
        ctype, _ = mimetypes.guess_type(candidate)
        with open(candidate, 'rb') as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype or 'application/octet-stream')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _audio(self, fname):
        path = os.path.normpath(os.path.join(OUTPUT_DIR, fname))
        if not path.startswith(os.path.normpath(OUTPUT_DIR)) or not os.path.isfile(path):
            self.send_error(404)
            return
        with open(path, 'rb') as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header('Content-Type', 'audio/wav')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith('/output/'):
            self._audio(urllib.parse.unquote(parsed.path[len('/output/'):]))
        elif parsed.path == '/api/voices':
            self._json({'voices': [{'label': l, 'id': v} for l, v, _ in VOICES]})
        elif parsed.path == '/api/files':
            self._json({'files': list_outputs()})
        elif parsed.path == '/api/session':
            self._json({'session_id': register_session()})
        else:
            self._static(parsed.path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/api/heartbeat':
            length = int(self.headers.get('Content-Length', 0))
            try:
                req = json.loads(self.rfile.read(length) or b'{}')
            except Exception:
                req = {}
            heartbeat_session(str(req.get('id', '')))
            self._json({'ok': True})
            return

        if path == '/api/leave':
            queried = urllib.parse.parse_qs(parsed.query)
            leave_session(queried.get('session_id', [''])[0])
            self._json({'ok': True})
            return

        if path != '/api/synth':
            self.send_error(404)
            return
        length = int(self.headers.get('Content-Length', 0))
        try:
            req = json.loads(self.rfile.read(length) or b'{}')
            text = str(req.get('text', ''))
            voice = str(req.get('voice', VOICES[0][1]))
            speed = float(req.get('speed', 1.0))
            if not text.strip():
                self._json({'error': 'Please enter some text to narrate.'}, 400)
                return
            valid = {v[1] for v in VOICES}
            if voice not in valid:
                self._json({'error': f'Unknown voice: {voice}'}, 400)
                return
            speed = min(max(speed, 0.5), 2.0)
            fname, audio = synthesize(text, voice, speed)
            self._json({'file': f'/output/{fname}', 'duration': round(len(audio) / SAMPLE_RATE, 2)})
        except RuntimeError as e:
            self._json({'error': str(e)}, 500)


def main():
    global AUTO_STOP, HOST, PORT
    args = sys.argv[1:]
    if '--no-auto-stop' in args:
        AUTO_STOP = False
    if '--port' in args:
        PORT = int(args[args.index('--port') + 1])
    if '--host' in args:
        HOST = args[args.index('--host') + 1]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        log(f'Port {PORT} is already in use ({e}).')
        log('TTS Studio may already be running - just open the page, or close the other instance first.')
        sys.exit(2)

    threading.Thread(target=watchdog_loop, args=(server,), daemon=True).start()
    mode = '' if AUTO_STOP else '  [auto-stop DISABLED]'
    log(f'Kokoro TTS Studio running at http://{HOST}:{PORT}{mode}')
    log('Close the browser tab to stop the engine.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log('Stopping server.')


if __name__ == '__main__':
    main()