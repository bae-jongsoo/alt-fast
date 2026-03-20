from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://alt:alt@localhost:5432/alt"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24

    # Admin
    ADMIN_ID: str = "admin"
    ADMIN_PW: str = "admin"

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")


settings = Settings()
