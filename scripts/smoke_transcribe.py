"""Smoke test for the GPU → CUDA → faster-whisper path.

Usage:
    cd backend && .venv/bin/python ../scripts/smoke_transcribe.py [audio_file]

If no audio file is given, downloads a short public JFK clip into the
configured sources dir and transcribes that. Prints the first few word-level
timestamps so we can confirm word_timestamps=True works on this box.

Use a smaller model first (set WHISPER_MODEL=tiny in .env) if you want to
validate the path without the ~3 GB large-v3 download.
"""

import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import cuda_preload  # noqa: F401, E402  # must precede faster_whisper import
from app.config import settings  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

JFK_URL = "https://github.com/openai/whisper/raw/main/tests/jfk.flac"


def ensure_audio(path_arg: str | None) -> Path:
    if path_arg:
        p = Path(path_arg)
        if not p.exists():
            sys.exit(f"audio file not found: {p}")
        return p
    sample = settings.data_sources_dir / "test_jfk.flac"
    if not sample.exists():
        sample.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading sample → {sample}")
        urllib.request.urlretrieve(JFK_URL, sample)
    return sample


def main() -> None:
    audio = ensure_audio(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"audio:   {audio}")
    print(f"model:   {settings.whisper_model} ({settings.whisper_compute_type} on {settings.whisper_device})")

    t0 = time.perf_counter()
    model = WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    print(f"loaded model in {time.perf_counter() - t0:.1f}s")

    t1 = time.perf_counter()
    segments, info = model.transcribe(str(audio), word_timestamps=True)
    segments = list(segments)
    elapsed = time.perf_counter() - t1
    audio_dur = info.duration
    print(f"transcribed {audio_dur:.1f}s of audio in {elapsed:.1f}s ({audio_dur / elapsed:.1f}x realtime)")
    print(f"language: {info.language} (p={info.language_probability:.2f})")

    print("\nfirst 12 words with timestamps:")
    n = 0
    for seg in segments:
        for w in seg.words or []:
            print(f"  [{w.start:6.2f} → {w.end:6.2f}] {w.word!r}")
            n += 1
            if n >= 12:
                return


if __name__ == "__main__":
    main()
