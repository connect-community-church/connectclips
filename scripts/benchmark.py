"""Auto-tune WHISPER_MODEL by timing each candidate on a 30s test clip.

Picks the largest model that transcribes at >= --threshold x realtime
(default 1.5x). Optionally writes the chosen model into backend/.env's
WHISPER_MODEL line so the next backend restart picks it up.

Cross-platform -- works on macOS / Linux / Windows -- because it just
calls into backend/app/services/transcribe.py and lets the existing
backend dispatch (whispercpp / whispercli / ctranslate2) handle the
hardware-specific path.

Usage:
    cd C:\\ConnectClips         # or ~/ConnectClips on macOS/Linux
    backend\\.venv\\Scripts\\python scripts\\benchmark.py
    backend\\.venv\\Scripts\\python scripts\\benchmark.py --write
    backend\\.venv\\Scripts\\python scripts\\benchmark.py --models large-v3 medium.en --write

Re-run after a hardware / driver change. The bundled jfk.wav clip is
downloaded once into ~/.cache/connectclips/ on first run.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import time
import urllib.request
import wave
from pathlib import Path

REPO_ROOT   = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
ENV_FILE    = BACKEND_DIR / ".env"

# 11-second JFK speech sample bundled with whisper.cpp. Public domain;
# concatenating 3x gives a 33s clip that's long enough for stable RTR
# measurements without making the bench take forever.
JFK_URL = "https://github.com/ggml-org/whisper.cpp/raw/master/samples/jfk.wav"


def ensure_fixture() -> Path:
    """Download + concat jfk.wav 3x -> ~/.cache/connectclips/bench_33s.wav."""
    cache_dir = Path.home() / ".cache" / "connectclips"
    fixture   = cache_dir / "bench_33s.wav"
    if fixture.is_file():
        return fixture
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading jfk.wav -> {fixture}", flush=True)
    src = cache_dir / "_jfk_src.wav"
    with urllib.request.urlopen(JFK_URL) as r, src.open("wb") as f:
        f.write(r.read())
    with wave.open(str(src), "rb") as rr:
        params = rr.getparams()
        frames = rr.readframes(rr.getnframes())
    with wave.open(str(fixture), "wb") as ww:
        ww.setparams(params)
        for _ in range(3):
            ww.writeframes(frames)
    src.unlink()
    return fixture


def reload_backend() -> None:
    """Reload app.config + app.services.transcribe so a new WHISPER_MODEL
    in os.environ wins over the cached Settings/model objects."""
    for name in ("app.services.transcribe", "app.config"):
        mod = sys.modules.get(name)
        if mod is not None:
            importlib.reload(mod)


def bench_one(model: str, fixture: Path) -> tuple[float, float] | None:
    """Run one transcribe + return (wall_secs, RTR). None if model missing."""
    os.environ["WHISPER_MODEL"] = model
    reload_backend()
    from app.services.transcribe import transcribe_file  # type: ignore[import-not-found]
    try:
        # Warm-up pays first-touch model-load + (for whispercli) Vulkan
        # pipeline compile cost. Steady-state numbers are what we want.
        transcribe_file(fixture)
        t0 = time.perf_counter()
        result = transcribe_file(fixture)
        elapsed = time.perf_counter() - t0
    except FileNotFoundError as e:
        print(f"  skip: {e}", flush=True)
        return None
    except Exception as e:
        print(f"  ERROR: {e!r}", flush=True)
        return None
    audio = float(result.get("duration") or 0) or 33.0
    rtr   = audio / elapsed if elapsed > 0 else 0.0
    return elapsed, rtr


def update_env_model(env_path: Path, model: str) -> None:
    """Replace WHISPER_MODEL=... in .env, leaving the rest alone."""
    if not env_path.is_file():
        print(f"  --write requested but {env_path} doesn't exist; skipping", flush=True)
        return
    text = env_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    found = False
    for i, ln in enumerate(lines):
        if ln.startswith("WHISPER_MODEL="):
            lines[i] = f"WHISPER_MODEL={model}"
            found = True
            break
    if not found:
        lines.append(f"WHISPER_MODEL={model}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote {env_path}: WHISPER_MODEL={model}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Pick the best Whisper model the local hardware can run in real time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--threshold", type=float, default=1.5,
                    help="Minimum acceptable RTR (audio_seconds / transcribe_seconds). Default 1.5")
    ap.add_argument("--models", nargs="+",
                    default=["large-v3", "medium.en", "small.en"],
                    help="Models to try, largest first. Default: large-v3 medium.en small.en")
    ap.add_argument("--write", action="store_true",
                    help="Update WHISPER_MODEL in backend/.env with the chosen model")
    args = ap.parse_args()

    if not ENV_FILE.is_file():
        print(f"backend/.env not found at {ENV_FILE} -- run install-*.sh / install-windows.ps1 first.",
              file=sys.stderr)
        sys.exit(2)

    sys.path.insert(0, str(BACKEND_DIR))

    fixture = ensure_fixture()
    print(f"audio:     {fixture} (~33s)")
    print(f"threshold: RTR >= {args.threshold}x  (60-min sermon transcribes in <{60/args.threshold:.0f} min)")
    print(f"models:    {' -> '.join(args.models)}")
    print(flush=True)

    chosen: str | None = None
    for model in args.models:
        print(f"=== {model} ===", flush=True)
        r = bench_one(model, fixture)
        if r is None:
            continue
        elapsed, rtr = r
        passes = rtr >= args.threshold
        tag = "PICK" if passes and chosen is None else " -- "
        print(f"  [{tag}] wall {elapsed:.1f}s   RTR {rtr:.2f}x", flush=True)
        if passes and chosen is None:
            chosen = model

    print(flush=True)
    if chosen is None:
        chosen = args.models[-1]
        print(f"No model cleared {args.threshold}x. Falling back to {chosen} (smallest tested).")
    else:
        print(f"Chose: {chosen}")

    if args.write:
        update_env_model(ENV_FILE, chosen)
        print("Restart the backend (NSSM / launchd / systemd) to pick up the new model.")
    else:
        print("Re-run with --write to persist this to backend/.env.")


if __name__ == "__main__":
    main()
