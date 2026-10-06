from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.core.exceptions import Forbidden, NotFound, RateLimited
from app.core.permissions import active_share, can_manage_group, group_role
from app.core.rate_limiter import limiter
from app.core.security import hash_password, opaque_token, token_digest, verify_password
from app.database import utcnow
from app.services.activity_service import log_activity
from app.services.file_service import record_download
from app.transactions.revoke_transaction import revoke_share as revoke_share_transaction
from app.transactions.share_transaction import commit_share
from app.utils.file_utils import attachment_header
from app.web import ensure_csrf, flash, get_db, get_settings, redirect, render, require_csrf, require_user

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_csrf)])


def _pepper(request: Request) -> str:
    return get_settings(request).jwt_secret or get_settings(request).session_signing_secret()


def _expiry(form, now: datetime) -> datetime | None:
    choice = str(form.get("expiry", "1d"))
    durations = {"10m": timedelta(minutes=10), "1h": timedelta(hours=1), "1d": timedelta(days=1), "7d": timedelta(days=7)}
    if choice == "never":
        return None
    if choice == "custom":
        value = str(form.get("expires_at", ""))
        try:
            parsed = datetime.fromisoformat(value)
            parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError as exc:
            raise ValueError("Choose a valid expiration time.") from exc
        if parsed <= now or parsed > now + timedelta(days=90):
            raise ValueError("Expiration must be in the future and within 90 days.")
        return parsed
    if choice not in durations:
        raise ValueError("Choose a supported expiration.")
    return now + durations[choice]


@router.get("/sharing")
async def sharing_home(request: Request, user=Depends(require_user)):
    return redirect("/sharing/shared-by-me")


@router.get("/sharing/shared-with-me")
async def shared_with_me(request: Request, user=Depends(require_user)):
    db = get_db(request)
    direct = await db.find_many("shares", {"recipient_id": user["id"], "revoked_at": None}, sort=[("created_at", -1)], limit=100)
    groups = await db.find_many("groups", {"members.user_id": user["id"], "deleted_at": None})
    group_ids = [g["id"] for g in groups]
    if group_ids:
        direct.extend(await db.find_many("shares", {"group_id": {"$in": group_ids}, "revoked_at": None}, sort=[("created_at", -1)], limit=100))
    entries = []
    seen = set()
    for share in direct:
        if share["id"] in seen:
            continue
        seen.add(share["id"])
        file = await db.find_one("files", {"id": share["file_id"], "deleted_at": None})
        sender = await db.find_one("users", {"id": share.get("sender_id")})
        if file:
            entries.append({"share": share, "file": file, "sender": sender})
    return render(request, "sharing/shared_with_me.html", {"entries": entries})


@router.get("/sharing/shared-by-me")
async def shared_by_me(request: Request, user=Depends(require_user)):
    db = get_db(request)
    shares = await db.find_many("shares", {"sender_id": user["id"]}, sort=[("created_at", -1)], limit=100)
    entries = []
    for share in shares:
        file = await db.find_one("files", {"id": share["file_id"]})
        recipient = await db.find_one("users", {"id": share.get("recipient_id")}) if share.get("recipient_id") else None
        group = await db.find_one("groups", {"id": share.get("group_id")}) if share.get("group_id") else None
        entries.append({"share": share, "file": file, "recipient": recipient, "group": group})
    return render(request, "sharing/shared_by_me.html", {"entries": entries, "new_share_link": request.session.pop("new_share_link", None), "now": utcnow()})


@router.get("/sharing/create")
async def create_share_page(request: Request, file_id: str = "", user=Depends(require_user)):
    ensure_csrf(request)
    db = get_db(request)
    files = await db.find_many("files", {"owner_id": user["id"], "deleted_at": None}, sort=[("created_at", -1)])
    selected = next((file for file in files if file["id"] == file_id), None)
    groups = await db.find_many("groups", {"members.user_id": user["id"], "deleted_at": None})
    students = await db.find_many("users", {"email_verified": True, "role": "student"}, sort=[("name", 1)], limit=300)
    students = [student for student in students if student.get("id") != user["id"] and not student.get("disabled")]
    return render(request, "sharing/create_share.html", {"files": files, "selected_file": selected, "groups": groups, "students": students})


@router.post("/shares")
async def create_share(request: Request, user=Depends(require_user)):
    form = await request.form()
    file_id = str(form.get("file_id", ""))
    share_type = str(form.get("share_type", "")).strip()
    if share_type and share_type not in {"student", "group", "link"}:
        flash(request, "error", "Choose a student, group, or secure link.")
        return redirect(f"/sharing/create?file_id={file_id}")
    recipient_id = str(form.get("recipient_id", "")).strip() if share_type in {"", "student"} else ""
    email = str(form.get("email", "")).strip().lower() if share_type in {"", "student"} else ""
    group_id = str(form.get("group_id", "")).strip() if share_type in {"", "group"} else ""
    is_link = share_type == "link" if share_type else str(form.get("is_link", "")) in {"on", "true", "1"}
    db = get_db(request)
    file = await db.find_one("files", {"id": file_id, "deleted_at": None})
    if not file:
        raise NotFound("Choose a file that still exists.")
    allowed = file.get("owner_id") == user["id"]
    if file.get("group_id"):
        group = await db.find_one("groups", {"id": file["group_id"]})
        allowed = can_manage_group(group or {}, user["id"])
    if not allowed:
        raise Forbidden("Only the file owner or a group administrator can share this file.")
    recipient = None
    group = None
    if share_type == "student" and not (recipient_id or email):
        flash(request, "error", "Select a student to share this file with.")
        return redirect(f"/sharing/create?file_id={file_id}")
    if share_type == "group" and not group_id:
        flash(request, "error", "Select a group to share this file with.")
        return redirect(f"/sharing/create?file_id={file_id}")
    if recipient_id or email:
        recipient = await db.find_one("users", {"id": recipient_id}) if recipient_id else await db.find_one("users", {"email": email})
        if not recipient or not recipient.get("email_verified") or recipient.get("disabled") or recipient["id"] == user["id"]:
            flash(request, "error", "Choose another active, verified SecureShare student.")
            return redirect(f"/sharing/create?file_id={file_id}")
    if group_id:
        group = await db.find_one("groups", {"id": group_id})
        if not group or not group_role(group, user["id"]):
            raise Forbidden("You are not a member of that group.")
    if sum(bool(x) for x in (recipient, group, is_link)) != 1:
        flash(request, "error", "Choose one recipient: a student, group, or secure link.")
        return redirect(f"/sharing/create?file_id={file_id}")
    now = utcnow()
    try:
        expires_at = _expiry(form, now)
    except ValueError as exc:
        flash(request, "error", str(exc))
        return redirect(f"/sharing/create?file_id={file_id}")
    limit_choice = str(form.get("download_limit", "unlimited"))
    limit_values = {"unlimited": None, "1": 1, "5": 5, "10": 10}
    if limit_choice == "custom":
        try:
            limit = int(str(form.get("custom_limit", "")))
            if limit < 1 or limit > 10000:
                raise ValueError
        except ValueError:
            flash(request, "error", "Enter a download limit between 1 and 10,000.")
            return redirect(f"/sharing/create?file_id={file_id}")
    elif limit_choice in limit_values:
        limit = limit_values[limit_choice]
    else:
        flash(request, "error", "Choose a supported download limit.")
        return redirect(f"/sharing/create?file_id={file_id}")
    password = str(form.get("link_password", "")) if is_link else ""
    if password and len(password) < 8:
        flash(request, "error", "Link passwords must contain at least 8 characters.")
        return redirect(f"/sharing/create?file_id={file_id}")
    token = opaque_token()
    share_id = uuid4().hex
    share = {
        "id": share_id, "file_id": file_id, "sender_id": user["id"],
        "recipient_id": recipient["id"] if recipient else None,
        "group_id": group["id"] if group else None,
        "is_link": is_link, "token_hash": token_digest(token, _pepper(request)) if is_link else None,
        "password_hash": hash_password(password) if password else None,
        "created_at": now, "expires_at": expires_at, "revoked_at": None,
        "download_limit": limit, "download_count": 0,
    }
    await commit_share(db, share, file=file, sender=user, recipient=recipient, group=group)
    if recipient and request.app.state.email.is_configured:
        try:
            await request.app.state.email.send(recipient["email"], "A file was shared with you on SecureShare", "A student shared a file", f"{user['name']} shared {file['filename']} with you.", action_url=get_settings(request).base_url.rstrip("/") + "/sharing/shared-with-me")
        except Exception:
            logger.exception("Share notification email failed")
    if is_link:
        link = get_settings(request).base_url.rstrip("/") + f"/s/{token}"
        request.session["new_share_link"] = link
        flash(request, "success", "Secure link created. Copy it now; it will not be shown again.")
    else:
        flash(request, "success", "File shared successfully.")
    return redirect("/sharing/shared-by-me")


@router.post("/shares/{share_id}/revoke")
async def revoke_share(request: Request, share_id: str, user=Depends(require_user)):
    db = get_db(request)
    share = await db.find_one("shares", {"id": share_id})
    if not share:
        raise NotFound("Share not found.")
    if share.get("sender_id") != user["id"]:
        raise Forbidden("Only the sender can revoke this share.")
    if share.get("revoked_at"):
        flash(request, "success", "Access was already revoked.")
        return redirect("/sharing/shared-by-me")
    file = await db.find_one("files", {"id": share["file_id"]})
    await revoke_share_transaction(db, share, user, file)
    if share.get("recipient_id") and request.app.state.email.is_configured:
        recipient = await db.find_one("users", {"id": share["recipient_id"]})
        if recipient:
            try:
                await request.app.state.email.send(recipient["email"], "SecureShare file access revoked", "Access was revoked", f"The sender revoked your access to {file['filename'] if file else 'a file'}.")
            except Exception:
                logger.exception("Access revocation email delivery failed")
    flash(request, "success", "Access revoked immediately.")
    return redirect("/sharing/shared-by-me")


@router.post("/shares/{share_id}/remove")
async def remove_received_share(request: Request, share_id: str, user=Depends(require_user)):
    db = get_db(request)
    share = await db.find_one("shares", {
        "id": share_id,
        "recipient_id": user["id"],
        "revoked_at": None,
    })
    if not share:
        raise NotFound("This shared file is no longer available.")
    file = await db.find_one("files", {"id": share["file_id"]})
    filename = file["filename"] if file else "a file"
    async with db.transaction():
        removed = await db.update_one(
            "shares",
            {"id": share_id, "recipient_id": user["id"], "revoked_at": None},
            {"$set": {"revoked_at": utcnow(), "revoked_by_id": user["id"]}},
        )
        if not removed:
            raise NotFound("This shared file is no longer available.")
        await log_activity(
            db,
            "share_removed",
            user_id=user["id"],
            detail=f"Removed access to {filename}",
            target_id=share_id,
            target_type="share",
        )
    flash(request, "success", "File removed from your list. The sender's original file was not deleted.")
    return redirect("/sharing/shared-with-me")


@router.get("/s/{token}")
async def open_secure_link(request: Request, token: str):
    ensure_csrf(request)
    db = get_db(request)
    share = await db.find_one("shares", {"token_hash": token_digest(token, _pepper(request)), "is_link": True})
    if not share or not active_share(share):
        raise NotFound("This secure link is unavailable or has expired.")
    file = await db.find_one("files", {"id": share["file_id"], "deleted_at": None})
    if not file:
        raise NotFound("This file is no longer available.")
    unlocked = not share.get("password_hash") or request.session.get("unlocked_share") == share["id"]
    return render(request, "sharing/share_details.html", {"file": file if unlocked else None, "share": share, "token": token, "unlocked": unlocked, "csrf_token": request.session.get("csrf_token")})


@router.post("/s/{token}/download")
async def download_secure_link(request: Request, token: str):
    form = await request.form()
    db = get_db(request)
    share = await db.find_one("shares", {"token_hash": token_digest(token, _pepper(request)), "is_link": True})
    if not share or not active_share(share):
        raise NotFound("This secure link is unavailable or has expired.")
    client_ip = request.client.host if request.client else "unknown"
    if share.get("password_hash") and request.session.get("unlocked_share") != share["id"] and not limiter.allow(f"share-password:{client_ip}:{share['id']}", limit=10, period=300):
        raise RateLimited("Too many password attempts for this secure link. Please wait and try again.")
    if not limiter.allow(f"share-download:{client_ip}:{share['id']}", limit=30, period=60):
        raise RateLimited("Too many requests for this secure link. Please wait a minute and try again.")
    if share.get("password_hash") and request.session.get("unlocked_share") != share["id"]:
        password = str(form.get("password", ""))
        if not verify_password(share["password_hash"], password):
            flash(request, "error", "That link password is incorrect.")
            return redirect(f"/s/{token}")
        request.session["unlocked_share"] = share["id"]
        flash(request, "success", "Link unlocked. Your download is ready.")
        return redirect(f"/s/{token}")
    file = await db.find_one("files", {"id": share["file_id"], "deleted_at": None})
    if not file:
        raise NotFound("This file is no longer available.")
    await record_download(db, file, request.session.get("user"), share, request=request)
    encrypted = await request.app.state.storage.get(file["storage_key"])
    content = request.app.state.encryptor.decrypt(encrypted, associated_data=file["id"].encode())
    return Response(content, media_type=file.get("content_type", "application/octet-stream"), headers={"Content-Disposition": attachment_header(file["filename"]), "Cache-Control": "private, no-store"})
