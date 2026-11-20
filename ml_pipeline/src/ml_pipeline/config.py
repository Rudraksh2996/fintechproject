"""Graph storage configuration; credentials are supplied only by the environment."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GraphSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    seed: int = 42
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_auth: SecretStr
    mule_scale: str = Field(default="lite", pattern="^(lite|demo|full)$")
    torch_num_threads: int = Field(default=4, ge=1)
    gnn_arch: str = Field(default="graphsage", pattern="^(graphsage|gatv2)$")
    risk_alert_threshold: float = Field(default=0.8, ge=0, le=1)
    reporting_threshold: float = Field(default=10000, gt=0)
