from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://alt:alt@localhost:5432/alt"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24

    # Naver API
    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""

    # KIS API
    KIS_APP_KEY: str = ""
    KIS_APP_SECRET: str = ""
    KIS_HTS_ID: str = ""
    KIS_ACCT_STOCK: str = ""

    # DART API
    DART_API_KEY: str = ""

    # Gemini (OpenAI 호환)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Webhook
    WEBHOOK_SECRET: str = ""

    # Admin
    ADMIN_ID: str = "admin"
    ADMIN_PW: str = "admin"

    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")


settings = Settings()
