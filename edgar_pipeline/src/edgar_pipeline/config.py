"""Validated environment configuration shared by ingestion and migrations."""

import re

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    demo_mode: bool = True
    seed: int = 42
    sec_user_agent: str = ""
    sec_max_rps: float = Field(default=8, gt=0, le=10)
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "fintech"
    postgres_app_user: str = "fintech_app"
    postgres_app_password: SecretStr
    postgres_user: str = "fintech_admin"
    postgres_password: SecretStr
    workbench_ro_password: SecretStr

    @model_validator(mode="after")
    def validate_sec_identity(self) -> "Settings":
        if not self.demo_mode and not re.fullmatch(
            r"\S.+\s+[^\s@]+@[^\s@]+\.[^\s@]+", self.sec_user_agent
        ):
            raise ValueError("Live mode requires SEC_USER_AGENT='YourOrg contact@example.com'")
        return self

    def database_url(self, *, admin: bool = False, readonly: bool = False) -> URL:
        if admin and readonly:
            raise ValueError("Choose either the migration role or read-only role")
        user = self.postgres_app_user
        password = self.postgres_app_password
        if admin:
            user, password = self.postgres_user, self.postgres_password
        elif readonly:
            user, password = "workbench_ro", self.workbench_ro_password
        return URL.create(
            "postgresql+psycopg",
            username=user,
            password=password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
