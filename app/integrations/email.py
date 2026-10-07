from __future__ import annotations

import asyncio
import html
import logging
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr

from app.config import Settings

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.smtp_host and self._sender_address())

    def _sender_address(self) -> str:
        configured = self.settings.smtp_from_email.strip()
        if configured:
            return configured
        username = self.settings.smtp_username.strip()
        return username if parseaddr(username)[1] else ""

    async def send(self, recipient: str, subject: str, title: str, message: str, *, action_url: str | None = None) -> bool:
        if not self.is_configured:
            logger.warning("SMTP is not configured; outgoing email was not delivered")
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._sender_address()
        msg["To"] = recipient
        safe_title = html.escape(title)
        safe_message = html.escape(message).replace("\n", "<br>")
        action = f'<p><a href="{html.escape(action_url, quote=True)}" style="display:inline-block;background:#111111;color:white;padding:12px 18px;border-radius:10px;text-decoration:none">Continue securely</a></p>' if action_url else ""
        msg.set_content(f"{title}\n\n{message}" + (f"\n\n{action_url}" if action_url else ""))
        msg.add_alternative(f"""<!doctype html><html><body style="margin:0;background:#F5F5F5;font-family:Arial,sans-serif;color:#171717"><div style="max-width:560px;margin:32px auto;padding:32px;background:#fff;border:1px solid #E2E2E2;border-radius:18px"><div style="font-weight:800;color:#111111;letter-spacing:.02em">SECURESHARE</div><h1 style="font-size:24px;margin:28px 0 12px">{safe_title}</h1><p style="line-height:1.65;color:#555555">{safe_message}</p>{action}<p style="font-size:12px;color:#777777;margin-top:32px">If you did not request this, you can ignore this email.</p></div></body></html>""", subtype="html")

        def deliver() -> None:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                if self.settings.smtp_username:
                    smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(msg)

        await asyncio.to_thread(deliver)
        return True
