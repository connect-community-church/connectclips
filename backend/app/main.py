from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.routers import jobs as jobs_router
from app.routers import sermons as sermons_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (settings.data_sources_dir, settings.data_work_dir, settings.data_clips_dir):
        d.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="ConnectClips", lifespan=lifespan)
app.include_router(sermons_router.router)
app.include_router(jobs_router.router)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "sources_dir": str(settings.data_sources_dir),
        "work_dir": str(settings.data_work_dir),
        "clips_dir": str(settings.data_clips_dir),
        "whisper_model": settings.whisper_model,
        "claude_model": settings.claude_model,
    }
