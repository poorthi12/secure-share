from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.exceptions import Forbidden
from app.core.permissions import group_role
from app.database import utcnow
from app.services.activity_service import log_activity
from app.services.notification_service import notify


async def consume_download(db: Any, *, file: dict[str, Any], user: dict[str, Any] | None, share: dict[str, Any] | None, ip: str | None, user_agent: str) -> None:
    async with db.transaction():
        checked_groups: set[str] = set()
        directly_shared = bool(share and user and share.get("recipient_id") == user.get("id"))
        if file.get("group_id") and (not user or file.get("owner_id") != user.get("id")) and not directly_shared:
            group_id = file["group_id"]
            group = await db.find_one("groups", {"id": group_id, "deleted_at": None})
            if not user or not group or not group_role(group, user["id"]):
                raise Forbidden("Your group access changed before the download started.")
            updated_group = await db.find_one_and_update("groups", {"id": group_id, "deleted_at": None, "members.user_id": user["id"]}, {"$inc": {"download_count": 1}})
            if not updated_group:
                raise Forbidden("Your group access changed before the download started.")
            checked_groups.add(group_id)
        if share:
            if share.get("recipient_id") and (not user or share["recipient_id"] != user.get("id")):
                raise Forbidden("This share belongs to a different recipient.")
            if share.get("group_id"):
                group_id = share["group_id"]
                group = await db.find_one("groups", {"id": group_id, "deleted_at": None})
                if not user or not group or not group_role(group, user["id"]):
                    raise Forbidden("Your group access changed before the download started.")
                if group_id not in checked_groups:
                    updated_group = await db.find_one_and_update("groups", {"id": group_id, "deleted_at": None, "members.user_id": user["id"]}, {"$inc": {"download_count": 1}})
                    if not updated_group:
                        raise Forbidden("Your group access changed before the download started.")
            share_filter = {"id": share["id"], "revoked_at": None}
            if share.get("expires_at"):
                share_filter["expires_at"] = {"$gt": utcnow()}
            if share.get("download_limit") is not None:
                share_filter["download_count"] = {"$lt": share["download_limit"]}
            consumed = await db.find_one_and_update("shares", share_filter, {"$inc": {"download_count": 1}})
            if not consumed:
                raise Forbidden("This share has reached its download limit, expired, or been revoked.")
        await db.insert_one("downloads", {
            "id": uuid4().hex,
            "user_id": user.get("id") if user else None,
            "file_id": file["id"],
            "share_id": share.get("id") if share else None,
            "ip": ip,
            "user_agent": user_agent[:300],
            "created_at": utcnow(),
        })
        await db.update_one("files", {"id": file["id"]}, {"$inc": {"download_count": 1}})
        await log_activity(db, "download", user_id=user.get("id") if user else None, detail=f"Downloaded {file['filename']}", target_id=file["id"], target_type="file", metadata={"share_id": share.get("id") if share else None})
        if file.get("owner_id") and (not user or file.get("owner_id") != user.get("id")):
            owner = await db.find_one("users", {"id": file["owner_id"]})
            if owner:
                who = user.get("name", "Someone") if user else "A link recipient"
                await notify(db, owner["id"], "download", "A file was downloaded", f"{who} downloaded {file['filename']}.", target_url=f"/files/{file['id']}")
