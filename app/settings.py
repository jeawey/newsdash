from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="dev", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    database_url: str = Field(default="sqlite:///./news_dashboard.sqlite3", alias="DATABASE_URL")
    timezone: str = Field(default="Europe/Madrid", alias="TIMEZONE")

    source_config_path: str = Field(default="config/sources.yml", alias="SOURCE_CONFIG_PATH")

    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")

    hourly_breaking_threshold: float = Field(default=7.0, alias="HOURLY_BREAKING_THRESHOLD")
    max_items_per_sector: int = Field(default=12, alias="MAX_ITEMS_PER_SECTOR")
    max_story_age_hours: int = Field(default=72, alias="MAX_STORY_AGE_HOURS")

    def resolved_source_config_path(self) -> Path:
        return Path(self.source_config_path).expanduser().resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
