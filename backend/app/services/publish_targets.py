"""Per-deployment publish target IDs (which YouTube channel, which Facebook Page).

The Publish view's deep-links to YouTube Studio and Meta Business Suite work
better when they're scoped to a specific channel / Page than when they're
generic upload-page links -- generic links rely on whatever account the
volunteer happens to be signed into in their browser, which has burned
churches that volunteer-cross-post to personal channels by accident.

These IDs are admin-configurable runtime settings (not env vars) so a
non-technical admin can update them from the UI when a Page is renamed or a
new channel is added without SSH + restart. Stored in a small JSON file
under the data work dir so it travels with data backups.

TikTok and Instagram don't expose channel-specific upload URLs that work
from a browser session -- those buttons stay generic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings


# Field names match the JSON we expose at /api/publish-targets and the form
# fields in the Settings view; keep these in sync if you add a platform.
FIELDS: tuple[str, ...] = (
    "youtube_channel_id",
    "facebook_page_id",
)


def _path() -> Path:
    return settings.data_work_dir / "_settings" / "publish_targets.json"


def load() -> dict[str, str]:
    p = _path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(data[k]) for k in FIELDS if k in data and data[k]}


def save(values: dict[str, Any]) -> dict[str, str]:
    """Upsert. Drops keys not in FIELDS and empty / None values, so the file
    only carries explicitly-set IDs. Returns the cleaned dict that was saved."""
    cleaned = {
        k: str(values[k]).strip()
        for k in FIELDS
        if k in values and values[k] is not None and str(values[k]).strip() != ""
    }
    p = _path()
    if cleaned:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
    else:
        p.unlink(missing_ok=True)
    return cleaned
