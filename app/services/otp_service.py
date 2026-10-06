from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.core.security import constant_time_equal, hash_otp
from app.database import utcnow


class OtpService:
    def __init__(self, settings: Settings, pepper: str) -> None:
        self.settings = settings
        self.pepper = pepper

    async def issue(self, db: Any, email: str, purpose: str) -> str | None:
        now = utcnow()
        otp = f"{secrets.randbelow(1_000_000):06d}"
        async with db.transaction():
            latest = await db.find_one("otp_records", {"email": email.lower(), "purpose": purpose, "consumed_at": None})
            if latest and latest.get("created_at") and now - latest["created_at"] < timedelta(seconds=self.settings.otp_resend_seconds):
                return None
            await db.update_one("otp_records", {"email": email.lower(), "purpose": purpose, "consumed_at": None}, {"$set": {"consumed_at": now}})
            await db.insert_one("otp_records", {
                "id": uuid4().hex,
                "email": email.lower(),
                "purpose": purpose,
                "otp_hash": hash_otp(email, purpose, otp, self.pepper),
                "attempts": 0,
                "created_at": now,
                "expires_at": now + timedelta(seconds=self.settings.otp_expiry_seconds),
                "consumed_at": None,
            })
        return otp

    async def verify(self, db: Any, email: str, purpose: str, otp: str) -> bool:
        now = utcnow()
        record = await db.find_one("otp_records", {
            "email": email.lower(), "purpose": purpose, "consumed_at": None,
            "expires_at": {"$gt": now}, "attempts": {"$lt": self.settings.otp_max_attempts},
        })
        if not record:
            return False
        expected = record["otp_hash"]
        actual = hash_otp(email, purpose, otp, self.pepper)
        if constant_time_equal(expected, actual):
            consumed = await db.find_one_and_update("otp_records", {
                "id": record["id"], "consumed_at": None, "expires_at": {"$gt": now}, "attempts": {"$lt": self.settings.otp_max_attempts},
            }, {"$set": {"consumed_at": now}})
            return consumed is not None
        await db.find_one_and_update("otp_records", {"id": record["id"], "consumed_at": None, "attempts": {"$lt": self.settings.otp_max_attempts}}, {"$inc": {"attempts": 1}})
        return False
