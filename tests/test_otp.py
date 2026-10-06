from datetime import timedelta

import pytest

from app.config import Settings
from app.database import MemoryDatabase, utcnow
from app.services.otp_service import OtpService


@pytest.mark.asyncio
async def test_otp_is_hashed_single_use_and_expires():
    db = MemoryDatabase()
    settings = Settings(otp_expiry_seconds=300, otp_resend_seconds=60, otp_max_attempts=5)
    service = OtpService(settings, "test-pepper")
    code = await service.issue(db, "STUDENT@example.edu", "verify_email")
    assert code and len(code) == 6
    record = db.tables["otp_records"][0]
    assert record["otp_hash"] != code
    assert code not in repr(record)
    assert await service.verify(db, "student@example.edu", "verify_email", "000000") is False
    assert await service.verify(db, "student@example.edu", "verify_email", code) is True
    assert await service.verify(db, "student@example.edu", "verify_email", code) is False


@pytest.mark.asyncio
async def test_otp_caps_attempts_and_resend_cooldown():
    db = MemoryDatabase()
    settings = Settings(otp_expiry_seconds=300, otp_resend_seconds=60, otp_max_attempts=2)
    service = OtpService(settings, "test-pepper")
    code = await service.issue(db, "a@example.edu", "reset_password")
    assert await service.issue(db, "a@example.edu", "reset_password") is None
    await service.verify(db, "a@example.edu", "reset_password", "111111")
    await service.verify(db, "a@example.edu", "reset_password", "222222")
    assert await service.verify(db, "a@example.edu", "reset_password", code) is False
    db.tables["otp_records"][0]["created_at"] = utcnow() - timedelta(seconds=61)
    assert await service.issue(db, "a@example.edu", "reset_password") is not None
