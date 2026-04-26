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


settings = Settings()
