from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


class CreateJobRequest(BaseModel):
    source: str


@router.get("")
def list_jobs() -> list[dict]:
    return [jobs.job_dict(j) for j in jobs.list_jobs()]


@router.post("", status_code=201)
async def create_job(body: CreateJobRequest) -> dict:
    try:
        job = jobs.create_transcribe_job(body.source)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return jobs.job_dict(job)


@router.get("/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return jobs.job_dict(job)
