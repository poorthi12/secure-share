import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.exceptions import Forbidden
from app.core.permissions import active_share
from app.database import MemoryDatabase, utcnow
from app.services.file_service import record_download


def request_stub():
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"user-agent": "SecureShare test"})


@pytest.mark.asyncio
async def test_only_one_concurrent_request_consumes_last_download():
    db = MemoryDatabase()
    file = {"id": "f1", "filename": "class-notes.pdf", "owner_id": "owner", "download_count": 0}
    share = {"id": "s1", "file_id": "f1", "sender_id": "owner", "download_limit": 1, "download_count": 0, "revoked_at": None, "expires_at": utcnow() + timedelta(hours=1)}
    await db.insert_one("files", file)
    await db.insert_one("shares", share)
    results = await asyncio.gather(
        record_download(db, file, {"id": "recipient", "name": "Reader"}, share, request=request_stub()),
        record_download(db, file, {"id": "recipient", "name": "Reader"}, share, request=request_stub()),
        return_exceptions=True,
    )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, Forbidden) for result in results) == 1
    assert db.tables["shares"][0]["download_count"] == 1
    assert len(db.tables["downloads"]) == 1
    assert db.tables["files"][0]["download_count"] == 1


@pytest.mark.asyncio
async def test_unlimited_share_without_expiration_can_download():
    db = MemoryDatabase()
    file = {"id": "f2", "filename": "notes.txt", "owner_id": "owner", "download_count": 0}
    share = {"id": "s2", "file_id": "f2", "sender_id": "owner", "download_limit": None, "download_count": 0, "revoked_at": None, "expires_at": None}
    await db.insert_one("files", file)
    await db.insert_one("shares", share)
    await record_download(db, file, None, share, request=request_stub())
    assert db.tables["shares"][0]["download_count"] == 1


def test_expiry_and_revocation_disable_a_share():
    assert active_share({"revoked_at": None, "expires_at": utcnow() + timedelta(seconds=1), "download_count": 0})
    assert not active_share({"revoked_at": utcnow(), "download_count": 0})
    assert not active_share({"expires_at": utcnow() - timedelta(seconds=1), "download_count": 0})
    assert not active_share({"download_limit": 1, "download_count": 1})
