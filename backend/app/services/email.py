"""Outbound email behind a tiny interface.

MVP backends (approved decision #2):
- console: logs the message, dev only (config refuses it in production)
- memory: keeps messages in a list, used by tests
- disabled: drops messages (production until a provider such as Resend is configured)
"""

from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


outbox: list[EmailMessage] = []


async def send_email(to: str, subject: str, body: str) -> None:
    backend = get_settings().email_backend
    msg = EmailMessage(to=to, subject=subject, body=body)
    if backend == "memory":
        outbox.append(msg)
    elif backend == "console":
        log.info("email_console_backend", to=to, subject=subject, body=body)
    # disabled: intentionally nothing
