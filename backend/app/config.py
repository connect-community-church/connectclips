from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_sources_dir: Path
    data_work_dir: Path
    data_clips_dir: Path

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"

    whisper_model: str = "large-v3"
    whisper_compute_type: str = "int8"
    whisper_device: str = "cuda"

    # Admin-mode password and the secret used to sign the admin session cookie.
    # If session_secret is empty, the SessionMiddleware will refuse to start —
    # set both in .env on first run.
    admin_password: str = ""
    session_secret: str = ""

    # Comma-separated Tailscale logins (emails) that get admin rights
    # automatically when their request carries Tailscale identity headers.
    # Falls back to the password flow if absent or if the request didn't come
    # through Tailscale Serve.
    admin_tailscale_logins: str = ""


settings = Settings()
