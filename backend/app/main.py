from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware


class SPAStaticFiles(StaticFiles):
    """StaticFiles subclass for a Vite SPA with History-API routing:

    - ``index.html`` (the document referenced for /any/route/) must be
      revalidated every load. Vite builds it with content-hashed asset URLs
      embedded inside, so a stale index.html points at a stale bundle even
      after a deploy.
    - Files under ``/assets/`` are content-addressed (filename includes a
      hash of the contents). They're effectively immutable, so we let the
      browser cache them forever.
    - Deep client-side routes (e.g. ``/sermons/foo.mp4``,
      ``/sermons/foo.mp4/clip/2``) don't match any real file, so we fall
      back to ``index.html`` for any 404 inside the SPA mount. The SPA's
      router then takes over on the client. API and /files mounts are
      registered before this catch-all so they still win for their paths.

    Result: no "hard-refresh after every backend restart" tax, AND deep
    links / refresh-on-deep-link work without leaving the SPA at /.
    """

    async def get_response(self, path, scope):
        # Starlette's StaticFiles raises HTTPException(404) for missing files
        # rather than returning a Response with status 404 — catch both cases.
        from starlette.exceptions import HTTPException as StarletteHTTPException
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                response = await super().get_response("index.html", scope)
                response.headers["Cache-Control"] = "no-cache, must-revalidate"
                return response
            raise
        if response.status_code == 404:
            response = await super().get_response("index.html", scope)
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
            return response
        if path in ("index.html", "."):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

from app import db
from app import platform as plat
from app.config import settings
from app.routers import auth as auth_router
from app.routers import jobs as jobs_router
from app.routers import me as me_router
from app.routers import sermons as sermons_router
from app.routers import usage as usage_router
from app.services import captions

# repo root → frontend/dist (built SPA)
_SPA_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (settings.data_sources_dir, settings.data_work_dir, settings.data_clips_dir):
        d.mkdir(parents=True, exist_ok=True)
    db.init()
    # Run hardware detection on the main thread BEFORE any worker thread
    # could spawn. Lazy detection from inside an export worker historically
    # caused encode-thread hangs (CUDA context initialized in the wrong
    # context, or ctranslate2 import racing with the ffmpeg subprocess).
    plat.initialize()
    # Static mounts must be added before the SPA catch-all below, so they take priority
    app.mount("/files/sources", StaticFiles(directory=settings.data_sources_dir), name="sources")
    app.mount("/files/clips", StaticFiles(directory=settings.data_clips_dir), name="clips")
    # Serve the built SPA at / when frontend/dist exists. In dev (no build), Vite is
    # the front door instead and this mount is skipped, so :8765 returns 404 for
    # non-API paths.
    if _SPA_DIST.is_dir():
        app.mount("/", SPAStaticFiles(directory=_SPA_DIST, html=True), name="spa")
    yield


app = FastAPI(title="ConnectClips", lifespan=lifespan)

# Vite dev server runs on a different origin during development; in production
# (Tailscale) frontend is served from the same origin. Allow only the Vite
# dev origins by default and require credentials so the admin session cookie
# can ride along on cross-origin fetches during development.
_DEV_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEV_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sign + encrypt the admin-mode session cookie. SESSION_SECRET must be set in .env;
# without it we'd silently fall back to a default and admin mode could be forged.
if not settings.session_secret:
    raise RuntimeError(
        "SESSION_SECRET is empty. Set it in backend/.env "
        "(generate via: python -c 'import secrets; print(secrets.token_urlsafe(32))')."
    )
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="cc_admin",
    https_only=False,  # local LAN over Tailscale; no TLS termination yet
    same_site="lax",
    max_age=8 * 3600,  # 8 hours
)

# All API routes live under /api so the frontend can call them via the same
# convention in dev (Vite proxies /api → backend) and in prod (FastAPI serves
# both API and SPA on one port).
_API_PREFIX = "/api"
app.include_router(auth_router.router, prefix=_API_PREFIX)
app.include_router(me_router.router, prefix=_API_PREFIX)
app.include_router(sermons_router.router, prefix=_API_PREFIX)
app.include_router(jobs_router.router, prefix=_API_PREFIX)
app.include_router(usage_router.router, prefix=_API_PREFIX)


@app.get(f"{_API_PREFIX}/caption-styles")
def caption_styles() -> dict:
    return {"styles": captions.list_styles(), "default": captions.DEFAULT_STYLE}


@app.get(f"{_API_PREFIX}/health")
def health() -> dict:
    return {
        "status": "ok",
        "sources_dir": str(settings.data_sources_dir),
        "work_dir": str(settings.data_work_dir),
        "clips_dir": str(settings.data_clips_dir),
        "whisper_model": settings.whisper_model,
        "claude_model": settings.claude_model,
        "spa_built": _SPA_DIST.is_dir(),
        # What the platform helper auto-detected at startup.
        "platform": plat.summary(),
    }
