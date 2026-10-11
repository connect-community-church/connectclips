"""Admin-configurable clip-selection settings.

GET is open (the Settings view and the clip-selection service both read it).
PUT is admin-only -- tuning how clips are picked is an ops decision, not a
per-volunteer choice. Mirrors routers/publish_targets.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.routers.auth import require_admin
from app.services import app_settings


router = APIRouter(prefix="/app-settings", tags=["app-settings"])


class AppSettingsIn(BaseModel):
    clip_thinking_effort: str | None = None
    clip_max_output_tokens: int | None = None
    num_clips_min: int | None = None
    num_clips_max: int | None = None


@router.get("")
def get_app_settings() -> dict:
    return app_settings.load()


@router.put("", dependencies=[Depends(require_admin)])
def put_app_settings(body: AppSettingsIn) -> dict:
    return app_settings.save(body.model_dump())
