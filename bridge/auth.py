"""API-key authentication for the Free TTS Studio bridge.

Reads `TTS_BRIDGE_API_KEY` from the environment and validates the
`Authorization: Bearer <key>` header on every request. Uses a
constant-time comparison so the key cannot be guessed by timing.

The key is *never* logged and *never* echoed back in any response.
"""

import hmac
import os


def get_api_key():
    """Return the configured API key, or None if not set."""
    key = os.environ.get('TTS_BRIDGE_API_KEY', '').strip()
    return key or None


def key_is_strong(key):
    """Keys must be at least 24 characters of non-trivial entropy.

    We deliberately do NOT validate charset beyond that -- the launcher
    generates a secrets.token_urlsafe(32) string which is well-formed,
    and we don't want to lock out users who paste their own.
    """
    return bool(key) and len(key) >= 24


def extract_bearer(header_value):
    """Return the bearer token from an Authorization header value, or None."""
    if not header_value:
        return None
    parts = header_value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None
    return parts[1].strip() or None


def check(headers):
    """Return True iff the request carries a valid bearer token.

    `headers` is an `http.client`-style mapping (case-insensitive).
    """
    expected = get_api_key()
    if not expected:
        # No key configured -- fail closed. The launcher is responsible
        # for refusing to start without a key (see run-bridge.ps1).
        return False
    presented = extract_bearer(headers.get('Authorization'))
    if not presented:
        return False
    # Constant-time compare; equal-length keys required for honest hmac.
    return hmac.compare_digest(presented.encode('utf-8'), expected.encode('utf-8'))
