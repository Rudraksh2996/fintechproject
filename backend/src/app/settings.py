"""Gateway process settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    demo_mode: bool = True
    origin: str = "http://localhost:8080"
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    replay_enabled: bool = True
    replay_speed: float = Field(default=1, gt=0)
    database_timeout_seconds: float = Field(default=10, gt=0, le=120)
