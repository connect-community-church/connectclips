"""Anthropic API usage, cost tracking, and estimated balance.

Each clip-selection run persists the Anthropic API ``usage`` block (input /
output / cache-write / cache-read tokens) plus the model name in the sermon's
``clips.json``. This router scans those files and aggregates the numbers
into a single per-sermon table plus totals, with an estimated USD cost
computed locally from hardcoded model rate cards.

Anthropic doesn't expose a "current balance" endpoint, so balance is
estimated from manually-recorded top-ups (admin logs each top-up here)
minus the sum of local cost estimates incurred since the first recorded
top-up. If the admin forgets to log a top-up, the balance trends low,
which is the right failure mode (encourages topping up rather than
silently overdrawing).

Local-only: doesn't talk to the Anthropic Admin API. The numbers reflect
what *ConnectClips* spent on this API key — any other usage on the same
key (one-off scripts, other apps) is not included.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import db
from app.config import settings
from app.routers.auth import require_admin

router = APIRouter(
    prefix="/usage",
    tags=["usage"],
    dependencies=[Depends(require_admin)],
)


# Anthropic public pricing as of April 2026, USD per token.
# Source: https://docs.anthropic.com/en/docs/about-claude/pricing
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

# When estimated balance drops below this, the UI shows it in red.
LOW_BALANCE_THRESHOLD_USD = 1.0


def _cost_for(model: str | None, usage: dict[str, Any]) -> float:
    rates = RATES_PER_TOKEN.get(model or "", RATES_PER_TOKEN[_FALLBACK_MODEL])
    return (
        int(usage.get("input_tokens") or 0) * rates["input"]
        + int(usage.get("output_tokens") or 0) * rates["output"]
        + int(usage.get("cache_creation_input_tokens") or 0) * rates["cache_write"]
        + int(usage.get("cache_read_input_tokens") or 0) * rates["cache_read"]
    )


def _list_topups() -> list[dict]:
    """All top-ups, newest first."""
    with db.cursor() as cur:
        rows = cur.execute(
            "SELECT id, amount_usd, note, created_at FROM balance_topups "
            "ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [
        {"id": r["id"], "amount_usd": r["amount_usd"], "note": r["note"], "created_at": r["created_at"]}
        for r in rows
    ]


def _scan_clips() -> list[dict]:
    """Read every sermon's clips.json and pull out the Anthropic usage block."""
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
    return rows


def _compute_balance(rows: list[dict], topups: list[dict]) -> dict | None:
    """Estimated balance = sum(topups) − sum(costs since first top-up).

    Returns None if no top-ups have been recorded — the UI falls back to
    a "log your first top-up to enable balance tracking" prompt instead
    of showing a meaningless number.
    """
    if not topups:
        return None
    first_topup_at = min(t["created_at"] for t in topups)
    total_topups = sum(t["amount_usd"] for t in topups)
    total_spent_since = sum(
        r["estimated_cost_usd"] for r in rows
        if (r["created_at"] or "") >= first_topup_at
    )
    estimated = total_topups - total_spent_since
    return {
        "total_topups_usd": round(total_topups, 4),
        "total_spent_since_first_topup_usd": round(total_spent_since, 4),
        "estimated_balance_usd": round(estimated, 4),
        "low_threshold_usd": LOW_BALANCE_THRESHOLD_USD,
        "is_low": estimated < LOW_BALANCE_THRESHOLD_USD,
        "first_topup_at": first_topup_at,
        "topups": topups,
    }


@router.get("")
def get_usage() -> dict:
    """Per-sermon Claude API usage rows + aggregated totals + estimated balance."""
    rows = _scan_clips()
    summary = {
        "n_clip_selections": len(rows),
        "total_input_tokens": sum(r["input_tokens"] for r in rows),
        "total_output_tokens": sum(r["output_tokens"] for r in rows),
        "total_cache_creation_input_tokens": sum(r["cache_creation_input_tokens"] for r in rows),
        "total_cache_read_input_tokens": sum(r["cache_read_input_tokens"] for r in rows),
        "total_estimated_cost_usd": sum(r["estimated_cost_usd"] for r in rows),
    }
    balance = _compute_balance(rows, _list_topups())
    return {"rows": rows, "summary": summary, "balance": balance}


# ---------- Top-up CRUD ----------------------------------------------------

class TopupCreate(BaseModel):
    amount_usd: float = Field(gt=0, description="Top-up amount in USD; must be positive")
    note: str | None = None
    # Optional — defaults to "now" if not provided. Useful for backfilling
    # historical top-ups when first wiring up balance tracking.
    created_at: str | None = None


@router.post("/topups", status_code=201)
def add_topup(body: TopupCreate) -> dict:
    created_at = body.created_at or dt.datetime.now(dt.timezone.utc).isoformat()
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO balance_topups (amount_usd, note, created_at) VALUES (?, ?, ?)",
            (body.amount_usd, body.note, created_at),
        )
        topup_id = cur.lastrowid
    return {
        "id": topup_id,
        "amount_usd": body.amount_usd,
        "note": body.note,
        "created_at": created_at,
    }


@router.delete("/topups/{topup_id}")
def delete_topup(topup_id: int) -> dict:
    with db.cursor() as cur:
        row = cur.execute(
            "SELECT id FROM balance_topups WHERE id = ?", (topup_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "topup not found")
        cur.execute("DELETE FROM balance_topups WHERE id = ?", (topup_id,))
    return {"id": topup_id, "deleted": True}
