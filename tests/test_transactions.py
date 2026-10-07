import asyncio
from pathlib import Path

import pytest

from app.database import MemoryDatabase
from tests.conftest import csrf, create_user, sign_in


@pytest.mark.asyncio
async def test_memory_transaction_rolls_back_all_documents():
    db = MemoryDatabase()
    await db.insert_one("users", {"id": "u1", "storage_used": 0})
    with pytest.raises(RuntimeError):
        async with db.transaction():
            await db.update_one("users", {"id": "u1"}, {"$inc": {"storage_used": 12}})
            await db.insert_one("files", {"id": "f1"})
            raise RuntimeError("force rollback")
    assert (await db.find_one("users", {"id": "u1"}))["storage_used"] == 0
    assert await db.count("files") == 0


def test_upload_failure_compensates_external_blob(client, monkeypatch):
    user = create_user(client)
    sign_in(client, user)
    db = client.app.state.db
    original_insert = db.insert_one
    original_delete = client.app.state.storage.delete
    deleted = []

    async def fail_file_metadata(collection, document):
        if collection == "files":
            raise RuntimeError("simulated metadata failure")
        return await original_insert(collection, document)

    async def track_delete(key):
        deleted.append(key)
        await original_delete(key)

    monkeypatch.setattr(db, "insert_one", fail_file_metadata)
    monkeypatch.setattr(client.app.state.storage, "delete", track_delete)
    page = client.get("/files/upload")
    response = client.post("/files/upload", data={"_csrf": csrf(page), "group_id": ""}, files={"upload": ("saga.txt", b"temporary blob", "text/plain")}, follow_redirects=False)
    # Batch uploads report per-file failures and return to the upload page.
    assert response.status_code == 303
    assert response.headers["location"] == "/files/upload"
    assert deleted and deleted[0].startswith("local:")
    assert db.tables.get("files", []) == []
    assert db.tables["users"][0]["storage_used"] == 0
    key = deleted[0].split(":", 1)[1]
    assert not (Path(client.app.state.settings.local_blob_dir) / f"{key}.blob").exists()
