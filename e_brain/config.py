import os
from dataclasses import dataclass
from typing import Optional

from .util.env import load_dotenv_if_present


@dataclass(frozen=True)
class Settings:
    # Core
    env: str
    dry_run: bool

    # OpenAI
    openai_api_key: Optional[str]
    embedding_model: str
    chat_model: str

    # DB
    database_url: str
    embedding_dim: int

    # X API (read)
    x_bearer_token: Optional[str]

    # X API (write) – user context
    x_api_key: Optional[str]
    x_api_secret: Optional[str]
    x_access_token: Optional[str]
    x_access_token_secret: Optional[str]

    # Scheduling
    post_windows_us: str
    post_windows_eu: str


def get_settings() -> Settings:
    load_dotenv_if_present()
    env = os.getenv("ENV", "development").lower()
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"

    return Settings(
        env=env,
        dry_run=dry_run,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        chat_model=os.getenv("CHAT_MODEL", "gpt-4o-mini"),
        database_url=os.getenv("DATABASE_URL", "postgresql://localhost/e_brain"),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "1536")),
        x_bearer_token=os.getenv("X_BEARER_TOKEN"),
        x_api_key=os.getenv("X_API_KEY"),
        x_api_secret=os.getenv("X_API_SECRET"),
        x_access_token=os.getenv("X_ACCESS_TOKEN"),
        x_access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
        post_windows_us=os.getenv("POST_WINDOWS_US", "09:00-12:00,17:00-19:00"),
        post_windows_eu=os.getenv("POST_WINDOWS_EU", "08:00-11:00,18:00-20:00"),
    )

