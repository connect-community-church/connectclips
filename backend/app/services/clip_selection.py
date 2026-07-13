"""Clip selection service.

Sends a sermon transcript to Claude (Sonnet 4.6) and asks for N candidate
short-form clips. Returns start/end/title/rationale for each clip.

Only segment-level transcript text is sent — word-level timestamps stay on
disk and are used later for caption rendering. See CLAUDE.md.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from pathlib import Path

from anthropic import Anthropic
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.services import app_settings

logger = logging.getLogger(__name__)

# Absolute upper bound for the auto-retry so a misconfigured ceiling can't
# balloon a single call's cost without limit. Matches the settings clamp.
_HARD_TOKEN_CAP = 64000


class ClipCandidate(BaseModel):
    start: float
    end: float
    title: str
    rationale: str
    hook_score: int = Field(ge=0, le=100)
    hook_rationale: str


class ClipSelection(BaseModel):
    clips: list[ClipCandidate]


# Cleanup applied to every Claude-returned clip so we don't ship clips that
# cut a word in half or end the moment the speaker stops.
END_PADDING_SECONDS = 0.35  # breath / silence after the last word
START_LEAD_SECONDS = 0.05   # tiny lead-in so the first word doesn't pop

def _flat_words(transcript: dict) -> list[dict]:
    out: list[dict] = []
    for seg in transcript.get("segments", []):
        for w in seg.get("words", []):
            if w.get("end", 0) > w.get("start", 0):
                out.append(w)
    out.sort(key=lambda w: w["start"])
    return out


def _snap_to_word_boundaries(clip: dict, words: list[dict], duration: float) -> dict:
    """Adjust clip start/end so they don't slice through a word.

    - If start falls *inside* a word, snap it to that word's start (don't cut
      the first word in half).
    - If end falls *inside* a word, snap it to that word's end (capture the
      whole final word).
    - Add a small lead-in before start and a longer breath-pad after end.
    - Clamp to [0, duration].
    """
    s = float(clip["start"])
    e = float(clip["end"])
    for w in words:
        ws, we = float(w["start"]), float(w["end"])
        if ws < s < we:
            s = ws
        if ws < e < we:
            e = we
        if ws > e:
            break  # words are sorted; no point scanning further
    s = max(0.0, s - START_LEAD_SECONDS)
    e = min(duration, e + END_PADDING_SECONDS)
    return {**clip, "start": round(s, 2), "end": round(e, 2)}


_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


SYSTEM_PROMPT = """You are an editor for a church's social media team. The clips you pick are for OUTREACH: they will be seen by strangers scrolling TikTok / Reels / Shorts who have never been to this church and don't know the speaker. Your job is to find moments from the sermon that will stop the scroll and make a cold viewer curious enough to keep watching.

A great clip:
- Hooks in the first 3 seconds — striking claim, vivid image, sharp question, contrarian statement, or compelling story opener. NOT a slow build-up.
- Is self-contained — the payoff is in the clip itself; no prior context needed.
- Lands on a complete thought, not mid-sentence.
- Runs 30 to 90 seconds.

Avoid:
- Long Bible reading without commentary.
- Setup or transitional material that needs context to land.
- Stories whose punchline only makes sense after several minutes.
- Moments that require sermon context to resonate.

The transcript is segment-level: each line is one chunk of speech with a start and end time in seconds, formatted as `[start-end] text`. When you pick a clip, snap start and end to segment boundaries from the transcript so the clip starts and ends on a natural pause.

For each clip return:
- start: clip start time in seconds (a segment boundary)
- end: clip end time in seconds (a segment boundary, 30–90 seconds after start)
- title: a punchy 4–8 word hook for the social caption (will also be burned on-screen as the opening overlay)
- rationale: one sentence on why this moment is editorially strong overall
- hook_score: integer 0–100, predicting how likely a cold scroller is to keep watching past the first 3 seconds
- hook_rationale: one sentence describing what the FIRST 3 SECONDS of the clip literally say or do, and why that grabs attention (or where it falls short)

Hook score rubric — use the full range, calibrate carefully:
- 90–100: extraordinary opening; immediate striking statement that works for any audience. Reserve for genuinely standout hooks.
- 75–89: strong hook with clear payoff, clearly above average.
- 60–74: solid clip but the opening is conventional or takes a beat to land.
- 40–59: works as a clip but the first 3 seconds are soft.
- Below 40: don't recommend; opening is a slow build or requires context.

Most clips should fall in 60–85. Don't inflate scores — a clip the volunteer skips because the hook is weak should score below 60.
"""


def _segment_view(transcript: dict) -> str:
    return "\n".join(
        f"[{s['start']:.2f}-{s['end']:.2f}] {s['text'].strip()}"
        for s in transcript["segments"]
    )


def select_clips(
    transcript_path: Path,
    num_clips_min: int = 3,
    num_clips_max: int = 8,
) -> dict:
    transcript = json.loads(transcript_path.read_text())
    segments_text = _segment_view(transcript)
    duration_min = transcript["duration"] / 60

    user_text = (
        f"Sermon: {transcript['source']}\n"
        f"Duration: {duration_min:.1f} min\n"
        f"Segments: {len(transcript['segments'])}\n\n"
        f"Pick {num_clips_min} to {num_clips_max} clip candidates from this transcript.\n\n"
        f"--- TRANSCRIPT ---\n{segments_text}\n--- END TRANSCRIPT ---"
    )

    client = _get_client()

    # Runtime, admin-tunable knobs (Settings UI → app_settings.json):
    #   effort     -- the quality dial (low/medium/high) for adaptive thinking.
    #   max_tokens -- SAFETY ceiling covering thinking + JSON output combined.
    # Thinking is the variable cost here (the clip JSON is only ~2-4K tokens);
    # a generous default ceiling keeps a long, dense sermon from truncating the
    # output. See app_settings.py for the rationale and defaults.
    cfg = app_settings.load()
    effort = cfg["clip_thinking_effort"]
    base_tokens = int(cfg["clip_max_output_tokens"])

    # Self-healing: if thinking overruns the ceiling, the JSON is cut off
    # mid-string and the SDK either raises a JSON ValidationError while parsing
    # or returns parsed_output=None with stop_reason="max_tokens". Both mean
    # "truncated" — retry once at double the ceiling before giving up.
    attempts = [base_tokens]
    if base_tokens * 2 <= _HARD_TOKEN_CAP and base_tokens < _HARD_TOKEN_CAP:
        attempts.append(min(base_tokens * 2, _HARD_TOKEN_CAP))

    response = None
    selection: ClipSelection | None = None
    last_reason = ""
    for i, budget in enumerate(attempts):
        more = i + 1 < len(attempts)
        # The SDK forces streaming for non-streaming calls it *estimates* could
        # exceed 10 min (roughly max_tokens ≳ 21K, via a very conservative
        # 128K-tokens/hour assumption). Our output is small and thinking-bound,
        # so it finishes far faster than that estimate — pass an explicit
        # timeout to opt out of the guard while still bounding the wait. Scale
        # it with the budget and cap at 30 min so a retry at a high ceiling
        # still has room.
        req_timeout = min(1800.0, 180.0 + budget / 128_000 * 3600)
        try:
            # cache_control on the last user content block caches the full prefix
            # (system + transcript). Min cacheable prefix on Sonnet 4.6 is 2048
            # tokens — the transcript alone clears that comfortably.
            response = client.messages.parse(
                model=settings.claude_model,
                max_tokens=budget,
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                timeout=req_timeout,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": [{
                        "type": "text",
                        "text": user_text,
                        "cache_control": {"type": "ephemeral"},
                    }],
                }],
                output_format=ClipSelection,
            )
        except ValidationError:
            # Truncated JSON → unparseable. Retry larger if we can.
            last_reason = f"unparseable JSON (truncated) at max_tokens={budget}"
            logger.warning(
                "Clip selection %s. %s",
                last_reason, "Retrying larger…" if more else "Out of retries.",
            )
            continue

        selection = response.parsed_output
        if selection is not None:
            break  # success

        # Returned, but nothing parseable — almost always max_tokens truncation.
        last_reason = f"no parseable output (stop_reason={response.stop_reason}) at max_tokens={budget}"
        logger.warning(
            "Clip selection %s. %s",
            last_reason, "Retrying larger…" if more else "Out of retries.",
        )

    if selection is None:
        raise RuntimeError(
            "Claude could not return a complete clip list — "
            f"{last_reason}. The sermon may be unusually long/dense. Raise "
            "'Max output tokens' (or lower 'Thinking effort') in Settings and "
            "re-run Pick clips."
        )
    raw_clips = [c.model_dump() for c in selection.clips]
    words = _flat_words(transcript)
    duration = float(transcript.get("duration", 0)) or float("inf")
    clips = [_snap_to_word_boundaries(c, words, duration) for c in raw_clips]
    return {
        "source": transcript["source"],
        "model": response.model,
        # clips_version stamps this generation of clips.json so each export job
        # can record which "version" it was built against. When clips.json is
        # regenerated (e.g. volunteer re-runs Pick clips with a different range),
        # the new version differs and previously-exported MP4s show as stale in
        # the UI rather than being silently misrepresented.
        "clips_version": uuid.uuid4().hex,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_creation_input_tokens": response.usage.cache_creation_input_tokens,
            "cache_read_input_tokens": response.usage.cache_read_input_tokens,
        },
        "clips": clips,
    }


def clips_path_for(source_name: str) -> Path:
    return settings.data_work_dir / Path(source_name).stem / "clips.json"


def write_clips(result: dict) -> Path:
    out = clips_path_for(result["source"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    # Wipe any per-clip user edits left over from a previous Claude
    # generation -- clip indices in the new clips.json don't line up
    # with what the volunteer was editing, so the cleanest semantics
    # for "re-suggest clips" is "start fresh".
    from app.services import clip_overrides
    clip_overrides.delete_all(result["source"])
    return out
