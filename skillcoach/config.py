import os
import re
from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    pass


DEFAULT_GROQ_MODELS = "openai/gpt-oss-120b,openai/gpt-oss-20b"
# Newer Google projects cannot call models that reached the LEGACY stage; keep current ones first.
DEFAULT_GEMINI_MODELS = "gemini-3.8-flash,gemini-3.5-flash,gemini-2.5-flash"


EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+")
DELIVERY_CHANNELS = ("telegram", "web")


def normalize_email(value) -> str | None:
    """A lowercase address if `value` is a plausible single email address, else None."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if len(value) <= 254 and EMAIL.fullmatch(value) else None


def model_chain(value: str) -> list[str]:
    """Comma-separated provider models in fallback order, without duplicates."""
    models = []
    for item in value.split(","):
        item = item.strip()
        if item and item not in models:
            models.append(item)
    return models


@dataclass(frozen=True)
class Config:
    database_url: str
    telegram_token: str
    owner_id: int
    webhook_secret: str = ""
    groq_key: str = ""
    gemini_key: str = ""
    groq_model: str = DEFAULT_GROQ_MODELS
    gemini_model: str = DEFAULT_GEMINI_MODELS
    github_token: str = ""
    dashboard_repo: str = ""
    dashboard_path: str = "docs/data.json"
    dashboard_url: str = ""
    max_learners: int = 10
    daily_ai_operations: int = 40
    bot_username: str = ""
    private_dashboard_url: str = ""
    narration_enabled: bool = False
    access_requests_enabled: bool = False
    labs_enabled: bool = True
    labs_template_repo: str = "Harshit975shukla/skillcoach-labs"
    labs_github_token: str = ""
    # Fallback while Telegram is unavailable: learners use the web app and receive email reminders.
    delivery_channel: str = "telegram"
    web_app_url: str = ""
    owner_email: str = ""
    email_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""

    @property
    def web_mode(self) -> bool:
        return self.delivery_channel == "web"

    @property
    def email_configured(self) -> bool:
        return bool(self.email_from and self.smtp_host and self.smtp_username and self.smtp_password)

    @classmethod
    def from_env(cls, *, webhook: bool = False) -> "Config":
        database = os.getenv("DATABASE_URL", "")
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        owner = os.getenv("OWNER_ID") or os.getenv("CHAT_ID", "")
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
        maximum = os.getenv("MAX_LEARNERS", "10")
        ai_limit = os.getenv("DAILY_AI_OPERATIONS", "40")
        username = os.getenv("TELEGRAM_BOT_USERNAME", "")
        private_dashboard = os.getenv("PRIVATE_DASHBOARD_URL", "")
        narration = os.getenv("NARRATION_ENABLED", "false").lower()
        requests_enabled = os.getenv("ACCESS_REQUESTS_ENABLED", "false").lower()
        groq_models = os.getenv("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODELS
        gemini_models = os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODELS
        for models in (groq_models, gemini_models):
            chain = model_chain(models)
            if not 1 <= len(chain) <= 4 or not all(
                re.fullmatch(r"[A-Za-z0-9._/:-]{1,100}", m) for m in chain
            ):
                raise ConfigurationError("GROQ_MODEL and GEMINI_MODEL must list one to four model names.")
        labs = os.getenv("LABS_ENABLED", "true").lower()
        labs_repo = os.getenv("LABS_TEMPLATE_REPO", "Harshit975shukla/skillcoach-labs")
        if labs not in ("true", "false"):
            raise ConfigurationError("LABS_ENABLED must be true or false.")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}", labs_repo):
            raise ConfigurationError("LABS_TEMPLATE_REPO must be owner/repository.")
        if requests_enabled not in ("true", "false"):
            raise ConfigurationError("ACCESS_REQUESTS_ENABLED must be true or false.")
        if narration not in ("true", "false"):
            raise ConfigurationError("NARRATION_ENABLED must be true or false.")
        if private_dashboard:
            from urllib.parse import urlsplit

            parsed_dashboard = urlsplit(private_dashboard)
            if (
                parsed_dashboard.scheme != "https"
                or not parsed_dashboard.hostname
                or parsed_dashboard.username
            ):
                raise ConfigurationError(
                    "PRIVATE_DASHBOARD_URL must be an HTTPS URL for the private Mini App."
                )
        if not maximum.isdecimal() or not 1 <= int(maximum) <= 100:
            raise ConfigurationError("MAX_LEARNERS must be between 1 and 100, including the owner.")
        if not ai_limit.isdecimal() or not 1 <= int(ai_limit) <= 200:
            raise ConfigurationError("DAILY_AI_OPERATIONS must be between 1 and 200 per learner.")
        if username and not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
            raise ConfigurationError("TELEGRAM_BOT_USERNAME must be the bot username, without @.")
        web = web_settings()
        return cls(
            database,
            token,
            int(owner),
            secret,
            os.getenv("GROQ_API_KEY", ""),
            os.getenv("GEMINI_API_KEY", ""),
            groq_models,
            gemini_models,
            os.getenv("GITHUB_TOKEN", ""),
            repo,
            path,
            os.getenv("DASHBOARD_URL", ""),
            int(maximum),
            int(ai_limit),
            username,
            private_dashboard,
            narration == "true",
            requests_enabled == "true",
            labs == "true",
            labs_repo,
            os.getenv("LABS_GITHUB_TOKEN", ""),
            **web,
        )


def web_settings() -> dict:
    """Web + email delivery settings. Everything is optional until DELIVERY_CHANNEL=web."""
    from urllib.parse import urlsplit

    channel = os.getenv("DELIVERY_CHANNEL", "").strip().lower() or "telegram"
    if channel not in DELIVERY_CHANNELS:
        raise ConfigurationError("DELIVERY_CHANNEL must be telegram or web.")
    url = os.getenv("WEB_APP_URL", "").strip().rstrip("/")
    owner_raw = os.getenv("OWNER_EMAIL", "").strip()
    sender = os.getenv("EMAIL_FROM", "").strip()
    host = os.getenv("SMTP_HOST", "").strip()
    port = os.getenv("SMTP_PORT", "").strip() or "587"
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    if url:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.path:
            raise ConfigurationError(
                "WEB_APP_URL must be the app's HTTPS origin, such as https://example.app."
            )
    owner = normalize_email(owner_raw) if owner_raw else ""
    if owner is None:
        raise ConfigurationError("OWNER_EMAIL must be one email address.")
    if any(ch in sender for ch in "\r\n") or len(sender) > 200:
        raise ConfigurationError("EMAIL_FROM must be a single line.")
    if sender and normalize_email(sender.rsplit("<", 1)[-1].rstrip(">")) is None:
        raise ConfigurationError("EMAIL_FROM must be an address, optionally as Name <address>.")
    if host and not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
        raise ConfigurationError("SMTP_HOST must be a host name.")
    if not port.isdecimal() or int(port) not in (465, 587, 2525):
        raise ConfigurationError("SMTP_PORT must be 587 (STARTTLS), 465 (TLS) or 2525.")
    if channel == "web":
        missing = [
            name
            for name, value in (
                ("WEB_APP_URL", url),
                ("OWNER_EMAIL", owner),
                ("EMAIL_FROM", sender),
                ("SMTP_HOST", host),
                ("SMTP_USERNAME", username),
                ("SMTP_PASSWORD", password),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError("Web mode requires " + ", ".join(missing) + ".")
    return {
        "delivery_channel": channel,
        "web_app_url": url,
        "owner_email": owner,
        "email_from": sender,
        "smtp_host": host,
        "smtp_port": int(port),
        "smtp_username": username,
        "smtp_password": password,
    }
