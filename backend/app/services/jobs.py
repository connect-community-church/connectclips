"""In-memory job store with serialized async execution.

Jobs survive only for the lifetime of the process. Work products (transcripts,
downloaded videos) are persisted to disk by the underlying services, so a
process restart loses the job log but not the artifacts.

Two job kinds:
  - "transcribe": runs faster-whisper on a file in sources/. Serialized via
    a GPU lock — one transcription at a time on the 8 GB card.
  - "youtube_download": runs yt-dlp to fetch a video into sources/. Network /
    disk bound; runs without a lock.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from app.config import settings
from app.services import ingest, transcribe

JobKind = Literal["transcribe", "youtube_download"]
JobStatus = Literal["queued", "running", "done", "failed"]


@dataclass
class Job:
    id: str
    kind: JobKind
    status: JobStatus = "queued"
    # transcribe fields
    source: str | None = None
    transcript_path: str | None = None
    # youtube_download fields
    url: str | None = None
    ingested_filename: str | None = None
    # common
    created_at: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


_jobs: dict[str, Job] = {}
_gpu_lock = asyncio.Lock()


def list_jobs() -> list[Job]:
    return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def job_dict(job: Job) -> dict:
    return asdict(job)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def create_transcribe_job(source_name: str) -> Job:
    src = settings.data_sources_dir / source_name
    if not src.is_file():
        raise FileNotFoundError(f"source not found: {source_name}")
    job = Job(id=_new_id(), kind="transcribe", source=source_name)
    _jobs[job.id] = job
    asyncio.create_task(_run_transcribe(job, src))
    return job


def create_youtube_download_job(url: str) -> Job:
    job = Job(id=_new_id(), kind="youtube_download", url=url)
    _jobs[job.id] = job
    asyncio.create_task(_run_youtube(job, url))
    return job


async def _start(job: Job) -> None:
    job.status = "running"
    job.started_at = dt.datetime.now(dt.timezone.utc).isoformat()


def _finish(job: Job, error: str | None = None) -> None:
    job.error = error
    job.status = "failed" if error else "done"
    job.finished_at = dt.datetime.now(dt.timezone.utc).isoformat()


async def _run_transcribe(job: Job, src: Path) -> None:
    async with _gpu_lock:
        await _start(job)
        try:
            transcript = await asyncio.to_thread(transcribe.transcribe_file, src)
            out = await asyncio.to_thread(transcribe.write_transcript, transcript)
            job.transcript_path = str(out)
            _finish(job)
        except Exception as exc:
            _finish(job, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")


async def _run_youtube(job: Job, url: str) -> None:
    await _start(job)
    try:
        out = await asyncio.to_thread(ingest.download_youtube, url, settings.data_sources_dir)
        job.ingested_filename = out.name
        _finish(job)
    except Exception as exc:
        _finish(job, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
