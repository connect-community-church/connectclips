"""Per-sermon admin-editable metadata.

Sits beside ``clips.json`` and friends at
``<work_dir>/<sermon_stem>/sermon_meta.json``. Survives clips.json
regeneration (volunteer rerun of Claude clip selection) and gets cleaned up
by the existing ``delete_sermon`` flow when the work dir is removed.

Currently holds the program YouTube URL only -- the full uploaded sermon that
each clip deep-links back to so a viewer can "watch from this moment on."
Designed to grow more per-sermon fields later (recording date, preacher
name, etc.) by extending ``FIELDS``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import settings


FIELDS: tuple[str, ...] = (
    "program_video_url",
)


def _path(source_name: str) -> Path:
    return settings.data_work_dir / Path(source_name).stem / "sermon_meta.json"


def load(source_name: str) -> dict[str, str]:
    p = _path(source_name)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(data[k]) for k in FIELDS if k in data and data[k]}


def save(source_name: str, values: dict[str, Any]) -> dict[str, str]:
    """Upsert. Drops keys not in FIELDS and empty / None values. Returns the
    cleaned dict that was saved (or empty if the file was deleted)."""
    cleaned = {
        k: str(values[k]).strip()
        for k in FIELDS
        if k in values and values[k] is not None and str(values[k]).strip() != ""
    }
    p = _path(source_name)
    if cleaned:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
    else:
        p.unlink(missing_ok=True)
    return cleaned


# YouTube URL parsing -- accept the forms volunteers actually paste:
#   https://www.youtube.com/watch?v=VIDEOID
#   https://youtu.be/VIDEOID
#   https://www.youtube.com/live/VIDEOID
#   https://www.youtube.com/shorts/VIDEOID
#   https://www.youtube.com/embed/VIDEOID
# (with or without subdomain, with or without query/fragment).
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_youtube_id(url: str | None) -> str | None:
    """Return the 11-char YouTube video ID from any common URL form, or None."""
    if not url:
        return None
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if not host:
        return None
    if host == "youtu.be" or host.endswith(".youtu.be"):
        vid = u.path.lstrip("/").split("/", 1)[0]
        return vid if _YOUTUBE_ID_RE.match(vid) else None
    if host == "youtube.com" or host.endswith(".youtube.com"):
        # /watch?v=VIDEOID
        if u.path == "/watch":
            q = parse_qs(u.query)
            v = (q.get("v") or [None])[0]
            return v if v and _YOUTUBE_ID_RE.match(v) else None
        # /live/VIDEOID, /embed/VIDEOID, /shorts/VIDEOID, /v/VIDEOID
        parts = u.path.lstrip("/").split("/", 2)
        if len(parts) >= 2 and parts[0] in ("live", "embed", "shorts", "v"):
            return parts[1] if _YOUTUBE_ID_RE.match(parts[1]) else None
    return None


def deep_link(video_id: str, start_seconds: float) -> str:
    """Build a canonical ``youtu.be/<id>?t=<n>s`` deep link.

    Uses youtu.be form because it's the shortest paste-friendly URL and
    the ``?t=Ns`` parameter works identically across youtu.be and
    youtube.com/watch. ``start_seconds`` is floored to int -- YouTube only
    seeks to integer seconds anyway.
    """
    t = max(0, int(start_seconds))
    return f"https://youtu.be/{video_id}?t={t}s"
