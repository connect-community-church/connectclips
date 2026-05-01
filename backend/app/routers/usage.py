"""Anthropic API usage and cost tracking.

Each clip-selection run persists the Anthropic API ``usage`` block (input /
output / cache-write / cache-read tokens) plus the model name in the sermon's
``clips.json``. This router scans those files and aggregates the numbers
into a single per-sermon table plus totals, with an estimated USD cost
computed locally from hardcoded model rate cards.

Local-only: doesn't talk to the Anthropic Admin API. The numbers reflect
what *ConnectClips* spent on this API key — any other usage on the same
key (one-off scripts, other apps) is not included.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from app.config import settings
from app.routers.auth import require_admin

router = APIRouter(
    prefix="/usage",
    tags=["usage"],
    dependencies=[Depends(require_admin)],
)


# Anthropic public pricing as of April 2026, USD per token.
# Source: https://docs.anthropic.com/en/docs/about-claude/pricing
# When Anthropic publishes new rates, update these constants. The
# fallback handles models we don't have specific rates for — uses
# Sonnet 4.6 as the most-likely-current-model approximation.
RATES_PER_TOKEN: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input":       3.0  / 1_000_000,
        "output":     15.0  / 1_000_000,
        "cache_write": 3.75 / 1_000_000,
        "cache_read":  0.30 / 1_000_000,
    },
    "claude-opus-4-7": {
        "input":      15.0  / 1_000_000,
        "output":     75.0  / 1_000_000,
        "cache_write":18.75 / 1_000_000,
        "cache_read":  1.50 / 1_000_000,
    },
    "claude-haiku-4-5": {
        "input":       1.0  / 1_000_000,
        "output":      5.0  / 1_000_000,
        "cache_write": 1.25 / 1_000_000,
        "cache_read":  0.10 / 1_000_000,
    },
}
_FALLBACK_MODEL = "claude-sonnet-4-6"


def _cost_for(model: str | None, usage: dict[str, Any]) -> float:
    rates = RATES_PER_TOKEN.get(model or "", RATES_PER_TOKEN[_FALLBACK_MODEL])
    return (
        int(usage.get("input_tokens") or 0) * rates["input"]
        + int(usage.get("output_tokens") or 0) * rates["output"]
        + int(usage.get("cache_creation_input_tokens") or 0) * rates["cache_write"]
        + int(usage.get("cache_read_input_tokens") or 0) * rates["cache_read"]
    )


@router.get("")
def get_usage() -> dict:
    """Per-sermon Claude API usage rows + aggregated totals.

    Reads each sermon's ``clips.json``, pulls out the ``usage`` block
    (saved by ``services/clip_selection.write_clips``), and computes
    estimated cost using the rate card above. Sorted newest first.
    """
    rows: list[dict] = []
    for clips_file in settings.data_work_dir.glob("*/clips.json"):
        try:
            data = json.loads(clips_file.read_text())
        except Exception:
            continue
        usage = data.get("usage") or {}
        if not usage:
            continue
        model = data.get("model")
        rows.append({
            "source": data.get("source") or clips_file.parent.name,
            "model": model,
            "created_at": data.get("created_at"),
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
            "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
            "estimated_cost_usd": _cost_for(model, usage),
        })

    rows.sort(key=lambda r: r["created_at"] or "", reverse=True)

    summary = {
        "n_clip_selections": len(rows),
        "total_input_tokens": sum(r["input_tokens"] for r in rows),
        "total_output_tokens": sum(r["output_tokens"] for r in rows),
        "total_cache_creation_input_tokens": sum(r["cache_creation_input_tokens"] for r in rows),
        "total_cache_read_input_tokens": sum(r["cache_read_input_tokens"] for r in rows),
        "total_estimated_cost_usd": sum(r["estimated_cost_usd"] for r in rows),
    }
    return {"rows": rows, "summary": summary}
