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
    max_items_per_sector: int = Field(default=24, alias="MAX_ITEMS_PER_SECTOR")
    max_items_per_domain_per_sector: int = Field(default=3, alias="MAX_ITEMS_PER_DOMAIN_PER_SECTOR")
    min_items_per_sector_target: int = Field(default=6, alias="MIN_ITEMS_PER_SECTOR_TARGET")
    min_items_per_local_subtopic: int = Field(default=6, alias="MIN_ITEMS_PER_LOCAL_SUBTOPIC")
    min_story_score: float = Field(default=1.0, alias="MIN_STORY_SCORE")
    min_social_story_score: float = Field(default=3.0, alias="MIN_SOCIAL_STORY_SCORE")
    min_social_mentions: int = Field(default=3, alias="MIN_SOCIAL_MENTIONS")
    normal_story_window_hours: int = Field(default=24, alias="NORMAL_STORY_WINDOW_HOURS")
    hot_story_window_hours: int = Field(default=48, alias="HOT_STORY_WINDOW_HOURS")
    max_story_age_hours: int = Field(default=48, alias="MAX_STORY_AGE_HOURS")
    run_ingestion_on_startup: bool = Field(default=False, alias="RUN_INGESTION_ON_STARTUP")
    hard_relevance_gate_enabled: bool = Field(default=True, alias="HARD_RELEVANCE_GATE_ENABLED")
    job_stale_after_minutes: int = Field(default=20, alias="JOB_STALE_AFTER_MINUTES")
    pipeline_lock_file: str = Field(default="/tmp/newsdash_pipeline.lock", alias="PIPELINE_LOCK_FILE")
    fetch_max_runtime_seconds: int = Field(default=480, alias="FETCH_MAX_RUNTIME_SECONDS")
    feed_fetch_timeout_seconds: int = Field(default=8, alias="FEED_FETCH_TIMEOUT_SECONDS")
    fetch_max_workers: int = Field(default=16, alias="FETCH_MAX_WORKERS")
    max_entries_per_feed: int = Field(default=20, alias="MAX_ENTRIES_PER_FEED")
    max_raw_stories_per_run: int = Field(default=2200, alias="MAX_RAW_STORIES_PER_RUN")
    min_direct_feed_raw_stories: int = Field(default=900, alias="MIN_DIRECT_FEED_RAW_STORIES")
    direct_feed_raw_share: float = Field(default=0.55, alias="DIRECT_FEED_RAW_SHARE")
    scoring_explain_log_limit: int = Field(default=8, alias="SCORING_EXPLAIN_LOG_LIMIT")

    def resolved_source_config_path(self) -> Path:
        return Path(self.source_config_path).expanduser().resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
