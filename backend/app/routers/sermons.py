from __future__ import annotations

import asyncio
import datetime as dt
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.config import settings
from app.identity import get_user
from app.routers.auth import require_admin
from app.services import captions, clip_selection, ingest, jobs, reframe
from app.services.transcribe import transcript_path_for



router = APIRouter(prefix="/sermons", tags=["sermons"])

_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm"}
_AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus"}
_ALLOWED_EXTS = _VIDEO_EXTS | _AUDIO_EXTS


def _exported_clip_path(source_name: str, clip_index: int, clips_version: str | None) -> Path:
    """Versioned export filename (matches the scheme used by jobs.create_export_clip_job).

    `clips_version` may be None when called for legacy clips.json files that
    predate the version field — fall back to "legacy" so the path is
    deterministic and matches whatever was stamped on the job row.
    """
    short = (clips_version or "legacy")[:8]
    return settings.data_clips_dir / f"{Path(source_name).stem}-clip-{clip_index}-v{short}.mp4"


@router.get("")
def list_sermons() -> list[dict]:
    src_dir = settings.data_sources_dir
    if not src_dir.exists():
        return []
    out = []
    for p in sorted(src_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in _ALLOWED_EXTS:
            continue
        stat = p.stat()
        clips_path = clip_selection.clips_path_for(p.name)
        n_clips = 0
        if clips_path.exists():
            try:
                n_clips = len(json.loads(clips_path.read_text()).get("clips", []))
            except Exception:
                n_clips = 0
        out.append(
            {
                "name": p.name,
                "size_bytes": stat.st_size,
                "modified_at": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(),
                "transcribed": transcript_path_for(p.name).exists(),
                "clips_selected": clips_path.exists(),
                "n_clips": n_clips,
            }
        )
    return out


@router.get("/{name}/clip-track")
def get_clip_track(
    name: str, start: float, end: float, identity_id: int | None = None,
) -> dict:
    """Return the per-frame crop track for the given range over this sermon.

    Used by the trim view's preview pane: the frontend draws a 9:16 crop
    rectangle on the source player at the tracked position, and canvas-crops
    the source video to a vertical preview using the same coordinates.

    With the source-level prescan in place, this is a slice of the cached
    ``source_scan.json`` and returns ~instantly. If the source hasn't been
    prescanned yet (e.g. uploaded before the prescan job existed), the call
    triggers a synchronous full-source scan as a fallback — slow but only
    happens once per source."""
    src = settings.data_sources_dir / name
    if not src.is_file():
        raise HTTPException(status_code=404, detail=f"sermon not found: {name}")
    if end <= start:
        raise HTTPException(status_code=400, detail="end must be greater than start")
    return reframe.track_for_clip(src, start, end, identity_id=identity_id)


@router.get("/{name}/identities")
def get_identities(name: str) -> dict:
    """List identities tracked across this sermon's source. Returns an empty
    list if the source hasn't been prescanned yet — the UI can show a
    "scan running" state and re-poll. Each identity has a stable id used by
    the export and clip-track APIs to filter detections."""
    src = settings.data_sources_dir / name
    if not src.is_file():
        raise HTTPException(status_code=404, detail=f"sermon not found: {name}")
    identities = reframe.identities_for_source(src)
    return {
        "scanned": reframe.has_source_scan(src),
        "identities": identities,
    }


@router.get("/{name}/identities/{identity_id}/thumb.png")
def get_identity_thumb(name: str, identity_id: int):
    """Return a 192×192 PNG cropped from the source at the identity's
    highest-confidence sighting. Used by the face-picker strip in the trim
    view. Cached on disk under ``<work>/<stem>/identity_thumbs/<id>.png``."""
    from fastapi.responses import FileResponse
    src = settings.data_sources_dir / name
    if not src.is_file():
        raise HTTPException(status_code=404, detail=f"sermon not found: {name}")
    if not reframe.has_source_scan(src):
        raise HTTPException(status_code=409, detail="source not scanned yet")
    identities = reframe.identities_for_source(src)
    match = next((i for i in identities if i["id"] == identity_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"identity {identity_id} not found for {name}")
    thumb_path = settings.data_work_dir / Path(name).stem / "identity_thumbs" / f"{identity_id}.png"
    if not thumb_path.exists():
        try:
            reframe.extract_identity_thumb(
                src, match["thumb_frame_idx"], match["thumb_box"], thumb_path,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"thumb extract failed: {exc}")
    return FileResponse(str(thumb_path), media_type="image/png")


@router.get("/{name}/transcript-words")
def get_transcript_words(name: str, start: float = 0.0, end: float | None = None) -> dict:
    """Return word-level timings within [start, end] (clip-relative seconds).

    Used by the frontend live caption preview: the JS renderer fetches this
    once per (clip, range) and renders the chunks itself, no backend rendering
    required. Word offsets in the response are CLIP-RELATIVE so the frontend
    can map them directly against the source video's currentTime - start.
    """
    transcript_path = transcript_path_for(name)
    if not transcript_path.is_file():
        raise HTTPException(status_code=404, detail="transcript not found (run transcribe first)")
    transcript = json.loads(transcript_path.read_text())
    if end is None:
        end = float(transcript.get("duration") or 1e9)
    words = captions.words_in_range(transcript, start, end)
    return {
        "start": start,
        "end": end,
        "words": [{"text": w.text, "start": w.start, "end": w.end} for w in words],
    }


@router.get("/{name}/clips")
def get_clips(name: str) -> dict:
    clips_path = clip_selection.clips_path_for(name)
    if not clips_path.exists():
        raise HTTPException(status_code=404, detail="clips.json not found (run select-clips first)")
    data = json.loads(clips_path.read_text())
    current_version = data.get("clips_version")
    for i, clip in enumerate(data.get("clips", [])):
        # Current-version export: file exists at the versioned path.
        out = _exported_clip_path(name, i, current_version)
        # Most recent export of any version (used both for attribution and to
        # surface a stale export's download path when the current version has
        # nothing exported yet).
        last = jobs.latest_export_for_clip(name, i)
        is_current = out.exists()
        # Stale = there's a previous export but it was made against a different
        # clips_version. The volunteer can still download it, but it represents
        # a different clip range from what the current clips.json says clip i is.
        previous = None
        if last and last.output_clip_path:
            same_version = (
                current_version is not None
                and last.clips_version == current_version
            )
            if not same_version and Path(last.output_clip_path).exists():
                previous = {
                    "filename": Path(last.output_clip_path).name,
                    "start": last.start,
                    "end": last.end,
                    "exported_at": last.finished_at,
                    "by_name": last.user_name,
                }
        clip["exported"] = is_current
        clip["output_filename"] = out.name if is_current else None
        clip["stale_export"] = previous is not None and not is_current
        clip["previous_export"] = previous
        clip["last_exported_by_login"] = last.user_login if (last and is_current) else None
        clip["last_exported_by_name"] = last.user_name if (last and is_current) else None
        clip["last_exported_at"] = last.finished_at if (last and is_current) else None
    return data


@router.post("/upload", status_code=201)
async def upload_sermon(request: Request, file: UploadFile = File(...)) -> dict:
    """Async because the auto-pipeline schedules background tasks via
    asyncio.create_task — that requires a running event loop, which we only
    get inside an async route. (A previous sync version silently dropped the
    transcribe step: the job row was saved as 'queued' and never started.)"""
    if not file.filename or not ingest.is_allowed_upload_ext(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"unsupported file type; allowed: {sorted(_ALLOWED_EXTS)}",
        )
    out = await asyncio.to_thread(
        ingest.save_upload, file.file, file.filename, settings.data_sources_dir,
    )
    # Auto-pipeline: kick off transcribe → select-clips chain on uploaded file
    u = get_user(request)
    jobs._maybe_chain_transcribe(
        out.name, user_login=u.login, user_name=u.name,
    )
    return {"name": out.name, "size_bytes": out.stat().st_size}


class YoutubeIngestRequest(BaseModel):
    url: str


@router.post("/youtube", status_code=201)
async def ingest_youtube(body: YoutubeIngestRequest, request: Request) -> dict:
    u = get_user(request)
    job = jobs.create_youtube_download_job(body.url, user_login=u.login, user_name=u.name)
    return jobs.job_dict(job)


@router.post("/{name}/prescan", status_code=201, dependencies=[Depends(require_admin)])
def manual_prescan(name: str, request: Request) -> dict:
    """Admin-only: enqueue a face prescan for an existing source. Used for
    backfill — auto-chain runs prescans for newly-ingested sources, this
    covers the ones that were uploaded before the prescan job existed.

    No-op if the source already has a scan or a queued/running prescan job.
    """
    src = settings.data_sources_dir / name
    if not src.is_file():
        raise HTTPException(status_code=404, detail="sermon not found")
    if reframe.has_source_scan(src):
        return {"name": name, "status": "already_scanned"}
    u = get_user(request)
    try:
        job = jobs.create_prescan_job(name, user_login=u.login, user_name=u.name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return jobs.job_dict(job)


@router.delete("/{name}", dependencies=[Depends(require_admin)])
def delete_sermon(name: str) -> dict:
    # Reject any path traversal — `name` must be a plain filename in sources/.
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="invalid sermon name")
    src = settings.data_sources_dir / name
    if not src.is_file():
        raise HTTPException(status_code=404, detail="sermon not found")

    removed: list[str] = []
    # 1. Source file
    src.unlink()
    removed.append(str(src))

    # 2. Work dir (transcript.json, clips.json) keyed on stem
    stem = Path(name).stem
    work_dir = settings.data_work_dir / stem
    if work_dir.exists():
        shutil.rmtree(work_dir)
        removed.append(str(work_dir))

    # 3. Exported clips: <stem>-clip-*.mp4
    for clip_path in settings.data_clips_dir.glob(f"{stem}-clip-*.mp4"):
        clip_path.unlink()
        removed.append(str(clip_path))

    return {"name": name, "removed": removed, "removed_count": len(removed)}
