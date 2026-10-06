from __future__ import annotations

from typing import Any

from app.core.permissions import active_share, group_role
from app.database import utcnow


async def file_access(db: Any, user: dict[str, Any] | None, file: dict[str, Any], *, allow_group: bool = True) -> tuple[bool, dict[str, Any] | None]:
    if file.get("deleted_at"):
        return False, None
    if user and file.get("owner_id") == user.get("id"):
        return True, None
    if user and allow_group and file.get("group_id"):
        group = await db.find_one("groups", {"id": file["group_id"]})
        if group and not group.get("deleted_at") and group_role(group, user["id"]):
            return True, None
    if not user:
        return False, None
    shares = await db.find_many("shares", {"file_id": file["id"], "revoked_at": None})
    for share in shares:
        if not active_share(share):
            continue
        if share.get("recipient_id") == user.get("id"):
            return True, share
        if share.get("group_id"):
            group = await db.find_one("groups", {"id": share["group_id"]})
            if group and not group.get("deleted_at") and group_role(group, user["id"]):
                return True, share
    return False, None


async def record_download(db: Any, file: dict[str, Any], user: dict[str, Any] | None, share: dict[str, Any] | None, *, request: Any) -> None:
    remote_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")[:300]
    from app.transactions.download_transaction import consume_download

    await consume_download(db, file=file, user=user, share=share, ip=remote_ip, user_agent=user_agent)
    if file.get("owner_id") and (not user or file["owner_id"] != user.get("id")):
        owner = await db.find_one("users", {"id": file["owner_id"]})
        if owner and owner.get("notification_preferences", {}).get("downloads", True) and request.app.state.email.is_configured:
            try:
                actor = user.get("name", "A link recipient") if user else "A secure link recipient"
                await request.app.state.email.send(owner["email"], "A SecureShare file was downloaded", "A file was downloaded", f"{actor} downloaded {file['filename']}.", action_url=request.app.state.settings.base_url.rstrip("/") + f"/files/{file['id']}")
            except Exception:
                import logging

                logging.getLogger(__name__).exception("Download notification email delivery failed")


async def user_can_upload_to_group(db: Any, group_id: str, user_id: str) -> bool:
    group = await db.find_one("groups", {"id": group_id})
    if not group or group.get("deleted_at"):
        return False
    role = group_role(group, user_id)
    if role in {"owner", "admin"}:
        return True
    return any(isinstance(member, dict) and member.get("user_id") == user_id and member.get("can_upload") for member in group.get("members", []))
