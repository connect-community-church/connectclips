"""Preload the nvidia cuBLAS / cuDNN / NVRTC shared libraries.

ctranslate2 (used by faster-whisper) does not bundle CUDA runtime libs and
expects them on the dynamic linker's path. We get them via the
nvidia-cublas-cu12 / nvidia-cudnn-cu12 / nvidia-cuda-nvrtc-cu12 pip packages,
and load them with ctypes RTLD_GLOBAL so ctranslate2's later dlopen calls
resolve. This avoids needing LD_LIBRARY_PATH in the shell.

Import this module BEFORE `faster_whisper` (or anything that loads ctranslate2).
"""

import ctypes
import sys
from pathlib import Path

_LIBS = [
    ("nvidia/cuda_runtime/lib", ["libcudart.so.12"]),
    ("nvidia/cublas/lib", ["libcublas.so.12", "libcublasLt.so.12"]),
    ("nvidia/cudnn/lib", ["libcudnn.so.9"]),
    ("nvidia/cuda_nvrtc/lib", ["libnvrtc.so.12"]),
    ("nvidia/curand/lib", ["libcurand.so.10"]),
    ("nvidia/cufft/lib", ["libcufft.so.11"]),
]


def _site_packages() -> Path | None:
    for p in sys.path:
        candidate = Path(p)
        if (candidate / "nvidia").is_dir():
            return candidate
    return None


def preload() -> None:
    # Linux-only: the libs are .so files for x86_64-linux. macOS would
    # need .dylib equivalents that CTranslate2 doesn't ship via pip
    # anyway; Windows would need .dll handling. On those platforms skip
    # preload entirely — faster-whisper falls back to CPU cleanly when
    # CUDA libs aren't reachable.
    if not sys.platform.startswith("linux"):
        return
    sp = _site_packages()
    if sp is None:
        return
    for subdir, names in _LIBS:
        for name in names:
            lib_path = sp / subdir / name
            if lib_path.exists():
                ctypes.CDLL(str(lib_path), mode=ctypes.RTLD_GLOBAL)


preload()
