from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def active_share(share: dict[str, Any] | None) -> bool:
    if not share or share.get("revoked_at"):
        return False
    expires_at = share.get("expires_at")
    if expires_at and expires_at <= datetime.now(timezone.utc):
        return False
    limit = share.get("download_limit")
    return limit is None or share.get("download_count", 0) < limit


def group_role(group: dict[str, Any], user_id: str) -> str | None:
    if group.get("owner_id") == user_id:
        return "owner"
    for member in group.get("members", []):
        if isinstance(member, dict) and member.get("user_id") == user_id:
            return member.get("role", "member")
        if member == user_id:
            return "member"
    return None


def can_manage_group(group: dict[str, Any], user_id: str) -> bool:
    return group_role(group, user_id) in {"owner", "admin"}
