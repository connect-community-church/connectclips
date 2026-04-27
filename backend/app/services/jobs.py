"""In-memory job store with serialized async execution.

Jobs survive only for the lifetime of the process. Transcripts themselves
are persisted to disk by the transcribe service, so a process restart loses
the job log but not the work product — the API can re-detect completed work
by checking whether the transcript file exists.

Only one transcribe job runs at a time; the WhisperModel and 8 GB of VRAM
don't accommodate concurrent inference safely.
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
from app.services import transcribe

JobStatus = Literal["queued", "running", "done", "failed"]


@dataclass
class Job:
    id: str
    source: str
    status: JobStatus = "queued"
    created_at: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    transcript_path: str | None = None


_jobs: dict[str, Job] = {}
_run_lock = asyncio.Lock()


def list_jobs() -> list[Job]:
    return sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def job_dict(job: Job) -> dict:
    return asdict(job)


def create_transcribe_job(source_name: str) -> Job:
    src = settings.data_sources_dir / source_name
    if not src.is_file():
        raise FileNotFoundError(f"source not found: {source_name}")
    job = Job(id=uuid.uuid4().hex[:12], source=source_name)
    _jobs[job.id] = job
    asyncio.create_task(_run(job, src))
    return job


async def _run(job: Job, src: Path) -> None:
    async with _run_lock:
        job.status = "running"
        job.started_at = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            transcript = await asyncio.to_thread(transcribe.transcribe_file, src)
            out = await asyncio.to_thread(transcribe.write_transcript, transcript)
            job.transcript_path = str(out)
            job.status = "done"
        except Exception as exc:
            job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            job.status = "failed"
        finally:
            job.finished_at = dt.datetime.now(dt.timezone.utc).isoformat()
