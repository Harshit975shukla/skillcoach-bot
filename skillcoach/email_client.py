"""Plain-text email over SMTP for web-mode sign-in codes and reminders. One bounded attempt per call;
callers own retries. Addresses, codes and credentials are never logged."""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

from skillcoach.clients import Budget, ExternalError
from skillcoach.config import normalize_email

log = logging.getLogger(__name__)
MAX_SECONDS = 20


class Email:
    def __init__(self, config):
        self.config = config

    @property
    def configured(self) -> bool:
        return self.config.email_configured

    def message(self, to: str, subject: str, text: str) -> EmailMessage:
        address = normalize_email(to)
        if address is None:
            raise ExternalError("email_recipient_invalid", retryable=False)
        if any(ch in subject for ch in "\r\n") or not 1 <= len(subject) <= 150:
            raise ExternalError("email_subject_invalid", retryable=False)
        name, sender = parseaddr(self.config.email_from)
        message = EmailMessage()
        message["From"] = formataddr((name or "SkillCoach", sender))
        message["To"] = address
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1])
        message["Auto-Submitted"] = "auto-generated"
        message.set_content(text[:20000])
        return message

    def send(self, to: str, subject: str, text: str, budget: Budget):
        if not self.configured:
            raise ExternalError("email_not_configured", retryable=False)
        message = self.message(to, subject, text)
        # Each SMTP step (connect, TLS, login, send) gets a share of the caller's budget.
        timeout = max(1.0, min(MAX_SECONDS, budget.remaining()) / 3)
        context = ssl.create_default_context()
        config = self.config
        try:
            if config.smtp_port == 465:
                client = smtplib.SMTP_SSL(config.smtp_host, 465, timeout=timeout, context=context)
            else:
                client = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=timeout)
            with client:
                if config.smtp_port != 465:
                    client.starttls(context=context)
                client.login(config.smtp_username, config.smtp_password)
                refused = client.send_message(message)
            if refused:
                raise ExternalError("email_recipient_refused", retryable=False)
        except smtplib.SMTPAuthenticationError:
            raise ExternalError("email_auth_failed", retryable=False) from None
        except smtplib.SMTPRecipientsRefused:
            raise ExternalError("email_recipient_refused", retryable=False) from None
        except (smtplib.SMTPException, OSError) as exc:
            log.warning("email_send_failed type=%s", type(exc).__name__)
            raise ExternalError("email_failed") from None
