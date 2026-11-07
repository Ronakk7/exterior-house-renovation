"""Configuration loading and validation via Pydantic BaseSettings."""

from typing import List
from pathlib import Path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Immutable application settings loaded from environment variables and .env file."""

    APP_ENV: str = "development"
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    WEENY_DATA_DIR: str = ""
    DATABASE_PATH: str = "data/app.db"
    STORAGE_ROOT: str = "storage"
    CATALOGUE_PATH: str = "backend/app/data/catalogue.json"
    FRONTEND_DIR: str = "frontend"

    ALLOWED_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"

    MAX_UPLOAD_MB: int = 10
    ALLOWED_IMAGE_TYPES: str = "image/jpeg,image/png,image/webp"
    MIN_IMAGE_SHORT_SIDE_PX: int = 600
    MAX_PHOTOS_PER_PROJECT: int = Field(default=1, ge=1, le=3)
    MAX_IMAGE_PIXELS: int = Field(default=40_000_000, ge=1)
    MAX_COMPONENTS_PER_PHOTO: int = Field(default=60, ge=1)

    CURRENCY: str = "INR"
    CURRENCY_SYMBOL: str = "₹"

    GEMINI_API_KEY: str = ""
    GEMINI_VISION_MODEL: str = ""
    NANO_BANANA_IMAGE_MODEL: str = ""
    AI_MOCK_MODE: bool = False
    AI_MOCK_SCENARIO: str = "ok"
    AI_WORKING_IMAGE_MAX_PX: int = 1600
    AI_DETECTION_TIMEOUT_S: int = Field(default=60, ge=5)
    AI_IMAGE_TIMEOUT_S: int = Field(default=120, ge=5)
    AI_MAX_RETRIES: int = Field(default=1, ge=0)

    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=("backend/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    @field_validator("APP_ENV")
    @classmethod
    def validate_app_env(cls, v: str) -> str:
        if v not in {"development", "production"}:
            raise ValueError("APP_ENV must be 'development' or 'production'")
        return v

    @field_validator(
        "MAX_UPLOAD_MB",
        "MIN_IMAGE_SHORT_SIDE_PX",
        "AI_WORKING_IMAGE_MAX_PX",
    )
    @classmethod
    def validate_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Must be a positive integer")
        return v

    @model_validator(mode="after")
    def validate_configuration(self) -> "Settings":
        if self.WEENY_DATA_DIR.strip():
            data_dir = Path(self.WEENY_DATA_DIR).expanduser()
            object.__setattr__(self, "DATABASE_PATH", str(data_dir / "app.db"))
            object.__setattr__(self, "STORAGE_ROOT", str(data_dir / "storage"))

        if self.AI_MOCK_MODE and self.AI_MOCK_SCENARIO not in {
            "ok",
            "unusable",
            "no_components",
            "invalid_json",
            "blocked",
            "timeout",
            "rate_limited",
        }:
            raise ValueError(
                f"Unknown AI_MOCK_SCENARIO: {self.AI_MOCK_SCENARIO}"
            )
        if self.APP_ENV == "production" and "*" in self.allowed_origins_list:
            raise ValueError("ALLOWED_ORIGINS must not contain '*' in production")
        return self

    @property
    def ai_configured(self) -> bool:
        """Return True if mock mode is on or all required AI credentials are set."""
        if self.AI_MOCK_MODE:
            return True
        return bool(
            self.GEMINI_API_KEY.strip()
            and self.GEMINI_VISION_MODEL.strip()
            and self.NANO_BANANA_IMAGE_MODEL.strip()
        )

    @property
    def allowed_origins_list(self) -> List[str]:
        """Parsed list of allowed CORS origins."""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def allowed_image_types_list(self) -> List[str]:
        """Parsed list of accepted image MIME types."""
        return [mime.strip() for mime in self.ALLOWED_IMAGE_TYPES.split(",") if mime.strip()]
