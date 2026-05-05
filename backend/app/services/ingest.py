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
from typing import BinaryIO, Callable

import yt_dlp


_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm"}
_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus"}
_ALLOWED_UPLOAD_EXTS = _VIDEO_EXTS | _AUDIO_EXTS


# (message, percent in [0, 1]) -- same shape as the transcribe / prescan
# progress callbacks, so jobs.py can reuse one helper to forward to job state.
ProgressCB = Callable[[str, float], None]


def _yt_stream_label(info: dict) -> str:
    """Best-effort 'video' / 'audio' / 'video+audio' tag for a yt-dlp format."""
    vcodec = info.get("vcodec") or "none"
    acodec = info.get("acodec") or "none"
    if vcodec != "none" and acodec != "none":
        return "video+audio"
    if vcodec != "none":
        return "video"
    if acodec != "none":
        return "audio"
    return "stream"


def download_youtube(url: str, dest_dir: Path, progress_cb: ProgressCB | None = None) -> Path:
    """Download a YouTube video to dest_dir at up to 1080p, return the final path.

    Caps at 1080p — final clip output is 1080x1920 anyway, so 4K source is
    wasted disk and download time. Uses --restrict-filenames for filesystem
    safety. Filename includes the YouTube id so re-downloads don't collide.

    `progress_cb` (optional) gets (message, percent) updates as yt-dlp
    streams. For the 1080p+audio merge case yt-dlp downloads two separate
    streams; we report each one's per-stream percent (the bar will reset
    when the second stream starts) and emit a 'Merging...' message at the
    end. Caller is responsible for throttling state writes -- yt-dlp can
    fire the hook many times per second.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(dest_dir / "%(title)s-%(id)s.%(ext)s")

    def _hook(d: dict) -> None:
        if progress_cb is None:
            return
        status = d.get("status")
        if status == "downloading":
            done = float(d.get("downloaded_bytes") or 0)
            total = float(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
            pct = (done / total) if total > 0 else 0.0
            label = _yt_stream_label(d.get("info_dict") or {})
            done_mb = done / (1024 * 1024)
            if total > 0:
                total_mb = total / (1024 * 1024)
                msg = f"Downloading {label} ({done_mb:.1f}/{total_mb:.0f} MB)"
            else:
                msg = f"Downloading {label} ({done_mb:.1f} MB)"
            # Cap below 1.0 so 'finished' / merge can claim the last sliver.
            progress_cb(msg, min(0.99, pct))
        elif status == "finished":
            progress_cb("Merging audio + video", 0.99)

    opts = {
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "restrictfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_hook],
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
