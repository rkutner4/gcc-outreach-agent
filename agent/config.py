"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"

    # ZoomInfo
    zoominfo_client_id: str = ""
    zoominfo_client_secret: str = ""
    zoominfo_username: str = ""
    zoominfo_password: str = ""

    # Gmail
    gmail_credentials_path: str = "credentials/gmail_client_secret.json"
    gmail_token_path: str = "credentials/gmail_token.json"

    # Identity / outreach
    sender_name: str = "Your Name"
    sender_firm: str = "Your Firm"
    sender_email: str = ""
    mailing_address: str = "Your physical mailing address"
    outreach_pitch: str = (
        "Brief description of what you offer to GCC institutional investors"
    )

    # Caps
    email_daily_cap: int = 70
    whatsapp_daily_cap: int = 30

    # Pipeline
    dry_run: bool = True
    company_confidence_threshold: float = 0.55
    contact_confidence_threshold: float = 0.6
    pipeline_paused: bool = False

    # Optional
    khaleeji_api_key: str = ""

    # DB
    database_url: str = f"sqlite:///{(ROOT_DIR / 'data' / 'outreach.db').as_posix()}"

    # Target geography (fixed for this product)
    target_countries: tuple[str, ...] = ("UAE", "KSA", "Kuwait", "Bahrain")
    target_uae_cities: tuple[str, ...] = ("Abu Dhabi", "Dubai")

    @property
    def root_dir(self) -> Path:
        return ROOT_DIR

    @property
    def data_dir(self) -> Path:
        return ROOT_DIR / "data"

    @property
    def imports_accounts_dir(self) -> Path:
        return ROOT_DIR / "imports" / "accounts"

    @property
    def imports_leads_dir(self) -> Path:
        return ROOT_DIR / "imports" / "leads"

    @property
    def templates_dir(self) -> Path:
        return ROOT_DIR / "templates"

    @property
    def whatsapp_session_dir(self) -> Path:
        return ROOT_DIR / "data" / "whatsapp_session"


@lru_cache
def get_settings() -> Settings:
    return Settings()
