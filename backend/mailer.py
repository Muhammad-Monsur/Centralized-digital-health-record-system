"""
Sends the one-time codes (consent OTP and password-reset code) by EMAIL.

"""

import os
import smtplib
from email.message import EmailMessage


def email_is_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def send_email(to_address: str, subject: str, body: str) -> bool:

    if not email_is_configured():
        return False

    message = EmailMessage()
    message["From"] = os.environ.get("SMTP_FROM", "no-reply@cdhrs.local")
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)

    try:
        host = os.environ["SMTP_HOST"]
        port = int(os.environ.get("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=10) as server:
            if os.environ.get("SMTP_STARTTLS", "true").lower() == "true":
                server.starttls()
            if os.environ.get("SMTP_USER"):
                server.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(message)
        return True
    except Exception as error:
        # never crash the request because email failed - just fall back to demo mode
        print(f"[mailer] could not send email: {error}")
        return False
