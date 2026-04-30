from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.identity import get_user
from app.services import jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


class CreateJobRequest(BaseModel):
    source: str


@router.get("")
def list_jobs(limit: int = 200) -> list[dict]:
    return [jobs.job_dict(j) for j in jobs.list_jobs(limit=limit)]


@router.post("", status_code=201)
async def create_job(body: CreateJobRequest, request: Request) -> dict:
    u = get_user(request)
    try:
        job = jobs.create_transcribe_job(body.source, user_login=u.login, user_name=u.name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return jobs.job_dict(job)


class SelectClipsRequest(BaseModel):
    source: str
    num_clips_min: int = 3
    num_clips_max: int = 8


@router.post("/select-clips", status_code=201)
async def create_select_clips_job(body: SelectClipsRequest, request: Request) -> dict:
    u = get_user(request)
    try:
        job = jobs.create_select_clips_job(
            body.source, body.num_clips_min, body.num_clips_max,
            user_login=u.login, user_name=u.name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return jobs.job_dict(job)


class ExportClipRequest(BaseModel):
    source: str
    clip_index: int
    start_override: float | None = None
    end_override: float | None = None
    caption_style: str | None = None
    caption_margin_v: int | None = None
    include_hook_title: bool = True
    identity_id: int | None = None


@router.post("/export-clip", status_code=201)
async def create_export_clip_job(body: ExportClipRequest, request: Request) -> dict:
    u = get_user(request)
    try:
        job = jobs.create_export_clip_job(
            body.source, body.clip_index,
            start_override=body.start_override,
            end_override=body.end_override,
            caption_style=body.caption_style,
            caption_margin_v=body.caption_margin_v,
            include_hook_title=body.include_hook_title,
            identity_id=body.identity_id,
            user_login=u.login, user_name=u.name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return jobs.job_dict(job)


class UploadStartRequest(BaseModel):
    filename: str


@router.post("/upload-start", status_code=201)
def upload_start(body: UploadStartRequest, request: Request) -> dict:
    """Frontend-driven: register that a browser upload is starting so it
    appears in the activity log as 'running' for the duration."""
    u = get_user(request)
    job = jobs.create_upload_job(body.filename, user_login=u.login, user_name=u.name)
    return jobs.job_dict(job)


class UploadFinishRequest(BaseModel):
    job_id: str
    error: str | None = None


@router.post("/upload-finish")
def upload_finish(body: UploadFinishRequest) -> dict:
    job = jobs.finish_upload_job(body.job_id, error=body.error)
    if job is None:
        raise HTTPException(status_code=404, detail="upload job not found")
    return jobs.job_dict(job)


@router.get("/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return jobs.job_dict(job)
