# Free TTS Studio

A fully **local, offline-first text-to-speech narration studio** for Windows, powered by
the [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) neural TTS model. Everything
runs **on your own machine** (CPU or NVIDIA CUDA GPU) — no cloud accounts, no API keys,
no paid tiers, and your text/audio never leaves your PC except through your own browser tab.

## What this is

A self-contained, two-file web app:

- **`app.py`** — a single-process local HTTP server built on Python's **standard library**
  (`http.server`), which loads Kokoro, renders the UI, and synthesizes narrated WAV clips.
- **`g2p_nospacy.py`** — a drop-in, pure-Python G2P shim that lets Kokoro/misaki run
  **without spaCy** (see *Why no spaCy?* below).
- **`static/index.html`** — the entire browser UI (HTML+CSS+JS in one file).

You see a web page at `http://localhost:7860`, pick a voice, type your script, press
**Generate**, and get a ready-to-import `.wav` narration track. There's **no server to
host, no account, and no per-use cost**.

## Quick start (Windows)

1. Install [Python 3.11](https://www.python.org/downloads/windows/) (3.12 also works).
2. Double-click **`run.bat`** (whole thing is self-contained — it creates its own venv,
   installs pinned dependencies, downloads the ~330 MB model on first launch, and opens
   your browser).
3. Pick a **voice**, type your script, choose a **speed**, and click **Generate**.
4. Your narration is saved as a `.wav` under `output/` and is playable + downloadable in
   the page. Click **Open in Explorer** (or use the `/output/<name>` link) to reuse it in
   your projects.

### Stopping it

The engine **auto-stops when you close the browser tab** (it keeps itself alive only while
at least one tab has an active session, with a configurable grace period). You can also
press `Ctrl+C` in the console, or run with `--no-auto-stop` if you want it to stay hot.

### Updating

Double-click **`update.bat`** to pull the latest pinned dependencies and model bits into
your existing venv (no full reinstall).

## Requirements

- **Python 3.11 or 3.12** on Windows 10/11 (tested on Python 3.11.9, Windows 11).
- **~3 GB free disk** for the venv + model cache.
- **Hardware:** runs on CPU, and is much faster on an NVIDIA GPU with CUDA (tested on an
  RTX 5070 / cu128). The launcher auto-selects CUDA when available.

### Windows / Smart App Control note

This was built specifically for machines where **Windows Smart App Control (SAC)** blocks
unsigned native DLLs (the "An Application Control policy has blocked this file" error).
Two offenders stripped out:

- **No spaCy** — Kokoro/misaki's G2P normally pulls in `spaCy` (a large native `.pyd`).
  `g2p_nospacy.py` replaces the spaCy-based tokenizer/POS tagger with a small NLTK-based
  one, so no unsigned native DLL is ever loaded governments.
- **No Gradio / pandas / spaCy** — the UI is a hand-written single-file HTML page served by
  the standard library, so none of the native-heavy UI stack is needed.

Everything else in the stack (`torch`, `transformers`, `kokoro`, `misaki`, `espeakng-loader`,
`nltk`, `soundfile`) loads cleanly even under SAC. On machines without SAC, it also just
works normally.

## Installation (manual, in case you want to avoid the launchers)

```
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu128  # GPU builds
.\.venv\Scripts\python.exe app.py
```

On first run it downloads the Kokoro model (~330 MB) and NLTK data from the internet; all
subsequent runs are fully offline.

## Supported voices

Kokoro's built-in voice set (US + UK English accents, male + female). Full list with
labels lives in `static/index.html`; select one via the dropdown in the UI.

| Accent | Voice ids                      |
|--------|--------------------------------|
| US (AF, female) | `af_bella`, `af_nicole`, `af_sarah`, `af_sky`, `af_heart` ... |
| US (AM, male)   | `am_adam`, `am_echo`, `am_eric`, `am_fenrir`, `am_liam` ...    |
| UK (BF, female) | `bf_alice`, `bf_emma`, `bf_isabella`, `bf_lily` ...            |
| UK (BM, male)   | `bm_daniel`, `bm_fable`, `bm_george`, `bm_lewis` ...           |

## Project layout

```
free-tts-studio/
├── app.py               # server + synthesis engine (stdlib HTTP)
├── g2p_nospacy.py       # spaCy-free G2P shim (NLTK-based)
├── static/index.html    # single-file web UI
├── run.bat / run.ps1    # launchers (double-click)
├── update.bat / update.ps1
├── requirements.txt     # pinned deps
├── README.md
└── LICENSE
```

## Model & license

- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) — model + voices by
  hexgrad; Apache-2.0 (model weights: see the Kokoro repo for exact terms).
- This project's own code (server + shim + UI) is **MIT** — see `LICENSE`.

MIT License

Copyright (c) 2026 Sean Vosler

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
