"""Per-clip user edits that survive page navigation.

Sits beside ``clips.json`` (Claude's output) at
``<work_dir>/<sermon_stem>/clip_overrides.json``, keyed by stringified
clip index. The clips-list endpoint merges these into each clip so
the Trim page reloads to whatever the volunteer last typed instead
of resetting to Claude's suggestion.

Override fields map 1:1 to the export-clip request body so the
frontend can persist exactly what it would later send to export.
A field set to ``null`` means "no override -- use the default" and
is dropped from the stored dict; an empty stored dict for a clip
means the clip key is removed from the file entirely.

When ``select_clips`` regenerates ``clips.json`` (volunteer rerun
asks Claude for fresh clips), the overrides become stale because
clip indices no longer line up with the new clip ranges. The
``clip_selection.write_clips`` helper deletes this file before
writing the new clips.json -- simpler than trying to detect index
collisions and forces a clean slate, which matches what a
"re-suggest clips" action implies.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings


# Override-able fields. Names match the ExportClipRequest body fields in
# routers/jobs.py so the frontend can save the same shape it would send
# to the export endpoint.
FIELDS: tuple[str, ...] = (
    "start",
    "end",
    "caption_style",
    "caption_margin_v",
    "include_hook_title",
    "identity_id",
)


def overrides_path_for(source_name: str) -> Path:
    return settings.data_work_dir / Path(source_name).stem / "clip_overrides.json"


def load_overrides(source_name: str) -> dict[str, dict[str, Any]]:
    p = overrides_path_for(source_name)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_override(source_name: str, clip_index: int, fields: dict[str, Any]) -> None:
    """Upsert override fields for a single clip.

    Drops keys not in FIELDS and keys whose value is None (so the frontend
    can clear a single field by sending it as null). If the cleaned dict
    is empty, removes the clip's entry entirely (clean state).
    """
    cleaned = {k: fields[k] for k in FIELDS if k in fields and fields[k] is not None}
    overrides = load_overrides(source_name)
    key = str(clip_index)
    if cleaned:
        overrides[key] = cleaned
    else:
        overrides.pop(key, None)
    p = overrides_path_for(source_name)
    if overrides:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(overrides, indent=2), encoding="utf-8")
    else:
        # No overrides left for any clip -- delete the file rather than
        # leave an empty {} on disk.
        p.unlink(missing_ok=True)


def delete_override(source_name: str, clip_index: int) -> bool:
    """Remove this clip's override entry. Returns True if anything changed."""
    overrides = load_overrides(source_name)
    if overrides.pop(str(clip_index), None) is None:
        return False
    p = overrides_path_for(source_name)
    if overrides:
        p.write_text(json.dumps(overrides, indent=2), encoding="utf-8")
    else:
        p.unlink(missing_ok=True)
    return True


def delete_all(source_name: str) -> None:
    """Wipe every override for this sermon (called when clips.json regenerates)."""
    overrides_path_for(source_name).unlink(missing_ok=True)


def merge_into_clips(clips: list[dict], overrides: dict[str, dict[str, Any]]) -> None:
    """In-place: stamp `user_edits` and `original` on each clip, and apply
    any start/end override into the effective clip.start / clip.end so the
    frontend's existing init code (which reads clip.start / clip.end) works
    unchanged. Caption fields aren't in Claude's clip output, so they live
    in `user_edits` only -- the frontend reads them from there.
    """
    for i, clip in enumerate(clips):
        ov = overrides.get(str(i)) or {}
        clip["original"] = {"start": clip.get("start"), "end": clip.get("end")}
        clip["user_edits"] = ov
        if ov.get("start") is not None:
            clip["start"] = ov["start"]
        if ov.get("end") is not None:
            clip["end"] = ov["end"]
