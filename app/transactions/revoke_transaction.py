from __future__ import annotations

from typing import Any

from app.database import utcnow
from app.services.activity_service import log_activity
from app.services.notification_service import notify


async def revoke_share(db: Any, share: dict[str, Any], sender: dict[str, Any], file: dict[str, Any] | None) -> bool:
    async with db.transaction():
        changed = await db.update_one("shares", {"id": share["id"], "revoked_at": None}, {"$set": {"revoked_at": utcnow()}})
        if not changed:
            return False
        name = file["filename"] if file else "file"
        await log_activity(db, "revoke", user_id=sender["id"], detail=f"Revoked share to {name}", target_id=share["id"], target_type="share")
        if share.get("recipient_id"):
            await notify(db, share["recipient_id"], "revoked", "File access was revoked", f"Access to {name} was revoked.", target_url="/sharing/shared-with-me")
        return True
