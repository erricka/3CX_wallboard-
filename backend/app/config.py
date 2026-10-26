from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # 3CX XAPI credentials (Admin Console > Integrations > API)
    threecx_base_url: str = "https://maxbit.3cx.asia"
    threecx_client_id: str
    threecx_client_secret: str
    threecx_verify_ssl: bool = True

    database_url: str = "postgresql+asyncpg://wallboard:wallboard@localhost:5432/wallboard"

    # Timezone of the call center; "today" / "yesterday" are calculated in this zone.
    timezone: str = "Asia/Phnom_Penh"
    # Comma separated queue numbers to show, e.g. "800,801". Empty = all queues.
    wallboard_queues: str = ""

    poll_interval_seconds: float = 3
    stats_refresh_seconds: float = 60
    # "Unanswered within N sec" column threshold.
    slow_answer_seconds: int = 5
    # Days of history to pull into Postgres at startup so reports are instant.
    backfill_days: int = 31

    cors_origins: str = "http://localhost:5173"
    # Built React app to serve at "/" (set in the Docker image); empty = API only.
    static_dir: str = ""

    @field_validator("database_url")
    @classmethod
    def use_asyncpg(cls, url: str) -> str:
        # Hosting providers hand out postgres:// or postgresql:// URLs.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix):]
        return url

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def queue_filter(self) -> list[str]:
        return [q.strip() for q in self.wallboard_queues.split(",") if q.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
