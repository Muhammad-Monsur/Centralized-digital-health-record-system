"""Development provider: prints the SMS to the server log instead of sending it."""
from __future__ import annotations

import logging
import secrets

from app.services.common.sms.base import SMSProvider, SMSResult

log = logging.getLogger("cdhrs.sms")

# Tests read the last message from here (never used in production).
OUTBOX: list[tuple[str, str]] = []


class ConsoleSMSProvider(SMSProvider):
    name = "console"

    def send(self, to: str, message: str) -> SMSResult:
        OUTBOX.append((to, message))
        del OUTBOX[:-50]
        log.warning("[DEV SMS] to=%s :: %s", to, message)
        return SMSResult(ok=True, provider=self.name, message_id=secrets.token_hex(6))
