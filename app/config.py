from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── LLM ──────────────────────────────────────────────────────────────────
    llm_provider: str = Field(default="groq", description="groq | gemini")
    groq_api_key: str = Field(default="", description="Groq API key")
    gemini_api_key: str = Field(default="", description="Gemini API key")
    llm_model: str = Field(default="openai/gpt-oss-120b")

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(description="PostgreSQL connection URL")

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg://", 1)
        return v

    # ── Auth ──────────────────────────────────────────────────────────────────
    service_api_key: str = Field(description="Shared secret for /tickets endpoints")
    human_jwt_secret: str = Field(description="JWT signing secret for human agents")
    cors_origins: str = Field(default="http://localhost:8501")

    # ── Policy (server-enforced) ──────────────────────────────────────────────
    refund_cap_cents: int = Field(default=100_000, description="Max auto-refund in paise/cents (₹1000.00)")
    max_tool_calls_per_ticket: int = Field(default=5)
    max_refunds_per_ticket: int = Field(default=1)

    # ── n8n — outbound notification webhook only (§1.1) ───────────────────────
    n8n_webhook_url: str = Field(default="", description="n8n webhook URL for notifications")
    n8n_webhook_secret: str = Field(default="", description="Header secret for n8n webhook")

    # ── Cognee — memory recall/store only (§13) ───────────────────────────────
    cognee_llm_provider: str = Field(default="groq")
    cognee_llm_api_key: str = Field(default="")
    cognee_llm_model: str = Field(default="llama-3.3-70b-versatile")

    # ── Logging & env ─────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
