"""Read the requesting user's identity from Tailscale Serve headers.

Tailscale's funnel/serve proxy injects three headers on requests it forwards:
  Tailscale-User-Login        (e.g. bob@gmail.com)
  Tailscale-User-Name         (display name)
  Tailscale-User-Profile-Pic  (avatar URL)

Headers are absent for requests that don't go through Tailscale Serve
(e.g. localhost on the streaming PC itself, or a direct hit on the tailnet
IP without ``tailscale serve`` in front). In those cases we return a
None-shaped record and callers fall back to anonymous behavior.

Admin status is granted three ways, checked in this order:
 1. Tailscale login matches an entry in ``ADMIN_TAILSCALE_LOGINS`` — preferred
    for tailnet access; no shared password to leak.
 2. Session cookie via ``ADMIN_PASSWORD`` flow — for typed-in admin escalation.
 3. Loopback fallback: requests from 127.0.0.1 / ::1 with NO Tailscale
    identity headers are treated as the operator at the keyboard. Tailscale
    Serve forwards from loopback too, but it always sets identity headers,
    so a header-less loopback request is genuinely "the local console" —
    no password needed to do admin things.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.config import settings


_LOOPBACK_HOSTS = {"127.0.0.1", "::1"}


@dataclass
class User:
    login: str | None
    name: str | None
    profile_pic: str | None
    admin: bool

    @property
    def is_anonymous(self) -> bool:
        return self.login is None


def _admin_logins() -> set[str]:
    raw = (settings.admin_tailscale_logins or "").strip()
    if not raw:
        return set()
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _is_loopback(request: Request) -> bool:
    client = request.client
    return client is not None and client.host in _LOOPBACK_HOSTS


def get_user(request: Request) -> User:
    login = request.headers.get("tailscale-user-login")
    name = request.headers.get("tailscale-user-name")
    pic = request.headers.get("tailscale-user-profile-pic")
    # Treat blank/None the same way; clients sometimes send empty strings.
    login = login.strip() if login else None
    name = name.strip() if name else None
    pic = pic.strip() if pic else None

    cookie_admin = bool(request.session.get("admin")) if "session" in request.scope else False
    identity_admin = bool(login and login.lower() in _admin_logins())
    # Loopback fallback: only fires when no Tailscale identity exists,
    # so a Tailscale-Serve-forwarded request always gets evaluated against
    # ADMIN_TAILSCALE_LOGINS rather than auto-promoted.
    loopback_admin = login is None and _is_loopback(request)

    return User(
        login=login,
        name=name,
        profile_pic=pic,
        admin=cookie_admin or identity_admin or loopback_admin,
    )
