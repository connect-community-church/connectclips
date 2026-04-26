from fastapi import FastAPI

from app.config import settings

app = FastAPI(title="ConnectClips")


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
