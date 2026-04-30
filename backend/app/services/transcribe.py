"""faster-whisper transcription service.

Loads the model lazily on first call and reuses it for the lifetime of the
process. faster-whisper accepts video files directly (via PyAV), so callers
pass either audio or video paths.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from threading import Lock
from typing import Callable

from app import cuda_preload  # noqa: F401  # must precede faster_whisper import
from faster_whisper import WhisperModel

from app.config import settings

# (message, percent in [0, 1]) — same shape as the reframe progress callback,
# so the runner can reuse one helper to update job rows.
ProgressCB = Callable[[str, float], None]

_model: WhisperModel | None = None
_model_lock = Lock()


def _get_model() -> WhisperModel:
    global _model
    with _model_lock:
        if _model is None:
            _model = WhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
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
