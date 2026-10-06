from __future__ import annotations

from typing import Any

from app.core.exceptions import Conflict
from app.database import utcnow
from app.services.activity_service import log_activity


async def persist_upload(db: Any, user_id: str, file_document: dict[str, Any], quota_bytes: int) -> None:
    async with db.transaction():
        updated = await db.find_one_and_update("users", {
            "id": user_id, "storage_used": {"$lte": quota_bytes - file_document["size"]},
        }, {"$inc": {"storage_used": file_document["size"]}})
        if not updated:
            raise Conflict("This upload would exceed your storage quota.")
        await db.insert_one("files", file_document)
        await log_activity(db, "upload", user_id=user_id, detail=f"Uploaded {file_document['filename']}", target_id=file_document["id"], target_type="file")
