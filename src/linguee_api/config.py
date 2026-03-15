from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "LINGUEE_"}

    redis_url: str | None = None
    cache_ttl: int = 86400
    log_level: str = "INFO"
    log_format: str = "console"
    sentry_dsn: str | None = None
    rate_limit: str = "30/minute"
    api_key: str | None = None


settings = Settings()
