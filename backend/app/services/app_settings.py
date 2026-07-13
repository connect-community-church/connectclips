"""Admin-configurable runtime settings for the clip-selection step.

Tuned per-deployment from the Settings UI (not env vars) so a non-technical
admin can adjust clip-selection behaviour without SSH + restart:

- ``clip_thinking_effort`` -- how hard Claude reasons when picking clips
  (low / medium / high). The quality-vs-cost dial.
- ``clip_max_output_tokens`` -- the ``max_tokens`` ceiling for the pick-clips
  call. Covers thinking + JSON output combined; a generous default keeps the
  small (~2-4K token) clip JSON from being starved when adaptive thinking runs
  long. This is a SAFETY ceiling, not a quality dial -- raising it doesn't make
  clips better, it just prevents the truncation that stopped the pipeline when
  the old hardcoded 12000 was exceeded on a long, dense sermon.
- ``num_clips_min`` / ``num_clips_max`` -- how many candidate clips the auto
  pipeline requests. A manual "Pick clips" run can still override per-run.

Stored as JSON under the data work dir so it travels with data backups,
mirroring services/publish_targets.py. All reads go through ``load()``, which
merges stored values over ``DEFAULTS`` and validates every field -- a corrupt
or partial file can never take clip-picking offline.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings


VALID_EFFORTS: tuple[str, ...] = ("low", "medium", "high")

# Defaults chosen so the pipeline is robust out of the box: 24000 gives
# adaptive thinking ample room above the ~2-4K tokens the clip JSON needs, so
# a long sermon can't truncate the output the way it did at the old 12000.
# The clip range mirrors the previous auto-pipeline constants (7..10).
DEFAULTS: dict[str, Any] = {
    "clip_thinking_effort": "medium",
    "clip_max_output_tokens": 24000,
    "num_clips_min": 7,
    "num_clips_max": 10,
}

# Clamp ranges so a fat-fingered UI value can't wedge the pipeline.
MIN_OUTPUT_TOKENS = 4000
MAX_OUTPUT_TOKENS = 64000
MAX_CLIPS = 20


def _path() -> Path:
    return settings.data_work_dir / "_settings" / "app_settings.json"


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    """Merge raw values over DEFAULTS, validating each field. Invalid or
    missing values fall back to the default rather than raising."""
    out = dict(DEFAULTS)

    effort = str(raw.get("clip_thinking_effort", "")).lower().strip()
    if effort in VALID_EFFORTS:
        out["clip_thinking_effort"] = effort

    try:
        out["clip_max_output_tokens"] = max(
            MIN_OUTPUT_TOKENS, min(MAX_OUTPUT_TOKENS, int(raw["clip_max_output_tokens"]))
        )
    except (KeyError, TypeError, ValueError):
        pass

    try:
        out["num_clips_min"] = max(1, min(MAX_CLIPS, int(raw["num_clips_min"])))
    except (KeyError, TypeError, ValueError):
        pass

    try:
        out["num_clips_max"] = max(1, min(MAX_CLIPS, int(raw["num_clips_max"])))
    except (KeyError, TypeError, ValueError):
        pass

    # Keep the range coherent regardless of how the two fields were set.
    if out["num_clips_max"] < out["num_clips_min"]:
        out["num_clips_max"] = out["num_clips_min"]

    return out


def load() -> dict[str, Any]:
    """Effective settings: stored values merged over defaults, validated."""
    p = _path()
    if not p.is_file():
        return dict(DEFAULTS)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)
    if not isinstance(data, dict):
        return dict(DEFAULTS)
    return _coerce(data)


def save(values: dict[str, Any]) -> dict[str, Any]:
    """Validate + persist. Only known fields with non-None values are applied
    over the current effective settings, so a partial PUT patches rather than
    clobbers. Returns the full effective settings after the write."""
    merged = load()
    for k in DEFAULTS:
        if values.get(k) is not None:
            merged[k] = values[k]
    coerced = _coerce(merged)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(coerced, indent=2), encoding="utf-8")
    return coerced
