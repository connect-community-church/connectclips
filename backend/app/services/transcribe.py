"""faster-whisper transcription service.

Loads the model lazily on first call and reuses it for the lifetime of the
process. faster-whisper accepts video files directly (via PyAV), so callers
pass either audio or video paths.

`WHISPER_DEVICE=auto` (the new default) picks CUDA if the NVIDIA driver
is detected at startup, otherwise CPU. Callers can force a specific
device by setting WHISPER_DEVICE=cuda or =cpu in .env. CPU is ~5-10×
slower than CUDA but works on every platform.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from threading import Lock
from typing import Callable

from app import cuda_preload  # noqa: F401  # must precede faster_whisper import
from app import platform as plat
from faster_whisper import WhisperModel

from app.config import settings

logger = logging.getLogger(__name__)

# (message, percent in [0, 1]) — same shape as the reframe progress callback,
# so the runner can reuse one helper to update job rows.
ProgressCB = Callable[[str, float], None]

_model: WhisperModel | None = None
_model_lock = Lock()


def _resolve_device() -> tuple[str, str]:
    """Decide the actual (device, compute_type) for faster-whisper.

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


def _get_model() -> WhisperModel:
    global _model
    with _model_lock:
        if _model is None:
            device, compute = _resolve_device()
            logger.info(
                "loading WhisperModel(model=%s, device=%s, compute_type=%s)",
                settings.whisper_model, device, compute,
            )
            _model = WhisperModel(
                settings.whisper_model,
                device=device,
                compute_type=compute,
            )
    return _model


def transcribe_file(source: Path, progress_cb: ProgressCB | None = None) -> dict:
    """Transcribe an audio/video file and return a JSON-serializable transcript.

    Blocking. Call from a thread (asyncio.to_thread) when invoked from async code.
    """
    model = _get_model()
    segments_iter, info = model.transcribe(str(source), word_timestamps=True)
    duration = float(info.duration or 0)
    segments = []
    for i, seg in enumerate(segments_iter):
        segments.append(
            {
                "id": i,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "words": [
                    {"word": w.word, "start": w.start, "end": w.end}
                    for w in (seg.words or [])
                ],
            }
        )
        if progress_cb is not None and duration > 0:
            pct = min(1.0, float(seg.end) / duration)
            progress_cb(f"Transcribing audio ({int(seg.end)}/{int(duration)}s)", pct)
    return {
        "source": source.name,
        "duration": info.duration,
        "language": info.language,
        "language_probability": info.language_probability,
        "model": settings.whisper_model,
        "compute_type": settings.whisper_compute_type,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "segments": segments,
    }


def transcript_path_for(source_name: str) -> Path:
    return settings.data_work_dir / Path(source_name).stem / "transcript.json"


def write_transcript(transcript: dict) -> Path:
    out = transcript_path_for(transcript["source"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(transcript, indent=2))
    return out
