# Security Policy

## Supported versions

The latest commit on `main` is the only version that receives security
fixes. Older commits are not patched.

## Reporting a vulnerability

If you discover a security issue in this project, please report it
privately via **GitHub Security Advisories** for this repository
(<https://github.com/seanvosler/free-tts-studio/security/advisories/new>).
Do **not** open a public issue for security problems.

We aim to acknowledge reports within 7 days.

## Built-in safeguards

- The Kokoro engine listens on `127.0.0.1:7860` and is never reachable
  from the network.
- The optional bridge (see README → *Experimental: local API mode*)
  listens on `127.0.0.1` by default and refuses to start without a
  bearer token of at least 24 characters.
- The bearer token is compared with `hmac.compare_digest` (constant
  time) to prevent timing attacks.
- The audit log records job metadata but never contains the API key,
  text payload, or audio content.

## Operator responsibilities

- Generate a fresh API key (`python -c "import secrets; print(secrets.token_urlsafe(32))"`)
  before first use. Do not reuse keys across machines.
- If you bind the bridge to `0.0.0.0`, **terminate TLS in front of it**
  (e.g. via `cloudflared`, Caddy, or another reverse proxy). Plain
  HTTP on a LAN is not a secure transport.
- The bridge grants anyone who can reach it the ability to enqueue
  synthesis jobs and read every WAV in `output/`. Treat the key like
  a password.
- Rotate the key if you suspect it has leaked.

## Out of scope

- Vulnerabilities in the [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)
  model itself should be reported upstream to hexgrad.
- Vulnerabilities in `torch`, `transformers`, `kokoro`, `misaki`, or any
  other dependency should be reported to the relevant upstream project.
