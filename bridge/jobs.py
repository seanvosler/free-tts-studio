"""Job store for the Free TTS Studio bridge.

Holds in-memory Job objects keyed by job id, plus a JSONL audit log on
disk. Thread-safe -- the bridge uses multiple worker threads that all
mutate Job state concurrently.
"""

import json
import os
import threading
import time
import uuid


STATUS_QUEUED = 'queued'
STATUS_RUNNING = 'running'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'

ALL_STATUSES = (STATUS_QUEUED, STATUS_RUNNING, STATUS_DONE, STATUS_FAILED)
TERMINAL_STATUSES = (STATUS_DONE, STATUS_FAILED)


class Job:
    __slots__ = (
        'id', 'text', 'voice', 'speed', 'wait',
        'status', 'file', 'duration', 'error',
        'created_at', 'started_at', 'finished_at',
        'client_ip', '_event',
    )

    def __init__(self, text, voice, speed, wait, client_ip):
        self.id = uuid.uuid4().hex
        self.text = text
        self.voice = voice
        self.speed = speed
        self.wait = wait
        self.client_ip = client_ip
        self.status = STATUS_QUEUED
        self.file = None
        self.duration = None
        self.error = None
        self.created_at = time.time()
        self.started_at = None
        self.finished_at = None
        self._event = threading.Event()

    def to_dict(self):
        d = {
            'job_id': self.id,
            'status': self.status,
            'voice': self.voice,
            'speed': self.speed,
            'created_at': self.created_at,
            'started_at': self.started_at,
            'finished_at': self.finished_at,
        }
        if self.file is not None:
            d['file'] = self.file
            d['duration'] = self.duration
        if self.error is not None:
            d['error'] = self.error
        return d

    def is_terminal(self):
        return self.status in TERMINAL_STATUSES


class JobStore:
    """Thread-safe in-memory job store + JSONL audit appender.

    Holds at most `max_in_memory` jobs (oldest evicted first) so the
    bridge doesn't grow without bound under heavy use. Every state
    transition appends a single JSON line to the audit log.
    """

    def __init__(self, audit_path, max_in_memory=1000):
        self._lock = threading.Lock()
        self._jobs = {}               # id -> Job
        self._order = []              # insertion order of ids
        self._max = max_in_memory
        self._audit_path = audit_path
        self._audit_lock = threading.Lock()
        # Ensure audit file exists so we can append safely.
        os.makedirs(os.path.dirname(audit_path) or '.', exist_ok=True)
        # We do *not* truncate -- users want a long history.
        # Rotation is out of scope for this milestone.

    def add(self, job):
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > self._max:
                old = self._order.pop(0)
                self._jobs.pop(old, None)
        self._audit('queued', job)

    def get(self, job_id):
        with self._lock:
            return self._jobs.get(job_id)

    def list_recent(self, limit=100):
        with self._lock:
            ids = list(reversed(self._order))
        out = []
        for jid in ids:
            if len(out) >= limit:
                break
            j = self.get(jid)
            if j is not None:
                out.append(j.to_dict())
        return out

    def set_status(self, job, status, **fields):
        with self._lock:
            job.status = status
            for k, v in fields.items():
                setattr(job, k, v)
        self._audit(status, job)

    def mark_done(self, job, file_url, duration):
        self.set_status(job, STATUS_DONE,
                        file=file_url, duration=duration,
                        finished_at=time.time())
        job._event.set()

    def mark_failed(self, job, error):
        self.set_status(job, STATUS_FAILED,
                        error=str(error),
                        finished_at=time.time())
        job._event.set()

    def mark_running(self, job):
        self.set_status(job, STATUS_RUNNING,
                        started_at=time.time())

    def _audit(self, status, job):
        # Keep audit payload deliberately small -- no text, no key.
        record = {
            'ts': time.time(),
            'job_id': job.id,
            'status': status,
            'voice': job.voice,
            'speed': job.speed,
            'ip': job.client_ip,
        }
        if job.duration is not None:
            record['duration_s'] = job.duration
        if job.error is not None:
            record['error'] = job.error
        line = json.dumps(record, ensure_ascii=False) + '\n'
        with self._audit_lock:
            try:
                with open(self._audit_path, 'a', encoding='utf-8') as fh:
                    fh.write(line)
            except OSError:
                # Audit failures must never crash the bridge.
                pass
