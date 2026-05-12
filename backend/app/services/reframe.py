"""Reframe a sermon clip to vertical 9:16 with variable-zoom face tracking.

The source is the program feed, which interleaves full-frame pastor with
PiP/composite slides where the pastor is a small inset in any of nine grid
positions. Single-zoom-level cropping fails on PiP frames (the slide
dominates, the pastor is squeezed off-center). This service handles both:

  - Detect a face per sampled frame.
  - Size the crop window proportional to face height (≈3.6× face_h tall).
    Result: full-frame pastor → wide crop; PiP pastor → tight crop.
  - Detect scene cuts via a downscaled grayscale frame-to-frame diff. The
    program feed cuts hard between layouts, so we MUST reset smoothing at
    each cut — otherwise the crop visibly drifts across the cut for ~0.3s.
  - Smooth (cx, cy, crop_h) within each cut-bounded segment. No smoothing
    across cuts.
  - Pipe cropped frames to ffmpeg + h264_nvenc, mux audio from source clip.

Face scanning runs once at ingest over the WHOLE source (``scan_source``)
and writes ``<work>/<stem>/source_scan.json``. Per-clip operations slice
that file — no re-scan on trim adjustments, no expensive ffmpeg extract
just to learn face positions. ``scan_for_clip`` falls back to an inline
``scan_source`` if the file is missing (first-time access for sources
ingested before prescan existed).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

import os

import av
import cv2
import numpy as np

from app import platform as plat
from app.config import settings
from app.services import captions
from app.services.yunet_ort import YuNetORT

# (message, percent in [0, 1]) → None. Called from the export pipeline to
# report progress; pass None to skip reporting.
ProgressCB = Callable[[str, float], None]

# Approximate weights so the overall percent feels right to a user. With the
# source-level prescan landed, "scan" is usually a cache hit at clip time
# (slice + dump), so encode dominates. Extract is the briefest phase.
_PHASE_WEIGHTS = {"extract": 0.10, "scan": 0.05, "encode": 0.85}
_PHASE_OFFSETS = {
    "extract": 0.00,
    "scan":    _PHASE_WEIGHTS["extract"],                                  # 0.10
    "encode":  _PHASE_WEIGHTS["extract"] + _PHASE_WEIGHTS["scan"],         # 0.15
}


def _emit(cb: ProgressCB | None, phase: str, current: int, total: int) -> None:
    if cb is None:
        return
    inner = (current / total) if total else 0.0
    overall = _PHASE_OFFSETS[phase] + _PHASE_WEIGHTS[phase] * inner
    label = {"extract": "Extracting clip", "scan": "Loading face track", "encode": "Encoding video"}[phase]
    if total:
        msg = f"{label} ({current}/{total})"
    else:
        msg = f"{label}…"
    cb(msg, overall)


# Source-level scan progress (used by the prescan job). Reported separately
# from the per-clip phases above so the activity log shows a clean 0-100%
# while the long full-source pass runs.
def _emit_prescan(cb: ProgressCB | None, current: int, total: int) -> None:
    if cb is None:
        return
    inner = (current / total) if total else 0.0
    cb(f"Scanning faces ({current}/{total or '?'})", max(0.0, min(1.0, inner)))


OUT_W = 1080
OUT_H = 1920
OUT_ASPECT = OUT_W / OUT_H  # 0.5625

# Detection / sampling
DETECT_EVERY_N = 3
# Detection + motion both run at half source resolution. YuNet is robust enough
# at 540p to find a ~40-pixel PiP face (which MediaPipe missed), while keeping
# the per-frame inference cheap.
DETECT_DOWNSCALE = 0.5
MIN_CONFIDENCE = 0.6  # YuNet — well-calibrated; 0.6 rejects most false positives

YUNET_MODEL = os.path.expanduser("~/.cache/connectclips/face_detection_yunet_2023mar.onnx")

# Crop sizing — multiplier from face height to crop height. Higher = wider
# framing (more pastor + background visible). Volunteer-selectable per clip
# via ClipUserEdits.zoom_level; falls back to DEFAULT_ZOOM_LEVEL when unset.
# Volunteer feedback at the 2026-05-09 meeting: the original "tight" framing
# read as a mugshot and amplified face-tracking jitter; "medium" gives more
# breathing room and feels closer to other churches' shorts.
ZOOM_PRESETS: dict[str, float] = {
    "tight":  3.6,
    "medium": 5.0,
    "wide":   7.0,
}
DEFAULT_ZOOM_LEVEL = "medium"
FACE_TO_CROP_H = ZOOM_PRESETS[DEFAULT_ZOOM_LEVEL]  # default multiplier
HEADROOM_FRAC = 0.10  # nudge crop up so face is above geometric center
MIN_CROP_H_FRAC = 0.30  # don't zoom in tighter than 30% of source height
MAX_CROP_H_FRAC = 1.00  # ...or wider than the full source height


def resolve_zoom(level: str | None) -> float:
    """Map a UI zoom preset name to the face→crop multiplier. Unknown or
    missing names fall back to the medium default — guards against a stale
    frontend writing a preset name the backend doesn't know about yet."""
    if level and level in ZOOM_PRESETS:
        return ZOOM_PRESETS[level]
    return ZOOM_PRESETS[DEFAULT_ZOOM_LEVEL]

# Smoothing — the EMA alpha and deadband together produce a "PTZ-smooth" feel:
# detector jitter (a few pixels frame-to-frame) is absorbed by the deadband,
# real movement (pastor walking) is followed but slowly. The original 0.20
# tracked too fast and read as a wobbly handheld camera on the clean feed
# where pastor position is otherwise rock steady.
EMA_ALPHA = 0.05
# Deadband threshold: face must move at least this many pixels OR this fraction
# of its own height before the crop starts panning. Whichever is larger wins,
# so a small distant face has its own scaled deadband while a large near face
# uses the absolute floor.
DEADBAND_PX_MIN = 20.0
DEADBAND_FACE_FRAC = 0.15
# Crop-height deadband: face height must change by at least this fraction of
# the current crop height before we update zoom. Detector face_h drifts by
# 1-3% per frame even on a still face; without this, that jitter scales
# straight into visible zoom wobble (face_h * 5.0 multiplier = ±10-30px of
# crop motion per frame on Medium). 10% is the threshold for "real pose
# change worth tracking" vs "detector noise we should ignore" — anything
# below that and the crop stays put.
DEADBAND_H_FRAC = 0.10
# Once the height deadband fires we still ease toward target instead of
# snapping, but with a slower alpha than position. Snapping would be visible
# as a single-frame step; this slower glide takes ~3-4s to fully catch up,
# which reads as natural "the camera adjusted" rather than "the crop jumped".
EMA_ALPHA_H = 0.02

# Scene cut detection (run on every frame)
CUT_DOWNSCALE_W = 64  # tiny grayscale thumb for diffing
CUT_THRESHOLD = 25.0  # mean abs delta on uint8 — tune empirically

# Live-face filter: faces in static graphics (illustrations on slides) get
# detected just like real video faces. The robust discriminator is motion —
# a real PiP video shows pixel changes (talking, breathing, lighting); an
# illustration is bit-identical between consecutive sampled frames. Discard
# any detection whose bbox has mean abs delta below this threshold vs the
# previous sampled frame.
MOTION_THRESHOLD = 5.0

# Identity tracking (used during scan_source to label each detection with a
# stable id across samples).
# Position + size already enforce continuity: a face appearing in roughly the
# same place at roughly the same scale is almost certainly the same person,
# even if they were off-camera for a long stretch. We DON'T expire tracks
# based on time gap: a sermon source has long slide-only passages where the
# pastor disappears for minutes, and an aggressive gap threshold would
# fragment a single pastor into dozens of identities (slide → new id, slide
# → new id, …).  An empirical first attempt at 60 samples (~6 s) produced
# 47 identities for a one-pastor sermon — clearly wrong.
IDENTITY_MAX_DIST_RATIO = 1.5
IDENTITY_SIZE_RATIO = 2.0
# Practical "never expire" cap. Above this, treat as a new identity — handles
# the pathological edge case where two people happen to occupy the same
# camera position much later in the source. ~30 min at 30 fps with N=3.
IDENTITY_GAP_SAMPLES = 18000

SOURCE_SCAN_VERSION = 1

logger = logging.getLogger(__name__)


# ---------- Source-level prescan ------------------------------------------

# Per-source lock to prevent two callers (background prescan job + on-demand
# UI fallback) from scanning the same source twice in parallel.
_source_scan_locks: dict[str, threading.Lock] = {}
_source_scan_locks_master = threading.Lock()


def _lock_for_source(stem: str) -> threading.Lock:
    with _source_scan_locks_master:
        lock = _source_scan_locks.get(stem)
        if lock is None:
            lock = threading.Lock()
            _source_scan_locks[stem] = lock
        return lock


def source_scan_path(source_path: Path) -> Path:
    """Where the per-source face/cut/identity scan is cached."""
    return settings.data_work_dir / source_path.stem / "source_scan.json"


def has_source_scan(source_path: Path) -> bool:
    return source_scan_path(source_path).is_file()


def scan_source(source_path: Path, progress_cb: ProgressCB | None = None) -> dict:
    """Scan the entire source video once. Writes
    ``<work>/<stem>/source_scan.json`` and returns the parsed dict.
    Idempotent — if the scan file already exists at the current schema
    version it is returned without rescanning.

    The per-source lock guarantees concurrent callers can't both scan.
    """
    out_path = source_scan_path(source_path)
    lock = _lock_for_source(source_path.stem)
    with lock:
        if out_path.exists():
            try:
                cached = json.loads(out_path.read_text())
                if cached.get("version") == SOURCE_SCAN_VERSION:
                    return cached
            except Exception:
                out_path.unlink(missing_ok=True)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        scan = _do_full_scan(source_path, progress_cb=progress_cb)
        # Atomic write: rename after fully serialising so a crash mid-write
        # doesn't leave a half-truncated JSON that future loads will reject.
        tmp = out_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(scan))
        tmp.replace(out_path)
        return scan


def _do_full_scan(source_path: Path, progress_cb: ProgressCB | None = None) -> dict:
    """Single decode pass over the whole source."""
    container = av.open(str(source_path))
    vstream = container.streams.video[0]
    src_w, src_h = vstream.width, vstream.height
    fps = float(vstream.average_rate)
    duration_frames = 0
    if vstream.duration is not None and vstream.time_base is not None:
        duration_frames = int(round(float(vstream.duration * vstream.time_base) * fps))
    total_hint = max(1, duration_frames)

    det_w = round(src_w * DETECT_DOWNSCALE)
    det_h = round(src_h * DETECT_DOWNSCALE)
    detector = YuNetORT(
        YUNET_MODEL, conf_threshold=MIN_CONFIDENCE, nms_threshold=0.3,
    )

    samples: list[dict] = []
    cuts: list[int] = [0]
    prev_thumb: np.ndarray | None = None
    prev_motion_img: np.ndarray | None = None
    n_frames = 0
    identities: list[dict] = []
    next_identity_id = 1

    for frame in container.decode(video=0):
        rgb = frame.to_ndarray(format="rgb24")

        if progress_cb is not None and n_frames % 60 == 0:
            _emit_prescan(progress_cb, n_frames, total_hint)

        # Scene cut: tiny grayscale diff on every frame
        thumb_h = max(1, round(CUT_DOWNSCALE_W * src_h / src_w))
        thumb = cv2.cvtColor(
            cv2.resize(rgb, (CUT_DOWNSCALE_W, thumb_h)), cv2.COLOR_RGB2GRAY
        )
        if prev_thumb is not None:
            diff = float(np.mean(np.abs(thumb.astype(np.int16) - prev_thumb.astype(np.int16))))
            if diff > CUT_THRESHOLD and n_frames - cuts[-1] >= 3:
                cuts.append(n_frames)
        prev_thumb = thumb

        # Face detection at 1/N rate
        if n_frames % DETECT_EVERY_N == 0:
            sample_idx = len(samples)
            small_rgb = cv2.resize(rgb, (det_w, det_h))
            small_bgr = cv2.cvtColor(small_rgb, cv2.COLOR_RGB2BGR)
            dets = detector.detect(small_bgr)

            live_faces: list[dict] = []
            if dets is not None and prev_motion_img is not None and prev_motion_img.shape == small_rgb.shape:
                for det in dets:
                    x, y, fw, fh = float(det[0]), float(det[1]), float(det[2]), float(det[3])
                    score = float(det[14])
                    x0 = max(0, int(x))
                    y0 = max(0, int(y))
                    x1 = min(det_w, int(x + fw))
                    y1 = min(det_h, int(y + fh))
                    if x1 <= x0 or y1 <= y0:
                        continue
                    a = small_rgb[y0:y1, x0:x1].astype(np.int16)
                    b = prev_motion_img[y0:y1, x0:x1].astype(np.int16)
                    motion = float(np.mean(np.abs(a - b)))
                    if motion < MOTION_THRESHOLD:
                        continue
                    scale = 1.0 / DETECT_DOWNSCALE
                    live_faces.append({
                        "cx": (x + fw / 2) * scale,
                        "cy": (y + fh / 2) * scale,
                        "w":  fw * scale,
                        "h":  fh * scale,
                        "score": score,
                    })

            assigned = _assign_identities(
                live_faces, identities, sample_idx, n_frames, next_identity_id,
            )
            next_identity_id = assigned["next_id"]
            samples.append({"faces": assigned["faces"]})
            prev_motion_img = small_rgb
        n_frames += 1

    container.close()
    if progress_cb is not None:
        _emit_prescan(progress_cb, n_frames, n_frames)

    return {
        "version": SOURCE_SCAN_VERSION,
        "source": source_path.name,
        "src_w": src_w,
        "src_h": src_h,
        "fps": fps,
        "n_frames": n_frames,
        "detect_every_n": DETECT_EVERY_N,
        "detect_downscale": DETECT_DOWNSCALE,
        "scanned_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "cuts": cuts,
        "samples": samples,
        "identities": _summarise_identities(identities, n_frames),
    }


def _assign_identities(
    live_faces: list[dict],
    identities: list[dict],
    sample_idx: int,
    frame_idx: int,
    next_id: int,
) -> dict:
    """Greedy match live faces to existing identity tracks; create new tracks
    for unmatched faces. Returns ``{"faces": [...with id...], "next_id": int}``.

    Position + size are doing the work: a face whose centroid is far from
    every active track or whose scale is wildly different gets a new id.
    The IDENTITY_GAP_SAMPLES check is set very high deliberately — fragmenting
    a single pastor across many identities (slide-heavy passages → off camera
    → new id on return) is a much worse failure mode than occasionally
    merging two people who happened to share a camera position far apart in
    time."""
    if not live_faces:
        return {"faces": [], "next_id": next_id}

    candidates: list[tuple[float, int, int]] = []
    for fi, face in enumerate(live_faces):
        for ti, track in enumerate(identities):
            if sample_idx - track["last_sample_idx"] > IDENTITY_GAP_SAMPLES:
                continue
            dh = max(face["h"], track["last_h"])
            dist = math.hypot(face["cx"] - track["last_cx"], face["cy"] - track["last_cy"])
            if dist > IDENTITY_MAX_DIST_RATIO * dh:
                continue
            denom = max(1.0, min(face["h"], track["last_h"]))
            size_ratio = max(face["h"], track["last_h"]) / denom
            if size_ratio > IDENTITY_SIZE_RATIO:
                continue
            cost = dist + abs(face["h"] - track["last_h"]) * 0.5
            candidates.append((cost, fi, ti))

    candidates.sort(key=lambda c: c[0])
    used_faces: set[int] = set()
    used_tracks: set[int] = set()
    matches: dict[int, int] = {}
    for _cost, fi, ti in candidates:
        if fi in used_faces or ti in used_tracks:
            continue
        matches[fi] = ti
        used_faces.add(fi)
        used_tracks.add(ti)

    out_faces: list[dict] = []
    for fi, face in enumerate(live_faces):
        if fi in matches:
            ti = matches[fi]
            track = identities[ti]
            track["last_cx"] = face["cx"]
            track["last_cy"] = face["cy"]
            track["last_h"] = face["h"]
            track["last_sample_idx"] = sample_idx
            track["last_frame"] = frame_idx
            track["n_samples"] += 1
            if face["score"] > track["thumb_score"]:
                track["thumb_score"] = face["score"]
                track["thumb_frame_idx"] = frame_idx
                track["thumb_box"] = {
                    "cx": face["cx"], "cy": face["cy"],
                    "w": face["w"], "h": face["h"],
                }
            if face["score"] > track["score_max"]:
                track["score_max"] = face["score"]
            ident_id = track["id"]
        else:
            ident_id = next_id
            next_id += 1
            identities.append({
                "id": ident_id,
                "last_cx": face["cx"], "last_cy": face["cy"], "last_h": face["h"],
                "last_sample_idx": sample_idx,
                "first_frame": frame_idx, "last_frame": frame_idx,
                "n_samples": 1,
                "score_max": face["score"],
                "thumb_score": face["score"],
                "thumb_frame_idx": frame_idx,
                "thumb_box": {
                    "cx": face["cx"], "cy": face["cy"],
                    "w": face["w"], "h": face["h"],
                },
            })
        out_faces.append({**face, "id": ident_id})

    return {"faces": out_faces, "next_id": next_id}


def _summarise_identities(identities: list[dict], n_frames: int) -> list[dict]:
    """Strip mutable matching state, keep only the JSON-friendly summary.
    Sorted by sample count descending so the dominant identity (almost always
    the pastor for a sermon source) is index 0.
    """
    out = [
        {
            "id": t["id"],
            "n_samples": t["n_samples"],
            "first_frame": t["first_frame"],
            "last_frame": t["last_frame"],
            "score_max": round(t["score_max"], 4),
            "thumb_frame_idx": t["thumb_frame_idx"],
            "thumb_box": t["thumb_box"],
        }
        for t in identities
    ]
    out.sort(key=lambda t: t["n_samples"], reverse=True)
    return out


# ---------- Per-clip slice & track build -----------------------------------

def scan_for_clip(
    source_path: Path,
    start: float,
    end: float,
    progress_cb: ProgressCB | None = None,
    identity_id: int | None = None,
) -> dict:
    """Slice the source-level scan to the [start, end] range. Triggers a
    full source scan if one isn't cached (fallback for any source that
    pre-dates the prescan job)."""
    src_scan = scan_source(source_path, progress_cb=progress_cb)
    return _slice_source_scan(src_scan, start, end, identity_id=identity_id)


def _slice_source_scan(
    src_scan: dict,
    start: float,
    end: float,
    identity_id: int | None = None,
) -> dict:
    """Translate (start, end) seconds into a clip-local scan dict matching
    the shape the encoder expects.

    Picks one face per sample (highest score among detections matching
    ``identity_id`` if given, else highest score overall). Cuts are
    translated to clip-local frame indices, with a synthetic cut at frame 0
    to preserve segment-snap behaviour."""
    fps = float(src_scan["fps"])
    src_w = int(src_scan["src_w"])
    src_h = int(src_scan["src_h"])
    detect_every_n = int(src_scan.get("detect_every_n", DETECT_EVERY_N))
    n_total = int(src_scan["n_frames"])

    frame_a = max(0, int(round(start * fps)))
    frame_b = max(frame_a + 1, int(round(end * fps)))
    frame_b = min(frame_b, n_total)
    n_clip_frames = frame_b - frame_a

    samples = src_scan["samples"]
    sample_a = frame_a // detect_every_n
    # Inclusive upper bound: ceil(frame_b / N) covers the trailing partial window.
    sample_b = min(len(samples), -(-frame_b // detect_every_n))
    sample_offset_frames = 0
    if sample_a > 0:
        # Including one sample BEFORE frame_a lets the very first frames of
        # the clip carry over the most recent identity / position rather than
        # falling through to "no detections in this segment".
        sample_a = sample_a - 1
        # The leading sample covers frames [(sample_a)*N .. (sample_a+1)*N-1];
        # we want the per-frame expansion to start at frame_a, so we'll trim
        # the first `sample_offset_frames` rows from the expansion.
        sample_offset_frames = frame_a - (sample_a * detect_every_n)

    sliced_faces: list[dict | None] = []
    for s in samples[sample_a:sample_b]:
        face_list = s.get("faces", [])
        if identity_id is not None:
            picked = _pick_by_identity(face_list, identity_id)
        else:
            picked = _pick_highest_score(face_list)
        if picked is None:
            sliced_faces.append(None)
        else:
            sliced_faces.append({
                "cx": picked["cx"], "cy": picked["cy"],
                "w": picked["w"], "h": picked["h"],
            })

    # Translate cuts into clip-local frame indices. Always include a synthetic
    # cut at 0 so segment-snap behaves correctly at the clip's first frame.
    cuts = [0]
    for cut_frame in src_scan.get("cuts", []):
        if cut_frame <= frame_a:
            continue
        if cut_frame >= frame_b:
            break
        local = cut_frame - frame_a
        if local > cuts[-1] + 2:
            cuts.append(local)

    return {
        "n_frames": n_clip_frames,
        "src_w": src_w,
        "src_h": src_h,
        "fps": fps,
        "faces": sliced_faces,
        "cuts": cuts,
        "sample_offset_frames": sample_offset_frames,
    }


def _pick_highest_score(face_list: list[dict]) -> dict | None:
    if not face_list:
        return None
    return max(face_list, key=lambda f: f.get("score", 0.0))


def _pick_by_identity(face_list: list[dict], identity_id: int) -> dict | None:
    matches = [f for f in face_list if f.get("id") == identity_id]
    if matches:
        return max(matches, key=lambda f: f.get("score", 0.0))
    # If the requested identity isn't in this sample, fall back to the
    # most prominent live face. Prevents whole-segment "no face" runs when
    # the requested identity blinks out for a sample or two; cut-bounded
    # smoothing still snaps on real shot changes.
    return _pick_highest_score(face_list)


def track_for_clip(
    source_path: Path,
    start: float,
    end: float,
    identity_id: int | None = None,
    zoom_level: str | None = None,
    lock_camera: bool = False,
) -> dict:
    """Return the per-frame crop track for the preview UI. Cheap when the
    source scan exists (just a slice). The first call after a fresh source
    upload triggers ``scan_source`` synchronously.

    ``zoom_level`` is a preset name from ``ZOOM_PRESETS`` ("tight"/"medium"/
    "wide"); unknown / unset falls back to the default. ``lock_camera``
    bypasses tracking entirely and emits a constant crop at the median
    face position."""
    scan = scan_for_clip(source_path, start, end, identity_id=identity_id)
    per_frame_faces = _expand_to_per_frame(
        scan["n_frames"], scan["faces"], scan.get("sample_offset_frames", 0),
    )
    track = _segment_crop_track(
        scan["n_frames"], scan["src_w"], scan["src_h"],
        per_frame_faces, scan["cuts"],
        face_to_crop_h=resolve_zoom(zoom_level),
        lock_camera=lock_camera,
    )
    return {
        "n_frames": int(scan["n_frames"]),
        "src_w": int(scan["src_w"]),
        "src_h": int(scan["src_h"]),
        "fps": float(scan["fps"]),
        "out_w": OUT_W,
        "out_h": OUT_H,
        "track": track.tolist(),
    }


def identities_for_source(source_path: Path) -> list[dict]:
    """Return identities recorded in the source scan, or an empty list if
    the scan hasn't been built yet (caller can decide whether to block on a
    scan or display a placeholder)."""
    if not has_source_scan(source_path):
        return []
    try:
        scan = json.loads(source_scan_path(source_path).read_text())
    except Exception:
        return []
    return list(scan.get("identities", []))


def extract_identity_thumb(
    source_path: Path,
    frame_idx: int,
    box: dict,
    out_path: Path,
    *,
    pad_ratio: float = 0.6,
) -> Path:
    """Cut a square thumbnail of the identity from the source video.

    Uses ffmpeg's ``-ss`` accurate-seek + a single-frame ``-vframes 1``
    extract. ``box`` is the source-pixel bbox stored on the identity. Pads
    by ``pad_ratio * face_h`` so the crop shows shoulders/headroom — a bare
    face crop reads as a mugshot and isn't great for picking. Output is
    PNG."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(source_path))
    vstream = container.streams.video[0]
    src_w, src_h = vstream.width, vstream.height
    fps = float(vstream.average_rate)
    seek_seconds = max(0.0, frame_idx / max(1.0, fps))
    container.close()

    fh = float(box["h"])
    pad = fh * pad_ratio
    side = max(fh + 2 * pad, 96.0)
    cx, cy = float(box["cx"]), float(box["cy"])
    x = max(0, int(round(cx - side / 2)))
    y = max(0, int(round(cy - side / 2)))
    side_int = int(round(side))
    side_int = min(side_int, src_w - x, src_h - y)
    side_int = max(64, side_int)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{seek_seconds:.3f}",
        "-i", str(source_path),
        "-vframes", "1",
        "-vf", f"crop={side_int}:{side_int}:{x}:{y},scale=192:192",
        str(out_path),
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        tail = res.stderr.decode("utf-8", errors="replace").strip().splitlines()[-8:]
        raise RuntimeError(f"ffmpeg face-thumb failed (rc={res.returncode}):\n  " + "\n  ".join(tail))
    return out_path


def _ffmpeg_extract(source: Path, start: float, end: float, out: Path) -> None:
    # -ss BEFORE -i uses the container index to jump to the keyframe right
    # before our target, then `-accurate_seek` (default ON when re-encoding)
    # decodes forward to the exact target frame and discards the gap.  Result:
    # frame-accurate output starting exactly at PTS=0 of `start`, but ffmpeg
    # only has to decode ~2 seconds of video instead of (start) seconds.
    # Empirical benchmark on a 35-min-deep clip from a 60 fps source: 108 s
    # (-ss AFTER) → 7 s (-ss BEFORE), bit-exact identical output. The historical
    # warning about caption drift only applies to stream-copy (`-c copy`) mode;
    # we re-encode here, so accurate_seek does the right thing.
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start}",
        "-i", str(source),
        "-t", f"{end - start}",
        *plat.encoder_args(plat.H264_ENCODER, fast=True, bitrate_video="8M"),
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        str(out),
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        tail = res.stderr.decode("utf-8", errors="replace").strip().splitlines()[-12:]
        raise RuntimeError(f"ffmpeg clip-extract failed (rc={res.returncode}):\n  " + "\n  ".join(tail))


def _expand_to_per_frame(
    n_frames: int,
    faces: list[dict | None],
    sample_offset_frames: int = 0,
) -> list[dict | None]:
    """Repeat each sample DETECT_EVERY_N times to align with frame indices.

    ``sample_offset_frames`` accounts for the case where the slice deliberately
    includes one sample before frame_a (so the first frames of the clip carry
    over the most recent face); we drop that many leading rows from the
    expansion so the result aligns to clip-local frame 0.
    """
    per_frame: list[dict | None] = []
    for v in faces:
        per_frame.extend([v] * DETECT_EVERY_N)
    if sample_offset_frames > 0:
        per_frame = per_frame[sample_offset_frames:]
    if len(per_frame) >= n_frames:
        return per_frame[:n_frames]
    pad = (per_frame[-1] if per_frame else None)
    return per_frame + [pad] * (n_frames - len(per_frame))


def _segment_crop_track(
    n_frames: int,
    src_w: int,
    src_h: int,
    faces_per_frame: list[dict | None],
    cuts: list[int],
    face_to_crop_h: float = FACE_TO_CROP_H,
    lock_camera: bool = False,
) -> np.ndarray:
    """Build per-frame (cx, cy, crop_h) array using cut-bounded smoothing.

    Within each cut-bounded segment, follow the face (forward-filling
    detection gaps) with a deadband + slow-EMA that absorbs detector jitter
    while still following real movement. At each cut, snap to the new face
    position. No smoothing crosses a cut.

    ``face_to_crop_h`` is the multiplier from face height to crop height
    (3.6 = tight, 5.0 = medium, 7.0 = wide). Higher values produce wider
    framing with less perceived jitter.

    ``lock_camera``: when True, ignore per-frame face positions and emit a
    single static crop at the median face position over the whole clip.
    Trades "follows the pastor" for "absolute zero motion." Useful on a
    fixed PTZ camera with a stationary pastor.

    Returns shape (n_frames, 3).
    """
    if lock_camera:
        return _locked_crop_track(n_frames, src_w, src_h, faces_per_frame, face_to_crop_h)
    track = np.zeros((n_frames, 3), dtype=np.float32)
    cut_bounds = list(cuts) + [n_frames]
    last_state: tuple[float, float, float] | None = None

    global_first_face = next((f for f in faces_per_frame if f is not None), None)

    def _state_from_face(f: dict) -> tuple[float, float, float]:
        h = float(np.clip(
            f["h"] * face_to_crop_h,
            src_h * MIN_CROP_H_FRAC,
            src_h * MAX_CROP_H_FRAC,
        ))
        return (f["cx"], f["cy"] - HEADROOM_FRAC * h, h)

    for seg_start, seg_end in zip(cut_bounds[:-1], cut_bounds[1:]):
        seg_faces = faces_per_frame[seg_start:seg_end]
        first_det_idx = next((i for i, f in enumerate(seg_faces) if f is not None), None)

        if first_det_idx is None:
            if last_state is not None:
                cx, cy_anchor, crop_h = last_state
            elif global_first_face is not None:
                cx, cy_anchor, crop_h = _state_from_face(global_first_face)
            else:
                cx, cy_anchor = src_w / 2, src_h / 2
                crop_h = src_h * MAX_CROP_H_FRAC
            for i in range(seg_end - seg_start):
                track[seg_start + i] = (cx, cy_anchor, crop_h)
            last_state = (cx, cy_anchor, crop_h)
            continue

        first = seg_faces[first_det_idx]
        snap_h = float(np.clip(
            first["h"] * face_to_crop_h,
            src_h * MIN_CROP_H_FRAC,
            src_h * MAX_CROP_H_FRAC,
        ))
        snap_cx = first["cx"]
        snap_cy = first["cy"] - HEADROOM_FRAC * snap_h
        prev = (snap_cx, snap_cy, snap_h)

        last_face = first
        for i in range(seg_end - seg_start):
            face = seg_faces[i]
            if face is not None:
                last_face = face
            target_h = float(np.clip(
                last_face["h"] * face_to_crop_h,
                src_h * MIN_CROP_H_FRAC,
                src_h * MAX_CROP_H_FRAC,
            ))
            target_cx = last_face["cx"]
            target_cy = last_face["cy"] - HEADROOM_FRAC * target_h

            if i == 0:
                track[seg_start] = prev
            else:
                px, py, ph = prev
                # Position and crop-height each have an independent deadband.
                # Position deadband scales with face size so a small distant
                # face has a proportionally tight threshold while a large near
                # face uses the absolute floor.  Height deadband is a fraction
                # of the CURRENT crop height — anchored on what's on screen,
                # not what the detector just reported, so the threshold stays
                # stable across the segment.
                pos_threshold = max(DEADBAND_PX_MIN, last_face["h"] * DEADBAND_FACE_FRAC)
                dx = target_cx - px
                dy = target_cy - py
                pos_moves = abs(dx) >= pos_threshold or abs(dy) >= pos_threshold

                h_change = abs(target_h - ph)
                h_moves = h_change >= ph * DEADBAND_H_FRAC

                new_cx = (EMA_ALPHA * target_cx + (1 - EMA_ALPHA) * px) if pos_moves else px
                new_cy = (EMA_ALPHA * target_cy + (1 - EMA_ALPHA) * py) if pos_moves else py
                new_h  = (EMA_ALPHA_H * target_h + (1 - EMA_ALPHA_H) * ph) if h_moves else ph
                track[seg_start + i] = (new_cx, new_cy, new_h)
            prev = tuple(track[seg_start + i])

        last_state = prev

    return track


def _locked_crop_track(
    n_frames: int,
    src_w: int,
    src_h: int,
    faces_per_frame: list[dict | None],
    face_to_crop_h: float,
) -> np.ndarray:
    """Lock Camera mode: emit one fixed (cx, cy, crop_h) tile across every
    frame. Position is the median of all detected face centres across the
    clip — median rather than mean so a few off-frame stray detections
    can't pull the static crop off the pastor.

    If no faces were ever detected, fall back to a centred max-height crop
    (same fallback as the smoothing path's all-empty segments)."""
    valid = [f for f in faces_per_frame if f is not None]
    if not valid:
        cx = float(src_w) / 2.0
        cy_anchor = float(src_h) / 2.0
        crop_h = float(src_h) * MAX_CROP_H_FRAC
    else:
        cxs = np.array([f["cx"] for f in valid], dtype=np.float32)
        cys = np.array([f["cy"] for f in valid], dtype=np.float32)
        hs  = np.array([f["h"]  for f in valid], dtype=np.float32)
        med_cx = float(np.median(cxs))
        med_cy = float(np.median(cys))
        med_h  = float(np.median(hs))
        crop_h = float(np.clip(
            med_h * face_to_crop_h,
            src_h * MIN_CROP_H_FRAC,
            src_h * MAX_CROP_H_FRAC,
        ))
        cx = med_cx
        cy_anchor = med_cy - HEADROOM_FRAC * crop_h
    return np.tile(
        np.array([cx, cy_anchor, crop_h], dtype=np.float32),
        (n_frames, 1),
    )


def _crop_window(
    cx: float, cy: float, crop_h: float, src_w: int, src_h: int
) -> tuple[int, int, int, int]:
    crop_h_int = int(round(crop_h))
    crop_w_int = int(round(crop_h * OUT_ASPECT))
    crop_h_int = min(crop_h_int, src_h)
    crop_w_int = min(crop_w_int, src_w)
    x = int(round(cx - crop_w_int / 2))
    y = int(round(cy - crop_h_int / 2))
    x = max(0, min(src_w - crop_w_int, x))
    y = max(0, min(src_h - crop_h_int, y))
    return x, y, crop_w_int, crop_h_int


def _encode(
    clip_path: Path,
    track: np.ndarray,
    src_w: int,
    src_h: int,
    fps: float,
    out_path: Path,
    ass_path: Path | None = None,
    progress_cb: ProgressCB | None = None,
    total_frames: int = 0,
) -> None:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-video_size", f"{OUT_W}x{OUT_H}",
        "-framerate", f"{fps}",
        "-i", "pipe:0",
        "-i", str(clip_path),
        "-map", "0:v:0", "-map", "1:a:0?",
    ]
    if ass_path is not None:
        # ffmpeg's filter parser uses `:` as the option separator within a
        # filter, so a Windows path like `C:/Foo/bar.ass` makes ffmpeg think
        # `C` is the filename and `/Foo/bar.ass` is the next option (it
        # complains "Unable to parse original_size option value ..."). The
        # standard fix is: forward-slash the path, backslash-escape the
        # drive-letter colon, AND wrap the whole value in single quotes so
        # ffmpeg parses it as one quoted filter-argument value.
        ff_path = str(ass_path).replace("\\", "/").replace(":", "\\:")
        cmd += ["-vf", f"subtitles='{ff_path}'"]
    cmd += [
        *plat.encoder_args(plat.H264_ENCODER, fast=False, bitrate_video="6M"),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(out_path),
    ]
    # Capture stderr so a non-zero rc surfaces ffmpeg's actual diagnostic
    # instead of swallowing it. Without this we just get a generic
    # BrokenPipeError when our writer trips over ffmpeg's already-closed
    # stdin and never learn why ffmpeg quit.
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    container = av.open(str(clip_path))
    pipe_broken = False
    try:
        for idx, frame in enumerate(container.decode(video=0)):
            rgb = frame.to_ndarray(format="rgb24")
            if progress_cb is not None and total_frames and idx % 30 == 0:
                _emit(progress_cb, "encode", idx, total_frames)
            cx, cy, ch = track[min(idx, len(track) - 1)]
            x, y, cw, ch_int = _crop_window(cx, cy, ch, src_w, src_h)
            cropped = rgb[y:y + ch_int, x:x + cw]
            scaled = cv2.resize(cropped, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)
            bgr = cv2.cvtColor(scaled, cv2.COLOR_RGB2BGR)
            try:
                proc.stdin.write(bgr.tobytes())
            except BrokenPipeError:
                # ffmpeg already exited (failed encoder / bad filter / etc).
                # Stop feeding frames, fall through to wait + report stderr.
                pipe_broken = True
                break
    finally:
        container.close()
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        stderr_bytes = proc.stderr.read() if proc.stderr else b""
        proc.wait()
    if proc.returncode != 0 or pipe_broken:
        tail = stderr_bytes.decode("utf-8", errors="replace").strip().splitlines()[-12:]
        msg = "\n  ".join(tail) if tail else "(no stderr captured)"
        raise RuntimeError(
            f"ffmpeg encode failed (rc={proc.returncode}, pipe_broken={pipe_broken}). "
            f"Last stderr lines:\n  {msg}"
        )


def _encode_stage(
    clip_path: Path,
    out_path: Path,
    ass_path: Path | None = None,
    progress_cb: ProgressCB | None = None,
    total_frames: int = 0,
    duration_seconds: float = 0.0,
) -> None:
    """Stage mode encode: full source frame letterboxed onto a blurred copy
    of itself. No face tracking — the whole frame is shown so the pastor
    can't drift out of crop, and the blur fill makes the empty top/bottom
    look polished instead of black-bar dead space.

    Single ffmpeg pass on the already-extracted clip (no Python decode
    loop). Progress is parsed from ``-progress pipe:1`` stdout so the export
    UI still gets a moving bar.
    """
    bg_chain = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,gblur=sigma=24"
    )
    # -2 keeps height even (h264 requires even dims); width = OUT_W.
    fg_chain = f"scale={OUT_W}:-2"
    parts = [
        "[0:v]split=2[bg_in][fg_in]",
        f"[bg_in]{bg_chain}[bg]",
        f"[fg_in]{fg_chain}[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[composite]",
    ]
    final_label = "[composite]"
    if ass_path is not None:
        # Same colon-escape trick as _encode: forward-slash path, escape the
        # drive-letter colon if present, single-quote the whole filename.
        ff_path = str(ass_path).replace("\\", "/").replace(":", "\\:")
        parts.append(f"[composite]subtitles='{ff_path}'[v]")
        final_label = "[v]"
    filtergraph = ";".join(parts)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(clip_path),
        "-filter_complex", filtergraph,
        "-map", final_label, "-map", "0:a:0?",
        *plat.encoder_args(plat.H264_ENCODER, fast=False, bitrate_video="6M"),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    total_us = max(1, int(duration_seconds * 1_000_000))
    stderr_bytes = b""
    try:
        if proc.stdout is not None:
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace").strip()
                if line.startswith("out_time_us=") and progress_cb is not None:
                    try:
                        cur_us = int(line.split("=", 1)[1])
                        fraction = min(1.0, max(0.0, cur_us / total_us))
                        _emit(
                            progress_cb, "encode",
                            int(round(fraction * total_frames)), total_frames,
                        )
                    except ValueError:
                        pass
                if line == "progress=end":
                    break
        stderr_bytes = proc.stderr.read() if proc.stderr else b""
    finally:
        proc.wait()
    if proc.returncode != 0:
        tail = stderr_bytes.decode("utf-8", errors="replace").strip().splitlines()[-12:]
        msg = "\n  ".join(tail) if tail else "(no stderr captured)"
        raise RuntimeError(f"ffmpeg stage encode failed (rc={proc.returncode}):\n  {msg}")


def export_clip(
    source_path: Path,
    start: float,
    end: float,
    output_name: str,
    transcript_path: Path | None = None,
    progress_cb: ProgressCB | None = None,
    caption_style: str | None = None,
    hook_title: str | None = None,
    caption_margin_v: int | None = None,
    identity_id: int | None = None,
    zoom_level: str | None = None,
    lock_camera: bool = False,
) -> dict:
    out_path = settings.data_clips_dir / output_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stage_mode = (zoom_level == "stage")

    with tempfile.TemporaryDirectory() as tmp:
        _emit(progress_cb, "extract", 0, 0)
        temp_clip = Path(tmp) / "clip.mp4"
        _ffmpeg_extract(source_path, start, end, temp_clip)

        # Captions are independent of framing mode. Build the ASS once and
        # let either encode path burn it in.
        ass_path: Path | None = None
        n_caption_words = 0
        clip_duration = end - start
        has_words = False
        words: list[captions.Word] = []
        if transcript_path is not None and transcript_path.is_file():
            transcript = json.loads(transcript_path.read_text())
            words = captions.words_in_range(transcript, start, end)
            has_words = bool(words)
        if has_words or hook_title:
            ass_text = captions.generate_ass(
                words, OUT_W, OUT_H, style=caption_style,
                hook_title=hook_title, clip_duration=clip_duration,
                caption_margin_v=caption_margin_v,
            )
            ass_path = Path(tmp) / "captions.ass"
            ass_path.write_text(ass_text, encoding="utf-8")
            n_caption_words = len(words)

        if stage_mode:
            # Stage skips the face scan entirely — no per-frame crop motion,
            # whole source frame is shown.  Probe the extracted clip for fps
            # so the progress callback has a sensible frame total.
            probe = av.open(str(temp_clip))
            vstream = probe.streams.video[0]
            src_w_p, src_h_p = vstream.width, vstream.height
            fps_p = float(vstream.average_rate)
            probe.close()
            total_frames = max(1, int(round(clip_duration * fps_p)))
            _emit(progress_cb, "encode", 0, total_frames)
            _encode_stage(
                temp_clip, out_path, ass_path,
                progress_cb=progress_cb, total_frames=total_frames,
                duration_seconds=clip_duration,
            )
            _emit(progress_cb, "encode", total_frames, total_frames)
            return {
                "source": source_path.name,
                "start": start,
                "end": end,
                "output": str(out_path),
                "src_resolution": f"{src_w_p}x{src_h_p}",
                "fps": fps_p,
                "n_frames": total_frames,
                "detected": 0,
                "sampled": 0,
                "detection_rate": 0.0,
                "scene_cuts": 0,
                "captioned": ass_path is not None,
                "n_caption_words": n_caption_words,
                "identity_id": None,
                "zoom_level": "stage",
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }

        # Face-tracked modes (tight / medium / wide / default) -- existing path.
        _emit(progress_cb, "scan", 0, 1)
        scan = scan_for_clip(source_path, start, end, identity_id=identity_id)
        _emit(progress_cb, "scan", 1, 1)

        per_frame_faces = _expand_to_per_frame(
            scan["n_frames"], scan["faces"], scan.get("sample_offset_frames", 0),
        )
        track = _segment_crop_track(
            scan["n_frames"], scan["src_w"], scan["src_h"],
            per_frame_faces, scan["cuts"],
            face_to_crop_h=resolve_zoom(zoom_level),
            lock_camera=lock_camera,
        )

        _emit(progress_cb, "encode", 0, scan["n_frames"])
        _encode(
            temp_clip, track, scan["src_w"], scan["src_h"], scan["fps"], out_path, ass_path,
            progress_cb=progress_cb, total_frames=scan["n_frames"],
        )
        _emit(progress_cb, "encode", scan["n_frames"], scan["n_frames"])

    detected = sum(1 for f in scan["faces"] if f is not None)
    return {
        "source": source_path.name,
        "start": start,
        "end": end,
        "output": str(out_path),
        "src_resolution": f"{scan['src_w']}x{scan['src_h']}",
        "fps": scan["fps"],
        "n_frames": scan["n_frames"],
        "detected": detected,
        "sampled": len(scan["faces"]),
        "detection_rate": detected / max(1, len(scan["faces"])),
        "scene_cuts": len(scan["cuts"]) - 1,
        "captioned": ass_path is not None,
        "n_caption_words": n_caption_words,
        "identity_id": identity_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
