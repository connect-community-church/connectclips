"""Generate karaoke-highlight ASS subtitles from Whisper word timings.

Each *word* gets its own Dialogue event — the chunk text is identical across
the chunk's events, but a different word is colored & scaled-up each time.
libass renders that as the moving "current word" highlight viewers expect
from short-form video.

Multiple visual presets are available via :data:`STYLES` — the volunteer
picks one in the trim view and we render the ASS accordingly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Approximate average character width as a fraction of font size for bold sans
# fonts. Used only to predict whether a chunk will wrap to a second line so we
# can size the bar correctly. Slight over-estimate is safer than under.
_CHAR_WIDTH_RATIO = 0.55
_SIDE_MARGIN_PX = 160  # 80 each side, matches the ASS Style margins below


def _estimate_lines(chunk_chars: int, font_size: int, video_w: int) -> int:
    if chunk_chars <= 0:
        return 1
    chars_per_line = max(1, int((video_w - _SIDE_MARGIN_PX) / (font_size * _CHAR_WIDTH_RATIO)))
    return max(1, math.ceil(chunk_chars / chars_per_line))


@dataclass(frozen=True)
class CaptionStyle:
    """Visual parameters for one preset. Tweak in one place per preset."""
    key: str
    label: str  # human-readable, shown in the dropdown
    font_name: str
    font_size: int
    primary_color: str    # ASS BGR: &HBBGGRR (no alpha)
    highlight_color: str
    outline_color: str
    outline_width: int
    shadow_depth: int
    highlight_scale: int  # percent — current word pops larger
    alignment: int        # ASS alignment: 2=bottom-center, 5=middle-center, 8=top-center
    margin_v: int         # px from the alignment edge
    bold: bool
    # chunking — different styles can prefer different word counts
    max_words_per_chunk: int
    max_chars_per_chunk: int
    # if True, draw a solid bar behind the text (separate ASS event under the
    # text layer). bar_color is BGR-only (no alpha prefix), bar_alpha is the
    # ASS \1a transparency hex — &H00& opaque, &HFF& fully transparent.
    background_box: bool
    bar_color: str = "&H000000&"  # default black for existing block style
    bar_alpha: str = "&H40&"      # 25% opaque (lower number = more visible)


# --- Presets ---------------------------------------------------------------

STYLES: dict[str, CaptionStyle] = {
    "classic": CaptionStyle(
        key="classic",
        label="Classic — yellow highlight",
        font_name="DejaVu Sans",
        font_size=90,
        primary_color="&H00FFFFFF",   # white
        highlight_color="&H0000FFFF", # yellow (BGR)
        outline_color="&H00000000",
        outline_width=5,
        shadow_depth=2,
        highlight_scale=110,
        alignment=2,
        margin_v=500,
        bold=True,
        max_words_per_chunk=3,
        max_chars_per_chunk=22,
        background_box=False,
    ),
    "neon_pop": CaptionStyle(
        key="neon_pop",
        label="Neon Pop — pink highlight, larger pop",
        font_name="DejaVu Sans",
        font_size=96,
        primary_color="&H00FFFFFF",
        highlight_color="&H00B469FF",  # hot pink (BGR ≈ rgb(255,105,180))
        outline_color="&H00000000",
        outline_width=6,
        shadow_depth=3,
        highlight_scale=130,
        alignment=2,
        margin_v=600,
        bold=True,
        max_words_per_chunk=3,
        max_chars_per_chunk=22,
        background_box=False,
    ),
    "block": CaptionStyle(
        key="block",
        label="Block — text on dark bar",
        font_name="DejaVu Sans",
        font_size=80,
        primary_color="&H00FFFFFF",
        highlight_color="&H0000FFFF",  # yellow
        outline_color="&H00000000",
        outline_width=2,
        shadow_depth=0,
        highlight_scale=110,
        alignment=2,
        margin_v=480,
        bold=True,
        # Tighter than other styles: each chunk should fit on one line so the
        # bar height stays predictable. The bar still grows to multiple lines
        # if a chunk overflows (see generate_ass), but we'd rather not rely on
        # that path.
        max_words_per_chunk=3,
        max_chars_per_chunk=20,
        background_box=True,
        bar_color="&H000000&",
        bar_alpha="&H40&",
    ),
    "white_block": CaptionStyle(
        key="white_block",
        label="White Block — black text on white bar, red highlight",
        font_name="DejaVu Sans",
        font_size=80,
        primary_color="&H00000000",     # black text
        highlight_color="&H000000FF",   # red (BGR — RGB(255,0,0))
        outline_color="&H00000000",
        outline_width=0,                # no outline; black text on white bar is legible enough
        shadow_depth=0,
        highlight_scale=110,
        alignment=2,
        margin_v=480,
        bold=True,
        max_words_per_chunk=3,
        max_chars_per_chunk=20,
        background_box=True,
        bar_color="&HFFFFFF&",          # white
        bar_alpha="&H10&",              # near-fully opaque (small alpha for slight see-through)
    ),
    "word_pop": CaptionStyle(
        key="word_pop",
        label="Word Pop — one big word at a time",
        font_name="DejaVu Sans",
        font_size=140,
        primary_color="&H00FFFFFF",
        highlight_color="&H0000FFFF",  # not used much — only one word
        outline_color="&H00000000",
        outline_width=8,
        shadow_depth=4,
        highlight_scale=100,           # only one word in chunk; no scale-up
        alignment=5,                   # middle-center
        margin_v=0,
        bold=True,
        max_words_per_chunk=1,
        max_chars_per_chunk=20,
        background_box=False,
    ),
}

DEFAULT_STYLE = "classic"


def list_styles() -> list[dict]:
    """Used by the API to populate the frontend dropdown."""
    return [{"key": s.key, "label": s.label} for s in STYLES.values()]


def get_style(key: str | None) -> CaptionStyle:
    if not key or key not in STYLES:
        return STYLES[DEFAULT_STYLE]
    return STYLES[key]


# --- Chunking + ASS emission ----------------------------------------------

MIN_GAP_FOR_BREAK = 0.55  # split if gap between consecutive words exceeds this
MAX_CHUNK_DURATION = 3.0


@dataclass
class Word:
    text: str
    start: float
    end: float


def words_in_range(transcript: dict, clip_start: float, clip_end: float) -> list[Word]:
    out: list[Word] = []
    for seg in transcript.get("segments", []):
        if seg["end"] <= clip_start:
            continue
        if seg["start"] >= clip_end:
            break
        for w in seg.get("words", []):
            if w["end"] <= clip_start:
                continue
            if w["start"] >= clip_end:
                continue
            text = w["word"].strip()
            if not text:
                continue
            out.append(Word(
                text=text,
                start=max(0.0, w["start"] - clip_start),
                end=min(clip_end - clip_start, w["end"] - clip_start),
            ))
    return _redistribute_degenerate_timings(out)


def _redistribute_degenerate_timings(words: list[Word]) -> list[Word]:
    """Whisper occasionally pins several consecutive words to the same start
    time (and zero duration) when the speaker runs words together. Without
    intervention, every one of those words emits its own caption event at
    exactly the same timestamp, and ASS stacks them vertically on screen.
    Detect those runs and spread the words evenly across the actual available
    time slot (next distinct word start, or the run's max end)."""
    n = len(words)
    if n <= 1:
        return words
    i = 0
    while i < n:
        j = i + 1
        # Run of words whose start is not strictly later than words[i].start
        while j < n and words[j].start <= words[i].start:
            j += 1
        run_size = j - i
        if run_size > 1:
            run_start = words[i].start
            max_end = max(words[k].end for k in range(i, j))
            if j < n:
                run_end = min(max_end, words[j].start)
            else:
                run_end = max_end
            # If the slot is unusably small, fall back to a reasonable spread
            if run_end <= run_start + 0.05:
                run_end = run_start + 0.5
            slot = (run_end - run_start) / run_size
            for k in range(i, j):
                words[k].start = run_start + (k - i) * slot
                words[k].end = run_start + (k - i + 1) * slot
        i = j
    return words


def chunk_words(words: list[Word], style: CaptionStyle) -> list[list[Word]]:
    chunks: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            chars = sum(len(x.text) for x in cur) + len(cur)
            dur = cur[-1].end - cur[0].start
            gap = w.start - cur[-1].end
            ends_sentence = cur[-1].text.endswith((".", "?", "!"))
            if (
                len(cur) >= style.max_words_per_chunk
                or chars + 1 + len(w.text) > style.max_chars_per_chunk
                or dur >= MAX_CHUNK_DURATION
                or gap > MIN_GAP_FOR_BREAK
                or ends_sentence
            ):
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def _fmt_time(s: float) -> str:
    if s < 0:
        s = 0.0
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    cs = int(round((s - int(s)) * 100))
    sec = int(s) % 60
    if cs == 100:
        cs = 0
        sec += 1
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


HOOK_DURATION = 2.0
HOOK_FADE_MS = 300
HOOK_FONT_SIZE_MAX = 140  # cap for very short titles
HOOK_FONT_SIZE_MIN = 80   # don't shrink past this; outline still readable
HOOK_OUTLINE = 8
HOOK_SHADOW = 4
HOOK_WRAP_THRESHOLD = 2   # 3+ words wrap to two lines (impactful, not 4-line stack)
HOOK_LINE_WIDTH_PX = 920  # 1080 - 80px each side margin


def _fit_font_size(longest_line_chars: int) -> int:
    """Pick a font size so a line of `longest_line_chars` chars fits in the
    horizontal margins. Caps at HOOK_FONT_SIZE_MAX so short titles still
    render big; floors at HOOK_FONT_SIZE_MIN to keep readability.
    """
    if longest_line_chars <= 0:
        return HOOK_FONT_SIZE_MAX
    raw = HOOK_LINE_WIDTH_PX / (longest_line_chars * _CHAR_WIDTH_RATIO)
    return max(HOOK_FONT_SIZE_MIN, min(HOOK_FONT_SIZE_MAX, int(raw)))


def _hook_title_text_and_size(title: str) -> tuple[str, int]:
    """Return (escaped ASS text with optional `\\N` line break, font size in px).

    For titles longer than the wrap threshold, splits into two balanced lines
    minimizing the longer line. Then sizes the font to fit that longest line.
    """
    words = title.strip().split()
    if not words:
        return "", HOOK_FONT_SIZE_MAX
    if len(words) <= HOOK_WRAP_THRESHOLD:
        text = " ".join(words)
        return _ass_escape(text), _fit_font_size(len(text))
    total = sum(len(w) for w in words)
    best = len(words) // 2
    best_score = float("inf")
    running = 0
    for i in range(1, len(words)):
        running += len(words[i - 1])
        score = max(running, total - running)
        if score < best_score:
            best_score = score
            best = i
    top = " ".join(words[:best])
    bottom = " ".join(words[best:])
    size = _fit_font_size(max(len(top), len(bottom)))
    return f"{_ass_escape(top)}\\N{_ass_escape(bottom)}", size


def _hook_dialogue(title: str, clip_duration: float) -> str:
    """Build a single Dialogue line for the hook title overlay.

    Fade in and out via `\\fad(in_ms, out_ms)`. Inline `\\fs` override scales
    the font down for long titles so libass doesn't soft-wrap the text into
    a 4-line stack. Sits at layer 2 — above any background bar (layer 0) and
    the per-word caption text (layer 1).
    """
    duration = max(0.3, min(HOOK_DURATION, clip_duration - 0.1))
    text, font_size = _hook_title_text_and_size(title)
    return (
        f"Dialogue: 2,{_fmt_time(0.0)},{_fmt_time(duration)},Hook,,0,0,0,,"
        f"{{\\fad({HOOK_FADE_MS},{HOOK_FADE_MS})\\fs{font_size}}}{text}"
    )


def generate_ass(
    words: list[Word],
    video_w: int = 1080,
    video_h: int = 1920,
    style: CaptionStyle | str | None = None,
    hook_title: str | None = None,
    clip_duration: float = 0.0,
    caption_margin_v: int | None = None,
) -> str:
    s = style if isinstance(style, CaptionStyle) else get_style(style)
    # Volunteer-overridden vertical position. Clamped to a safe range so a
    # bogus drag value can't push the text off-frame. The 80px floor leaves
    # room for the outline + a small breathing margin from the edge.
    if caption_margin_v is not None:
        s = CaptionStyle(**{**s.__dict__, "margin_v": max(80, min(video_h - 80, int(caption_margin_v)))})
    chunks = chunk_words(words, s)

    # We always use BorderStyle=1 (outline + shadow). When the style asks for a
    # background bar (background_box=True) we draw it as a separate ASS event
    # underneath the text — using BorderStyle=3 instead breaks because libass
    # splits the box at every per-word inline override.
    bold_flag = -1 if s.bold else 0
    style_line = (
        f"Style: Default,{s.font_name},{s.font_size},"
        f"{s.primary_color},{s.primary_color},{s.outline_color},&H00000000,"
        f"{bold_flag},0,0,0,100,100,0,0,1,{s.outline_width},{s.shadow_depth},"
        f"{s.alignment},80,80,{s.margin_v},1"
    )
    # The Hook style is intentionally separate from the caption style: the
    # overlay is a different visual register (giant centered title, just for
    # the first ~2s) and we don't want it to vary by caption preset.
    hook_style_line = (
        f"Style: Hook,{s.font_name},{HOOK_FONT_SIZE_MAX},"
        f"&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,{HOOK_OUTLINE},{HOOK_SHADOW},"
        f"5,80,80,0,1"
    )

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_w}\n"
        f"PlayResY: {video_h}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style_line}\n"
        f"{hook_style_line}\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    text_layer = 1 if s.background_box else 0  # text on top of any bar
    line_h = s.font_size + 8
    BAR_PAD_TOP = 8
    BAR_PAD_BOTTOM = 12

    # Flat next-chunk-start lookup so a chunk's bar can end exactly when the
    # next chunk's bar begins (no overlap → no stacked dialogues).
    chunk_starts = [c[0].start for c in chunks]

    events = []
    for ci, chunk in enumerate(chunks):
        chunk_start = chunk[0].start
        # End the chunk at its last word's end, OR at the next chunk's start
        # if that comes first (rare — only if last word's "end" is bogus).
        chunk_end = chunk[-1].end
        if ci + 1 < len(chunks):
            chunk_end = min(chunk_end, chunk_starts[ci + 1])
        if chunk_end <= chunk_start:
            chunk_end = chunk_start + 0.05  # defensive

        if s.background_box:
            chunk_chars = sum(len(w.text) for w in chunk) + max(0, len(chunk) - 1)
            n_lines = _estimate_lines(chunk_chars, s.font_size, video_w)
            bar_h = n_lines * line_h + BAR_PAD_TOP + BAR_PAD_BOTTOM
            bar_bottom = video_h - s.margin_v + BAR_PAD_BOTTOM
            bar_top = max(0, bar_bottom - bar_h)
            path = f"m 0 0 l {video_w} 0 l {video_w} {bar_h} l 0 {bar_h}"
            events.append(
                f"Dialogue: 0,{_fmt_time(chunk_start)},{_fmt_time(chunk_end)},Default,,0,0,0,,"
                f"{{\\an7\\pos(0,{bar_top})\\bord0\\shad0\\1c{s.bar_color}\\1a{s.bar_alpha}\\p1}}{path}{{\\p0}}"
            )

        for i, current in enumerate(chunk):
            parts = []
            for j, w in enumerate(chunk):
                escaped = _ass_escape(w.text)
                if j == i:
                    parts.append(
                        f"{{\\c{s.highlight_color}\\fscx{s.highlight_scale}\\fscy{s.highlight_scale}}}"
                        f"{escaped}"
                        f"{{\\c{s.primary_color}\\fscx100\\fscy100}}"
                    )
                else:
                    parts.append(escaped)
            text = " ".join(parts)
            start_t = current.start
            # End at next word's start (within chunk) or the chunk's end
            # boundary. NEVER extend into another chunk — that's what was
            # causing all the dialogues to stack up on screen at once for
            # fast speech.
            end_t = chunk[i + 1].start if i + 1 < len(chunk) else chunk_end
            if end_t <= start_t:
                end_t = start_t + 0.05  # defensive, avoid zero-duration events
            events.append(
                f"Dialogue: {text_layer},{_fmt_time(start_t)},{_fmt_time(end_t)},Default,,0,0,0,,{text}"
            )

    if hook_title and hook_title.strip() and clip_duration > 0:
        events.append(_hook_dialogue(hook_title, clip_duration))

    return header + "\n".join(events) + "\n"
