"""Pluggable SMS provider interface.

To add a real gateway, implement ``SMSProvider.send`` in a new module and register it in
``get_sms_provider`` (see README "Plugging in a real SMS provider").
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SMSResult:
    ok: bool
    provider: str
    message_id: str | None = None
    error: str | None = None


class SMSProvider(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, to: str, message: str) -> SMSResult:
        """Send ``message`` to E.164 number ``to``. Must never raise; return ok=False instead."""


def mask_phone(phone: str) -> str:
    """+8801712345678 -> +880*******678 (for UI and logs)."""
    return phone[:4] + "*" * max(0, len(phone) - 7) + phone[-3:] if len(phone) > 7 else "***"
