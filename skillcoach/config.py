import os
import re
from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    database_url: str
    telegram_token: str
    owner_id: int
    webhook_secret: str = ""
    groq_key: str = ""
    gemini_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    gemini_model: str = "gemini-2.5-flash"
    github_token: str = ""
    dashboard_repo: str = ""
    dashboard_path: str = "docs/data.json"
    dashboard_url: str = ""

    @classmethod
    def from_env(cls, *, webhook: bool = False) -> "Config":
        database = os.getenv("DATABASE_URL", "")
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        owner = os.getenv("OWNER_ID", os.getenv("CHAT_ID", ""))
        secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
        if not database.startswith(("postgresql://", "postgres://")):
            raise ConfigurationError("DATABASE_URL must be a private PostgreSQL connection URL.")
        if not token or not owner.isdecimal() or int(owner) <= 0:
            raise ConfigurationError("TELEGRAM_BOT_TOKEN and positive OWNER_ID are required.")
        if webhook and not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", secret):
            raise ConfigurationError("TELEGRAM_WEBHOOK_SECRET must contain 32-256 URL-safe characters.")
        repo = os.getenv("DASHBOARD_REPO", "")
        path = os.getenv("DASHBOARD_PATH", "docs/data.json")
        if repo and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ConfigurationError("DASHBOARD_REPO must be owner/repository.")
        if path.startswith("/") or any(p in ("", ".", "..") for p in path.split("/")):
            raise ConfigurationError("DASHBOARD_PATH must be a relative repository path.")
        return cls(
            database,
            token,
            int(owner),
            secret,
            os.getenv("GROQ_API_KEY", ""),
            os.getenv("GEMINI_API_KEY", ""),
            os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            os.getenv("GITHUB_TOKEN", ""),
            repo,
            path,
            os.getenv("DASHBOARD_URL", ""),
        )
