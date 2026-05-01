"""Platform / hardware detection for cross-platform deployment.

Picks the right defaults at startup so the rest of the backend can stay
hardware-agnostic. Three things to detect:

  1. Which h264 encoder is available in the local ffmpeg build (NVENC on
     NVIDIA Linux/Windows, AMF on AMD Windows, QSV on Intel Windows,
     VideoToolbox on macOS, libx264 software fallback everywhere).
  2. Which ONNX Runtime execution providers are installed (CUDA on Linux
     with onnxruntime-gpu, CoreML on macOS, DirectML on Windows, CPU
     everywhere).
  3. Whether the NVIDIA driver is actually loaded — onnxruntime-gpu lists
     CUDAExecutionProvider as available even on a box with no driver.

**Lifecycle.** Detection is opt-in via :func:`initialize`, NOT at module
import time. Call it once from ``main.py``'s lifespan startup, on the
main asyncio thread, before any background workers can spawn. This
avoids a class of CUDA-context-from-the-wrong-thread issues that bit us
when the platform module was lazy-imported from inside an encode
worker thread.

**Use the module reference, not name bindings.**  Consumers should do
``from app import platform as plat`` and dereference ``plat.H264_ENCODER``
at call time. ``from app.platform import H264_ENCODER`` captures the
default value at import time and never sees the post-initialize update.
"""
from __future__ import annotations

import ctypes
import logging
import platform as _platform
import subprocess
import sys

logger = logging.getLogger(__name__)


# h264 encoder preference, best to worst. First one present in `ffmpeg
# -encoders` wins.
_H264_PREFERENCE = [
    "h264_nvenc",         # NVIDIA — best perf where available
    "h264_amf",           # AMD on Windows
    "h264_qsv",           # Intel QuickSync on Windows / Linux
    "h264_videotoolbox",  # Apple Silicon / Intel Macs
    "libx264",            # software fallback — always present in any reasonable ffmpeg build
]

# ONNX Runtime execution provider preference.
_ORT_PREFERENCE = [
    "CUDAExecutionProvider",     # NVIDIA, requires onnxruntime-gpu + driver
    "CoreMLExecutionProvider",   # macOS, requires onnxruntime built with CoreML
    "DmlExecutionProvider",      # Windows DirectML — covers AMD / Intel / NVIDIA
    "ROCMExecutionProvider",     # AMD on Linux
    "CPUExecutionProvider",      # always available
]


# Module-level constants. Default to the safe-everywhere choices so that
# any consumer importing before initialize() runs sees something
# functional (libx264 / CPU). initialize() updates these in-place once
# we know what's actually available.
H264_ENCODER: str = "libx264"
ORT_PROVIDERS: list[str] = ["CPUExecutionProvider"]
CUDA_AVAILABLE: bool = False
PLATFORM: str = _platform.system()  # "Linux" / "Darwin" / "Windows"
_INITIALIZED: bool = False


def _detect_h264_encoder() -> str:
    """Pick the best available h264 encoder. Returns 'libx264' on any error."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("ffmpeg -encoders failed (%s); defaulting to libx264", exc)
        return "libx264"
    for candidate in _H264_PREFERENCE:
        if candidate in out:
            return candidate
    return "libx264"


def _detect_ort_providers() -> list[str]:
    """Return ORT execution providers in preference order. CPU at minimum."""
    try:
        import onnxruntime as ort
    except ImportError:
        logger.warning("onnxruntime not installed; YuNet will fail to load")
        return ["CPUExecutionProvider"]
    available = set(ort.get_available_providers())
    picked = [p for p in _ORT_PREFERENCE if p in available]
    return picked or ["CPUExecutionProvider"]


def _detect_cuda_available() -> bool:
    """Try to dlopen the NVIDIA driver library. No CUDA context created.

    Lighter than importing ctranslate2 — that pulls in libtorch-style
    CUDA initialization which previously caused mysterious encode-thread
    hangs when called from inside an export. ``libcuda.so.1`` (Linux)
    or ``nvcuda.dll`` (Windows) is the actual driver entry point and a
    bare dlopen is side-effect-free.
    """
    if PLATFORM == "Linux":
        candidates = ["libcuda.so.1", "libcuda.so"]
    elif PLATFORM == "Windows":
        candidates = ["nvcuda.dll"]
    else:
        return False  # macOS doesn't have a CUDA driver
    for name in candidates:
        try:
            ctypes.CDLL(name)
            return True
        except OSError:
            continue
    return False


def initialize() -> dict:
    """Run hardware detection and update the module-level constants.

    Idempotent — repeated calls are no-ops. Returns the current summary
    so callers can log what was found at startup.
    """
    global H264_ENCODER, ORT_PROVIDERS, CUDA_AVAILABLE, _INITIALIZED
    if _INITIALIZED:
        return summary()
    H264_ENCODER = _detect_h264_encoder()
    ORT_PROVIDERS = _detect_ort_providers()
    CUDA_AVAILABLE = _detect_cuda_available()
    _INITIALIZED = True
    logger.info("platform: %s", summary())
    return summary()


# Per-encoder ffmpeg argument profiles. Only the `-c:v <enc> ...` flags
# differ across encoders; audio + container args stay shared by callers.
def encoder_args(encoder: str, *, fast: bool, bitrate_video: str) -> list[str]:
    """Return the `-c:v <enc> ...` args for a chosen encoder.

    `fast=True` is for the temp-clip extract (speed > quality); `False`
    is for the final reframe encode (quality at target bitrate).
    """
    if encoder == "h264_nvenc":
        preset = "p1" if fast else "p4"
        return ["-c:v", "h264_nvenc", "-preset", preset, "-b:v", bitrate_video]
    if encoder == "h264_amf":
        quality = "speed" if fast else "balanced"
        return ["-c:v", "h264_amf", "-quality", quality, "-b:v", bitrate_video]
    if encoder == "h264_qsv":
        preset = "veryfast" if fast else "medium"
        return ["-c:v", "h264_qsv", "-preset", preset, "-b:v", bitrate_video]
    if encoder == "h264_videotoolbox":
        # VideoToolbox: no preset knob, just bitrate. Output quality at
        # the same bitrate is roughly comparable to NVENC p4 in practice.
        return ["-c:v", "h264_videotoolbox", "-b:v", bitrate_video]
    # libx264 software fallback.
    preset = "veryfast" if fast else "medium"
    return ["-c:v", "libx264", "-preset", preset, "-b:v", bitrate_video]


def summary() -> dict:
    """For /api/health-style introspection."""
    return {
        "platform": PLATFORM,
        "h264_encoder": H264_ENCODER,
        "ort_providers": list(ORT_PROVIDERS),
        "cuda_available": CUDA_AVAILABLE,
        "initialized": _INITIALIZED,
    }
