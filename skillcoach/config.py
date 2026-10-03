import os
import re
from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    pass


DEFAULT_GROQ_MODELS = "openai/gpt-oss-120b,openai/gpt-oss-20b"
# The public privacy policy (PRIVACY.md in this public repository); PRIVACY_POLICY_URL overrides it.
DEFAULT_PRIVACY_POLICY_URL = "https://github.com/Harshit975shukla/skillcoach-bot/blob/main/PRIVACY.md"


EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+")
# telegram: the bot only. web: the web app and email only (while Telegram is unavailable). both: the
# web app stays the complete record and Telegram gets a copy of coaching messages, with email as backup.
DELIVERY_CHANNELS = ("telegram", "web", "both")


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


BOT_TOKEN = re.compile(r"([1-9]\d{4,15}):[A-Za-z0-9_-]{30,64}")


def bot_id_of(token: str) -> int:
    """A bot token's numeric bot ID (its prefix), or 0 for anything that is not a bot token."""
    match = BOT_TOKEN.fullmatch(token or "")
    return int(match.group(1)) if match else 0


@dataclass(frozen=True)
class Config:
    database_url: str
    telegram_token: str
    owner_id: int
    webhook_secret: str = ""
    groq_key: str = ""
    groq_model: str = DEFAULT_GROQ_MODELS
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
    # Optional phone/desktop notifications for the web app: one VAPID key pair (base64url).
    web_push_public_key: str = ""
    web_push_private_key: str = ""
    # The bot whose Telegram update IDs were recorded before receipts carried a bot ID (migration 015).
    # Unset: this deployment has only ever used the configured bot.
    telegram_legacy_bot_id: int = 0
    privacy_policy_url: str = DEFAULT_PRIVACY_POLICY_URL

    @property
    def telegram_bot_id(self) -> int:
        """The configured bot's numeric ID, read from its token (no network call); 0 if unreadable."""
        return bot_id_of(self.telegram_token)

    @property
    def telegram_namespace(self) -> int:
        """Receipt and file-cache namespace of the configured bot: 0 for the bot whose records predate
        bot IDs (so a regenerated token for it keeps deduplicating), its own ID for any other bot."""
        if not self.telegram_legacy_bot_id or self.telegram_legacy_bot_id == self.telegram_bot_id:
            return 0
        return self.telegram_bot_id

    @property
    def web_mode(self) -> bool:
        """The web app, email sign-in and email reminders are on (web or both)."""
        return self.delivery_channel in ("web", "both")

    @property
    def telegram_copies(self) -> bool:
        """Both mode: coaching messages are also copied to Telegram while it accepts them."""
        return self.delivery_channel == "both"

    @property
    def push_enabled(self) -> bool:
        return self.web_mode and bool(self.web_push_public_key and self.web_push_private_key)

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
        chain = model_chain(groq_models)
        if not 1 <= len(chain) <= 4 or not all(re.fullmatch(r"[A-Za-z0-9._/:-]{1,100}", m) for m in chain):
            raise ConfigurationError("GROQ_MODEL must list one to four model names.")
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
        legacy_bot = os.getenv("TELEGRAM_LEGACY_BOT_ID", "").strip()
        if legacy_bot and not re.fullmatch(r"[1-9]\d{4,15}", legacy_bot):
            raise ConfigurationError("TELEGRAM_LEGACY_BOT_ID must be the numeric ID of a bot.")
        privacy = os.getenv("PRIVACY_POLICY_URL", "").strip() or DEFAULT_PRIVACY_POLICY_URL
        from urllib.parse import urlsplit

        parsed_privacy = urlsplit(privacy)
        if parsed_privacy.scheme != "https" or not parsed_privacy.hostname or parsed_privacy.username:
            raise ConfigurationError("PRIVACY_POLICY_URL must be an HTTPS address of the privacy policy.")
        web = web_settings()
        if web["delivery_channel"] == "both":
            # Copies, receipts and prompts are tied to the bot's identity: never guess it.
            if not bot_id_of(token):
                raise ConfigurationError(
                    "DELIVERY_CHANNEL=both needs a well-formed TELEGRAM_BOT_TOKEN (its numeric bot ID "
                    "identifies the bot)."
                )
            if not legacy_bot:
                raise ConfigurationError(
                    "DELIVERY_CHANNEL=both needs TELEGRAM_LEGACY_BOT_ID: the numeric ID of the bot whose "
                    "updates are already recorded (the configured bot's own ID if it is the same bot)."
                )
        return cls(
            database,
            token,
            int(owner),
            secret,
            os.getenv("GROQ_API_KEY", ""),
            groq_models,
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
            telegram_legacy_bot_id=int(legacy_bot) if legacy_bot else 0,
            privacy_policy_url=privacy,
        )


def web_settings() -> dict:
    """Web + email delivery settings. Everything is optional until DELIVERY_CHANNEL=web."""
    from urllib.parse import urlsplit

    channel = os.getenv("DELIVERY_CHANNEL", "").strip().lower() or "telegram"
    if channel not in DELIVERY_CHANNELS:
        raise ConfigurationError("DELIVERY_CHANNEL must be telegram, web or both.")
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
    if channel in ("web", "both"):
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
    push_public = os.getenv("WEB_PUSH_PUBLIC_KEY", "").strip()
    push_private = os.getenv("WEB_PUSH_PRIVATE_KEY", "").strip()
    if push_public or push_private:
        from skillcoach.web_push import check_keys

        if not check_keys(push_public, push_private):
            raise ConfigurationError(
                "WEB_PUSH_PUBLIC_KEY and WEB_PUSH_PRIVATE_KEY must be one matching VAPID key pair."
            )
    return {
        "delivery_channel": channel,
        "web_app_url": url,
        "owner_email": owner,
        "email_from": sender,
        "smtp_host": host,
        "smtp_port": int(port),
        "smtp_username": username,
        "smtp_password": password,
        "web_push_public_key": push_public,
        "web_push_private_key": push_private,
    }
