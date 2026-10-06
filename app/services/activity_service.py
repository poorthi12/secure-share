from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.database import utcnow


async def log_activity(db: Any, event: str, *, user_id: str | None, detail: str = "", target_id: str | None = None, target_type: str | None = None, metadata: dict[str, Any] | None = None) -> None:
    await db.insert_one("activity_logs", {
        "id": uuid4().hex,
        "event": event,
        "user_id": user_id,
        "detail": detail[:500],
        "target_id": target_id,
        "target_type": target_type,
        "metadata": metadata or {},
        "created_at": utcnow(),
    })
