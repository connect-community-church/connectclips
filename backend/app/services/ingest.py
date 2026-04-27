"""Sermon ingest: YouTube download via yt-dlp and direct file upload save.

Both paths land a file in sources_dir, which the transcribe pipeline can then
operate on. Filenames include a stable identifier (YouTube id, or a uuid for
uploads) so collisions are impossible across separate ingests.
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

import yt_dlp


_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm"}
_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus"}
_ALLOWED_UPLOAD_EXTS = _VIDEO_EXTS | _AUDIO_EXTS


def download_youtube(url: str, dest_dir: Path) -> Path:
    """Download a YouTube video to dest_dir at up to 1080p, return the final path.

    Caps at 1080p — final clip output is 1080x1920 anyway, so 4K source is
    wasted disk and download time. Uses --restrict-filenames for filesystem
    safety. Filename includes the YouTube id so re-downloads don't collide.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(dest_dir / "%(title)s-%(id)s.%(ext)s")
    opts = {
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "restrictfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # prepare_filename gives the path before merge; after merge it'll have
        # merge_output_format extension. requested_downloads has the actual final.
        downloads = info.get("requested_downloads") or []
        if downloads:
            return Path(downloads[0]["filepath"])
        # Fallback: derive from template
        return Path(ydl.prepare_filename(info)).with_suffix(f".{opts['merge_output_format']}")


def _sanitize_basename(name: str) -> str:
    # Strip path components, keep only the base name. Then restrict charset.
    base = Path(name).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    return base or "upload"


def save_upload(stream: BinaryIO, original_name: str, dest_dir: Path, chunk_size: int = 1024 * 1024) -> Path:
    """Stream an upload to disk, return the final path.

    Writes <stem>-<uuid8>.<ext> to avoid collisions if two volunteers upload
    files with the same name. Caller is responsible for validating the
    extension (use is_allowed_upload_ext).
    """
    safe = _sanitize_basename(original_name)
    stem = Path(safe).stem
    suffix = Path(safe).suffix.lower()
    final_name = f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / final_name
    with out.open("wb") as f:
        shutil.copyfileobj(stream, f, length=chunk_size)
    return out


def is_allowed_upload_ext(name: str) -> bool:
    return Path(name).suffix.lower() in _ALLOWED_UPLOAD_EXTS
