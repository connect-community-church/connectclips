"""Identity endpoint — who is the current request authenticated as?

Returns Tailscale identity (when forwarded via Tailscale Serve) plus the
admin flag. Frontend calls this on app load to render the header and
decide whether to show admin features without a password prompt.
"""

from fastapi import APIRouter, Request

from app.identity import get_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def me(request: Request) -> dict:
    u = get_user(request)
    return {
        "login": u.login,
        "name": u.name,
        "profile_pic": u.profile_pic,
        "admin": u.admin,
        "anonymous": u.is_anonymous,
    }
