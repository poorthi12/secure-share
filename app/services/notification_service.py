from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.database import utcnow


async def notify(db: Any, user_id: str, kind: str, title: str, message: str, *, target_url: str = "") -> None:
    if not user_id:
        return
    owner = await db.find_one("users", {"id": user_id})
    preference = "downloads" if kind == "download" else "groups" if kind == "group" else "security" if kind in {"security", "revoked"} else "sharing"
    if owner and not owner.get("notification_preferences", {}).get(preference, True):
        return
    await db.insert_one("notifications", {
        "id": uuid4().hex,
        "user_id": user_id,
        "kind": kind,
        "title": title[:120],
        "message": message[:500],
        "target_url": target_url,
        "read_at": None,
        "created_at": utcnow(),
    })
