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


# The clip-selection system prompt is assembled from three parts so the two
# strategies below can share the parts that must never drift:
#   _INTRO      -- who this is for (outreach to cold scrollers). Shared.
#   <guidance>  -- what makes a clip good. This is the ONLY part that differs
#                  between "classic" and "performance".
#   _MECHANICS  -- transcript format, the exact output fields, and the
#                  hook-score rubric. Shared, so both strategies emit the same
#                  ClipCandidate schema and score the same way.
_INTRO = """You are an editor for a church's social media team. The clips you pick are for OUTREACH: they will be seen by strangers scrolling TikTok / Reels / Shorts who have never been to this church and don't know the speaker. Your job is to find moments from the sermon that will stop the scroll and make a cold viewer curious enough to keep watching."""

_CLASSIC_GUIDANCE = """A great clip:
- Hooks in the first 3 seconds — striking claim, vivid image, sharp question, contrarian statement, or compelling story opener. NOT a slow build-up.
- Is self-contained — the payoff is in the clip itself; no prior context needed.
- Lands on a complete thought, not mid-sentence.
- Runs 30 to 90 seconds.

Avoid:
- Long Bible reading without commentary.
- Setup or transitional material that needs context to land.
- Stories whose punchline only makes sense after several minutes.
- Moments that require sermon context to resonate."""

# Reporting-tuned guidance. Based on analysis of which uploaded Shorts actually
# performed: clips that create immediate human tension out-perform safe
# teaching summaries. Biases toward the proven patterns without chasing
# outrage, and asks for a deliberately balanced mix so every clip doesn't feel
# the same.
_PERFORMANCE_GUIDANCE = """A great clip hooks in the first 3 seconds — the tension itself is in those seconds, not a set-up for it — is self-contained (payoff needs no prior context), lands on a complete thought, and runs 30 to 90 seconds.

Past performance guidance:
ConnectClips reporting shows stronger performance from clips that create immediate human tension. Prefer moments that fit one or more of these patterns:
- A bold or contrarian — but truthful — claim that makes a viewer think, "Wait, what?"
- Raw honesty about sin, suffering, doubt, prayer, family, marriage, money, church hurt, fear, guilt, or spiritual exhaustion.
- A direct personal question that names a hidden struggle.
- A vivid story or image with conflict visible in the first few seconds.
- A practical relationship / family / work / life application of doctrine.
- A tension-to-grace arc: conviction, discomfort, or fear that resolves in gospel hope.

Do not chase outrage or cheap controversy. The tone must remain pastoral, truthful, and hopeful. But when choosing between a safe teaching summary and a sharper self-contained moment with emotional stakes, prefer the sharper moment.

Score hooks HIGHER when:
- the first 3 seconds contain the actual tension, not just set-up
- the clip can be understood by a non-church viewer
- the language is concrete, personal, and emotionally recognizable
- the moment would still be interesting if the viewer knows nothing about the sermon series

Score hooks LOWER when:
- the opening sounds like mid-sermon connective tissue (starts with "and", "now", "so", or another mid-thought connector)
- the clip mostly explains a Bible passage without a felt human problem
- the payoff requires prior context
- the title is stronger than the spoken opening
- it is a safe devotional summary, or theologically correct but emotionally flat
- there is a long explanation before the tension arrives

Aim for a BALANCED set rather than variations on one moment. When deciding which candidates to include, prioritize in this order and scale the proportions to the number of clips requested:
1. Proven-pattern clips — contrarian, raw, personal, urgent, or practical. These should be the largest share.
2. A vivid story / image clip, if a strong one is present.
3. A theologically rich clip ONLY if it carries a sharp human hook.
4. One experimental clip — unusually memorable even if a little risky.
(For example, for ~5 clips that's roughly 2 proven-pattern, 1 story, 1 rich-with-hook, 1 experimental.)"""

_MECHANICS = """The transcript is segment-level: each line is one chunk of speech with a start and end time in seconds, formatted as `[start-end] text`. When you pick a clip, snap start and end to segment boundaries from the transcript so the clip starts and ends on a natural pause.

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

CLASSIC_SYSTEM_PROMPT = f"{_INTRO}\n\n{_CLASSIC_GUIDANCE}\n\n{_MECHANICS}"
PERFORMANCE_SYSTEM_PROMPT = f"{_INTRO}\n\n{_PERFORMANCE_GUIDANCE}\n\n{_MECHANICS}"

_DEEPER_GUIDANCE = """Deeper Clips mode is for one midweek bridge clip, not a normal Short. These clips are for viewers who were encouraged by a Short and may want a fuller taste of the message before watching the full sermon. Choose from the full sermon transcript, not from previously selected Shorts.

A great Deeper Clip:
- Runs 2:30 to 5:00.
- Has a clear beginning, middle, and end.
- Develops one meaningful sermon idea with enough context to stand alone.
- Is understandable to someone who was not in the room and has not watched the sermon.
- Starts with a human problem, question, tension, or image in the first few seconds.
- Ends with hope, Jesus, or a practical next step rather than stopping mid-thought.

Avoid:
- Simply stitching several Short-style moments together.
- Long Bible reading without enough explanation.
- Sections that depend on earlier sermon context.
- Pure setup that does not land before the clip ends.
- Inside-baseball church announcements or transitions.

The goal is not maximum scroll-stopping speed. The goal is a deeper, watchable midweek excerpt that helps someone take one step further into the message."""

_DEEPER_MECHANICS = """The transcript is segment-level: each line is one chunk of speech with a start and end time in seconds, formatted as `[start-end] text`. When you pick a Deeper Clip, snap start and end to segment boundaries from the transcript so the clip starts and ends on a natural pause.

For each clip return:
- start: clip start time in seconds (a segment boundary)
- end: clip end time in seconds (a segment boundary, 2:30 to 5:00 after start)
- title: a clear 5–10 word title for the midweek clip
- rationale: one sentence on why this section works as a deeper bridge from Short to full sermon
- hook_score: integer 0–100, predicting how likely a viewer is to keep watching past the first 15 seconds
- hook_rationale: one sentence describing what the opening says or does and why it invites a deeper watch

Hook score rubric — use the full range, calibrate carefully:
- 90–100: extraordinary opening plus a clearly complete mini-message. Reserve for genuinely standout excerpts.
- 75–89: strong deeper clip with a clear human hook and satisfying development.
- 60–74: useful midweek excerpt, but the opening or ending needs volunteer judgment.
- 40–59: understandable, but too slow, too contextual, or not complete enough.
- Below 40: do not recommend; it is mostly setup, context-dependent, or incomplete.

Most Deeper Clips should fall in 60–85. Do not inflate scores.
"""

DEEPER_SYSTEM_PROMPT = f"""{_INTRO}

Deeper Clips

{_DEEPER_GUIDANCE}

{_DEEPER_MECHANICS}"""

# Strategy key (from app_settings) -> system prompt. Unknown keys fall back to
# the performance prompt in select_clips().
SYSTEM_PROMPTS = {
    "classic": CLASSIC_SYSTEM_PROMPT,
    "performance": PERFORMANCE_SYSTEM_PROMPT,
}


def _segment_view(transcript: dict) -> str:
    return "\n".join(
        f"[{s['start']:.2f}-{s['end']:.2f}] {s['text'].strip()}"
        for s in transcript["segments"]
    )


def select_clips(
    transcript_path: Path,
    num_clips_min: int = 3,
    num_clips_max: int = 8,
    selection_mode: str = "shorts",
) -> dict:
    mode = "deeper" if str(selection_mode).lower().strip() == "deeper" else "shorts"
    transcript = json.loads(transcript_path.read_text())
    segments_text = _segment_view(transcript)
    duration_min = transcript["duration"] / 60

    pick_label = "Deeper Clips" if mode == "deeper" else "clip candidates"
    mode_note = (
        "Use Deeper Clips mode: choose longer 2:30 to 5:00 midweek bridge excerpts "
        "from the full sermon transcript, independent of any previously selected Shorts."
        if mode == "deeper"
        else "Use Shorts mode: choose 30 to 90 second short-form clips."
    )
    user_text = (
        f"Sermon: {transcript['source']}\n"
        f"Duration: {duration_min:.1f} min\n"
        f"Segments: {len(transcript['segments'])}\n"
        f"Mode: {mode}\n"
        f"{mode_note}\n\n"
        f"Pick {num_clips_min} to {num_clips_max} {pick_label} from this transcript.\n\n"
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
    # Which editorial guidance Claude picks against. "performance" is the
    # reporting-tuned prompt (default); "classic" is the original, kept as an
    # alternate. Deeper Clips intentionally uses a separate prompt and searches
    # the whole transcript, not the previously selected Shorts pool.
    strategy = cfg["clip_selection_strategy"]
    if mode == "deeper":
        strategy = "deeper"
        system_prompt = DEEPER_SYSTEM_PROMPT
    else:
        system_prompt = SYSTEM_PROMPTS.get(strategy, PERFORMANCE_SYSTEM_PROMPT)

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
                system=system_prompt,
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
        # Which editorial guidance produced these clips, so Reporting can later
        # compare performance by strategy.
        "strategy": strategy,
        "selection_mode": mode,
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


def _normalize_selection_mode(selection_mode: str | None = None) -> str:
    return "deeper" if str(selection_mode or "shorts").lower().strip() == "deeper" else "shorts"


def clips_path_for(source_name: str, selection_mode: str | None = None) -> Path:
    mode = _normalize_selection_mode(selection_mode)
    filename = "clips.deeper.json" if mode == "deeper" else "clips.json"
    return settings.data_work_dir / Path(source_name).stem / filename


def write_clips(result: dict) -> Path:
    mode = _normalize_selection_mode(result.get("selection_mode"))
    result["selection_mode"] = mode
    out = clips_path_for(result["source"], mode)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    # Wipe any per-clip user edits left over from a previous Claude
    # generation -- clip indices in the new clips.json don't line up
    # with what the volunteer was editing, so the cleanest semantics
    # for "re-suggest clips" is "start fresh".
    from app.services import clip_overrides
    clip_overrides.delete_all(result["source"])
    return out
