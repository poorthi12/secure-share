from __future__ import annotations

from typing import Any

from app.services.activity_service import log_activity
from app.services.notification_service import notify


async def commit_share(db: Any, share: dict[str, Any], *, file: dict[str, Any], sender: dict[str, Any], recipient: dict[str, Any] | None, group: dict[str, Any] | None) -> None:
    async with db.transaction():
        await db.insert_one("shares", share)
        await log_activity(db, "share", user_id=sender["id"], detail=f"Shared {file['filename']}", target_id=share["id"], target_type="share")
        if recipient:
            await notify(
                db,
                recipient["id"],
                "share",
                f"You received a file from {sender['name']}",
                f"{file['filename']} is ready. Tap to view and download it.",
                target_url="/sharing/shared-with-me",
            )
        if group:
            for member in group.get("members", []):
                member_id = member.get("user_id") if isinstance(member, dict) else member
                if member_id and member_id != sender["id"]:
                    await notify(db, member_id, "share", "A group file was shared", f"{file['filename']} is available to your group.", target_url=f"/groups/{group['id']}/files")
