"""Admin-mode toggle.

Anonymous (default) is fine for everyone — only delete operations require
admin. Admin mode is established by POSTing the password to /auth/admin/enter,
which sets a signed session cookie. The cookie expires after 8 hours.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class AdminEnterRequest(BaseModel):
    password: str


def is_admin(request: Request) -> bool:
    return bool(request.session.get("admin"))


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="admin mode required")


@router.get("/admin/status")
def admin_status(request: Request) -> dict:
    return {"admin": is_admin(request)}


@router.post("/admin/enter")
def admin_enter(body: AdminEnterRequest, request: Request) -> dict:
    expected = settings.admin_password
    if not expected:
        # No admin password configured — refuse rather than silently allow.
        raise HTTPException(status_code=503, detail="admin password not configured on server")
    # constant-time compare so wrong-password timing can't leak the prefix
    if not secrets.compare_digest(body.password, expected):
        raise HTTPException(status_code=401, detail="incorrect password")
    request.session["admin"] = True
    return {"admin": True}


@router.post("/admin/exit")
def admin_exit(request: Request) -> dict:
    request.session.pop("admin", None)
    return {"admin": False}
