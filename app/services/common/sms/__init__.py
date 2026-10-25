from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.services.common.sms.base import SMSProvider, SMSResult, mask_phone

__all__ = ["SMSProvider", "SMSResult", "get_sms_provider", "mask_phone"]


@lru_cache(maxsize=1)
def get_sms_provider() -> SMSProvider:
    if settings.sms_provider == "http":
        from app.services.common.sms.http_provider import build

        return build()
    if settings.is_production:
        raise RuntimeError("SMS_PROVIDER=console is not allowed in production; configure a real provider.")
    from app.services.common.sms.console import ConsoleSMSProvider

    return ConsoleSMSProvider()
