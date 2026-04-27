from __future__ import annotations

import datetime as dt

from fastapi import APIRouter

from app.config import settings
from app.services.transcribe import transcript_path_for

router = APIRouter(prefix="/sermons", tags=["sermons"])

_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm"}
_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus"}
_ALLOWED_EXTS = _VIDEO_EXTS | _AUDIO_EXTS


@router.get("")
def list_sermons() -> list[dict]:
    src_dir = settings.data_sources_dir
    if not src_dir.exists():
        return []
    out = []
    for p in sorted(src_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in _ALLOWED_EXTS:
            continue
        stat = p.stat()
        out.append(
            {
                "name": p.name,
                "size_bytes": stat.st_size,
                "modified_at": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(),
                "transcribed": transcript_path_for(p.name).exists(),
            }
        )
    return out
