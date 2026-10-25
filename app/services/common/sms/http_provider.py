"""Generic HTTP SMS gateway adapter (JSON POST with a bearer API key).

Most gateways (Twilio, SSL Wireless, BulkSMSBD, Infobip ...) accept "to + text + key".
Adjust ``_payload`` / headers to your provider's documented format; everything else
(timeouts, never raising, logging without the message body) stays the same.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from app.config import settings
from app.services.common.sms.base import SMSProvider, SMSResult, mask_phone

log = logging.getLogger("cdhrs.sms")


class HttpSMSProvider(SMSProvider):
    name = "http"

    def __init__(self, url: str, api_key: str, sender_id: str) -> None:
        if not url.startswith("https://"):
            raise ValueError("SMS_HTTP_URL must be an https:// URL")
        self.url, self.api_key, self.sender_id = url, api_key, sender_id

    def _payload(self, to: str, message: str) -> dict[str, str]:
        return {"to": to, "from": self.sender_id, "text": message}

    def send(self, to: str, message: str) -> SMSResult:
        req = urllib.request.Request(
            self.url,
            data=json.dumps(self._payload(to, message)).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310 (https enforced above)
                body = resp.read(2048).decode(errors="replace")
                ok = 200 <= resp.status < 300
                log.info("SMS to %s via http: status %s", mask_phone(to), resp.status)
                msg_id = None
                try:
                    msg_id = str(json.loads(body).get("id") or "") or None
                except (ValueError, AttributeError):
                    pass
                return SMSResult(ok=ok, provider=self.name, message_id=msg_id, error=None if ok else body[:200])
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log.error("SMS to %s failed: %s", mask_phone(to), e)
            return SMSResult(ok=False, provider=self.name, error=str(e)[:200])


def build() -> HttpSMSProvider:
    return HttpSMSProvider(settings.sms_http_url, settings.sms_http_api_key, settings.sms_http_sender_id)
