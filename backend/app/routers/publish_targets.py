"""Admin-configurable publish-target IDs (which YouTube channel, which FB Page).

GET is open to anyone (the Publish view consumes it on every clip page).
PUT is admin-only -- changing where the church publishes from is an ops
decision, not a per-volunteer choice.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.routers.auth import require_admin
from app.services import publish_targets


router = APIRouter(prefix="/publish-targets", tags=["publish-targets"])


class PublishTargetsIn(BaseModel):
    youtube_channel_id: str | None = None
    facebook_page_id: str | None = None


@router.get("")
def get_publish_targets() -> dict:
    return publish_targets.load()


@router.put("", dependencies=[Depends(require_admin)])
def put_publish_targets(body: PublishTargetsIn) -> dict:
    return publish_targets.save(body.model_dump())
