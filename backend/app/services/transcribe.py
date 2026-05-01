"""Whisper transcription service with pluggable backends.

Two backends are supported behind a single ``transcribe_file`` entry point:

  - ``ctranslate2`` — faster-whisper (CTranslate2 + CUDA on Linux+NVIDIA,
    falls back to CPU elsewhere). Mature, fast, well-tested. Default on
    Linux and Windows.
  - ``whispercpp`` — pywhispercpp (whisper.cpp + Metal on Apple Silicon).
    Default on macOS where Metal acceleration closes most of the gap with
    faster-whisper + CUDA.

Choice is made at startup from the ``WHISPER_BACKEND`` env var; ``auto``
picks ``whispercpp`` on Darwin and ``ctranslate2`` everywhere else. Both
backends produce the same transcript JSON shape, so callers don't care
which one ran.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from app import cuda_preload  # noqa: F401  # must precede faster_whisper import
from app import platform as plat

from app.config import settings

logger = logging.getLogger(__name__)

# (message, percent in [0, 1]) — same shape as the reframe progress callback,
# so the runner can reuse one helper to update job rows.
ProgressCB = Callable[[str, float], None]

# Cached models per backend. Loading is cheap-ish but model weights stay
# resident, so we keep the singleton for the process lifetime.
_ct2_model: Any = None
_whispercpp_model: Any = None
_model_lock = Lock()


# ---------- Backend selection ---------------------------------------------

def _resolve_backend() -> str:
    """Pick which Whisper implementation to use.

    Reads WHISPER_BACKEND from .env. ``auto`` picks ``whispercpp`` on
    macOS (Metal accelerates Whisper there) and ``ctranslate2``
    elsewhere (faster-whisper is the most mature path on Linux/Windows).
    """
    backend = (settings.whisper_backend or "auto").lower()
    if backend in ("auto", ""):
        backend = "whispercpp" if plat.PLATFORM == "Darwin" else "ctranslate2"
    if backend not in ("ctranslate2", "whispercpp"):
        logger.warning("Unknown WHISPER_BACKEND=%r; falling back to ctranslate2", backend)
        backend = "ctranslate2"
    return backend


def _resolve_device() -> tuple[str, str]:
    """For the ctranslate2 backend: pick (device, compute_type).

    Honours WHISPER_DEVICE from .env but degrades gracefully:
    - auto / unset → cuda if the NVIDIA driver is loaded, else cpu
    - cuda but no driver → cpu + int8 (with a warning), since
      faster-whisper would crash trying to init CUDA otherwise
    """
    requested = (settings.whisper_device or "auto").lower()
    compute = settings.whisper_compute_type or "int8"

    if requested in ("auto", ""):
        device = "cuda" if plat.CUDA_AVAILABLE else "cpu"
    elif requested == "cuda" and not plat.CUDA_AVAILABLE:
        logger.warning(
            "WHISPER_DEVICE=cuda but no CUDA driver detected — "
            "falling back to CPU. Transcription will be ~5-10× slower."
        )
        device = "cpu"
    else:
        device = requested

    # On CPU, int8 is the only universally-supported compute_type with
    # reasonable speed. Override anything fancier the user requested.
    if device == "cpu" and compute not in ("int8", "int16", "int8_float32"):
        compute = "int8"

    return device, compute


# ---------- Backend: faster-whisper / CTranslate2 -------------------------

def _get_ct2_model():
    """Lazy-load + cache the faster-whisper model."""
    global _ct2_model
    with _model_lock:
        if _ct2_model is None:
            from faster_whisper import WhisperModel
            device, compute = _resolve_device()
            logger.info(
                "loading faster-whisper (model=%s, device=%s, compute_type=%s)",
                settings.whisper_model, device, compute,
            )
            _ct2_model = WhisperModel(
                settings.whisper_model,
                device=device,
                compute_type=compute,
            )
    return _ct2_model


def _transcribe_ctranslate2(source: Path, progress_cb: ProgressCB | None) -> dict:
    model = _get_ct2_model()
    segments_iter, info = model.transcribe(str(source), word_timestamps=True)
    duration = float(info.duration or 0)
    segments = []
    for i, seg in enumerate(segments_iter):
        segments.append({
            "id": i,
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
            "words": [
                {"word": w.word, "start": w.start, "end": w.end}
                for w in (seg.words or [])
            ],
        })
        if progress_cb is not None and duration > 0:
            pct = min(1.0, float(seg.end) / duration)
            progress_cb(f"Transcribing audio ({int(seg.end)}/{int(duration)}s)", pct)
    return {
        "source": source.name,
        "duration": info.duration,
        "language": info.language,
        "language_probability": info.language_probability,
        "model": settings.whisper_model,
        "backend": "ctranslate2",
        "compute_type": settings.whisper_compute_type,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "segments": segments,
    }


# ---------- Backend: whisper.cpp / pywhispercpp ---------------------------

def _get_whispercpp_model():
    """Lazy-load + cache the whisper.cpp model.

    pywhispercpp downloads ggml weights to ``~/.cache/whispercpp/`` on
    first use, keyed by model name. ``large-v3`` is ~3 GB.
    """
    global _whispercpp_model
    with _model_lock:
        if _whispercpp_model is None:
            try:
                from pywhispercpp.model import Model
            except ImportError as exc:
                raise RuntimeError(
                    "pywhispercpp is not installed.  On macOS run "
                    "`pip install pywhispercpp` (requires Xcode Command "
                    "Line Tools for the C++ build), or set "
                    "WHISPER_BACKEND=ctranslate2 in .env to use the CPU "
                    "fallback."
                ) from exc
            logger.info(
                "loading whisper.cpp (model=%s, backend=metal)", settings.whisper_model,
            )
            # pywhispercpp picks the right backend automatically — Metal
            # on Apple Silicon, CPU elsewhere. No device knob to turn.
            _whispercpp_model = Model(
                settings.whisper_model,
                # Reduce log verbosity; we manage progress via the callback.
                print_progress=False,
                print_realtime=False,
            )
    return _whispercpp_model


def _transcribe_whispercpp(source: Path, progress_cb: ProgressCB | None) -> dict:
    model = _get_whispercpp_model()
    # word_timestamps=True asks whisper.cpp to record per-token timing,
    # which we map to word-level entries below.
    segments = model.transcribe(
        str(source),
        word_timestamps=True,
        language="auto",
    )

    out_segments: list[dict] = []
    duration = 0.0
    last_pct_emit = -1.0

    for i, seg in enumerate(segments):
        # whisper.cpp returns timestamps in centiseconds (1/100 sec).
        seg_start = float(seg.t0) / 100.0
        seg_end = float(seg.t1) / 100.0
        words: list[dict] = []
        for tok in (getattr(seg, "tokens", None) or []):
            text = getattr(tok, "text", None) or ""
            # Skip whisper's special / control tokens (<|en|>, <|endoftext|>, etc.).
            if not text or text.startswith("<|"):
                continue
            words.append({
                "word": text,
                "start": float(tok.t0) / 100.0,
                "end": float(tok.t1) / 100.0,
            })
        out_segments.append({
            "id": i,
            "start": seg_start,
            "end": seg_end,
            "text": getattr(seg, "text", ""),
            "words": words,
        })
        duration = max(duration, seg_end)
        # Throttle progress updates: emit on every ~5% jump to avoid
        # hammering SQLite.
        if progress_cb is not None and duration > 0:
            pct = min(1.0, seg_end / duration if duration > 0 else 0.0)
            if pct >= last_pct_emit + 0.05 or pct >= 1.0:
                progress_cb(f"Transcribing audio ({int(seg_end)}/{int(duration)}s)", pct)
                last_pct_emit = pct

    # whisper.cpp doesn't expose a confidence-style language probability
    # the way faster-whisper does. Best effort: use the detected language
    # if pywhispercpp surfaces it; otherwise None.
    language = getattr(model, "context", None)
    language = getattr(language, "language", None) if language else None

    return {
        "source": source.name,
        "duration": duration,
        "language": language,
        "language_probability": None,
        "model": settings.whisper_model,
        "backend": "whispercpp",
        "compute_type": "metal" if plat.PLATFORM == "Darwin" else "cpu",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "segments": out_segments,
    }


# ---------- Public entry point --------------------------------------------

def transcribe_file(source: Path, progress_cb: ProgressCB | None = None) -> dict:
    """Transcribe an audio/video file and return a JSON-serializable transcript.

    Blocking. Call from a thread (asyncio.to_thread) when invoked from async code.
    Backend chosen by WHISPER_BACKEND env var; both backends produce the
    same output shape.
    """
    backend = _resolve_backend()
    if backend == "whispercpp":
        return _transcribe_whispercpp(source, progress_cb)
    return _transcribe_ctranslate2(source, progress_cb)


def transcript_path_for(source_name: str) -> Path:
    return settings.data_work_dir / Path(source_name).stem / "transcript.json"


def write_transcript(transcript: dict) -> Path:
    out = transcript_path_for(transcript["source"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(transcript, indent=2))
    return out
