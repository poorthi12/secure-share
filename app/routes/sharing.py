from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from app.core.exceptions import Forbidden, NotFound, RateLimited
from app.core.permissions import active_share, can_manage_group, group_role
from app.core.rate_limiter import limiter
from app.core.security import hash_password, opaque_token, token_digest, verify_password
from app.database import utcnow
from app.services.activity_service import log_activity
from app.services.file_service import record_download
from app.transactions.revoke_transaction import revoke_share as revoke_share_transaction
from app.transactions.share_transaction import commit_shares
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


async def _shared_entries(db, user: dict) -> list[dict]:
    shares = await db.find_many("shares", {"recipient_id": user["id"], "revoked_at": None}, sort=[("created_at", -1)], limit=100)
    groups = await db.find_many("groups", {"members.user_id": user["id"], "deleted_at": None})
    group_ids = [group["id"] for group in groups]
    if group_ids:
        shares.extend(await db.find_many("shares", {"group_id": {"$in": group_ids}, "revoked_at": None}, sort=[("created_at", -1)], limit=100))
    unique_shares = list({share["id"]: share for share in shares}.values())
    file_ids = list({share["file_id"] for share in unique_shares})
    files = await db.find_many("files", {"id": {"$in": file_ids}, "deleted_at": None}) if file_ids else []
    file_by_id = {file["id"]: file for file in files}
    sender_ids = list({share.get("sender_id") for share in unique_shares if share.get("sender_id")})
    senders = await db.find_many("users", {"id": {"$in": sender_ids}}) if sender_ids else []
    sender_by_id = {sender["id"]: sender for sender in senders}
    return [
        {"share": share, "file": file_by_id[share["file_id"]], "sender": sender_by_id.get(share.get("sender_id"))}
        for share in unique_shares if share["file_id"] in file_by_id
    ]


@router.get("/sharing")
async def sharing_home(request: Request, user=Depends(require_user)):
    return redirect("/sharing/shared-by-me")


@router.get("/sharing/shared-with-me")
async def shared_with_me(request: Request, user=Depends(require_user)):
    db = get_db(request)
    entries = await _shared_entries(db, user)
    signature = ",".join(sorted(entry["share"]["id"] for entry in entries))
    return render(request, "sharing/shared_with_me.html", {"entries": entries, "share_signature": signature})


@router.get("/sharing/updates")
async def sharing_updates(request: Request, user=Depends(require_user)):
    entries = await _shared_entries(get_db(request), user)
    signature = ",".join(sorted(entry["share"]["id"] for entry in entries))
    return JSONResponse({"share_signature": signature})


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
    return render(request, "sharing/shared_by_me.html", {"entries": entries, "new_share_links": request.session.pop("new_share_links", []), "new_share_link": request.session.pop("new_share_link", None), "now": utcnow()})


@router.get("/sharing/create")
async def create_share_page(request: Request, file_id: str = "", recipient_id: str = "", user=Depends(require_user)):
    ensure_csrf(request)
    db = get_db(request)
    files = await db.find_many("files", {"owner_id": user["id"], "deleted_at": None}, sort=[("created_at", -1)])
    selected = next((file for file in files if file["id"] == file_id), None)
    groups = await db.find_many("groups", {"members.user_id": user["id"], "deleted_at": None})
    students = await db.find_many("users", {"email_verified": True}, sort=[("name", 1)], limit=1000)
    students = [student for student in students if student.get("id") != user["id"] and not student.get("disabled")]
    selected_recipient = next((student for student in students if student["id"] == recipient_id), None)
    return render(request, "sharing/create_share.html", {"files": files, "selected_file": selected, "groups": groups, "students": students, "selected_recipient": selected_recipient})


@router.post("/shares")
async def create_share(request: Request, user=Depends(require_user)):
    form = await request.form()

    def values(name: str) -> list[str]:
        return list(dict.fromkeys(str(value).strip() for value in form.getlist(name) if str(value).strip()))

    file_ids = values("file_ids")
    if not file_ids:
        legacy_file_id = str(form.get("file_id", "")).strip()
        file_ids = [legacy_file_id] if legacy_file_id else []
    page_url = f"/sharing/create?file_id={quote(file_ids[0], safe='')}" if file_ids else "/sharing/create"
    if not file_ids:
        flash(request, "error", "Select at least one file to share.")
        return redirect(page_url)
    if len(file_ids) > 20:
        flash(request, "error", "Share up to 20 files at a time.")
        return redirect(page_url)

    share_type = str(form.get("share_type", "")).strip()
    if share_type and share_type not in {"student", "group", "link"}:
        flash(request, "error", "Choose accounts, a group, or secure links.")
        return redirect(page_url)

    recipient_ids = values("recipient_ids")
    if not recipient_ids:
        legacy_recipient_id = str(form.get("recipient_id", "")).strip()
        recipient_ids = [legacy_recipient_id] if legacy_recipient_id else []
    recipient_emails = [email.lower() for email in values("recipient_emails")]
    if not recipient_emails:
        legacy_email = str(form.get("email", "")).strip().lower()
        recipient_emails = [legacy_email] if legacy_email else []
    group_id = str(form.get("group_id", "")).strip()
    is_link = share_type == "link" if share_type else str(form.get("is_link", "")) in {"on", "true", "1"}
    if not share_type:
        share_type = "student" if recipient_ids or recipient_emails else "group" if group_id else "link" if is_link else ""
    if share_type != "student":
        recipient_ids = []
        recipient_emails = []
    if share_type != "group":
        group_id = ""
    if share_type != "link":
        is_link = False
    if not share_type:
        flash(request, "error", "Choose a share destination.")
        return redirect(page_url)

    if share_type == "student" and not (recipient_ids or recipient_emails):
        flash(request, "error", "Select one or more accounts to share these files with.")
        return redirect(page_url)
    if share_type == "student" and len(recipient_ids) + len(recipient_emails) > 20:
        flash(request, "error", "Share with up to 20 accounts at a time.")
        return redirect(page_url)
    if share_type == "group" and not group_id:
        flash(request, "error", "Select a group to share these files with.")
        return redirect(page_url)

    db = get_db(request)
    files_found = await db.find_many("files", {"id": {"$in": file_ids}, "deleted_at": None})
    file_by_id = {file["id"]: file for file in files_found}
    if len(file_by_id) != len(file_ids):
        flash(request, "error", "One or more selected files are no longer available.")
        return redirect(page_url)
    files = [file_by_id[file_id] for file_id in file_ids]
    for file in files:
        allowed = file.get("owner_id") == user["id"]
        if file.get("group_id"):
            owner_group = await db.find_one("groups", {"id": file["group_id"]})
            allowed = can_manage_group(owner_group or {}, user["id"])
        if not allowed:
            raise Forbidden("Only the file owner or a group administrator can share selected files.")

    recipients = []
    for recipient_id in recipient_ids:
        recipient = await db.find_one("users", {"id": recipient_id})
        if not recipient or not recipient.get("email_verified") or recipient.get("disabled") or recipient["id"] == user["id"]:
            flash(request, "error", "Choose active, verified accounts other than yourself.")
            return redirect(page_url)
        recipients.append(recipient)
    for email in recipient_emails:
        recipient = await db.find_one("users", {"email": email})
        if not recipient or not recipient.get("email_verified") or recipient.get("disabled") or recipient["id"] == user["id"]:
            flash(request, "error", "Choose active, verified accounts other than yourself.")
            return redirect(page_url)
        recipients.append(recipient)
    recipients = list({recipient["id"]: recipient for recipient in recipients}.values())

    group = None
    if group_id:
        group = await db.find_one("groups", {"id": group_id})
        if not group or not group_role(group, user["id"]):
            raise Forbidden("You are not a member of that group.")

    target_count = len(recipients) if share_type == "student" else 1
    if len(files) * target_count > 100:
        flash(request, "error", "A batch can create up to 100 individual shares.")
        return redirect(page_url)

    now = utcnow()
    try:
        expires_at = _expiry(form, now)
    except ValueError as exc:
        flash(request, "error", str(exc))
        return redirect(page_url)
    limit_choice = str(form.get("download_limit", "unlimited"))
    limit_values = {"unlimited": None, "1": 1, "5": 5, "10": 10}
    if limit_choice == "custom":
        try:
            limit = int(str(form.get("custom_limit", "")))
            if limit < 1 or limit > 10000:
                raise ValueError
        except ValueError:
            flash(request, "error", "Enter a download limit between 1 and 10,000.")
            return redirect(page_url)
    elif limit_choice in limit_values:
        limit = limit_values[limit_choice]
    else:
        flash(request, "error", "Choose a supported download limit.")
        return redirect(page_url)

    password = str(form.get("link_password", "")) if is_link else ""
    if password and len(password) < 8:
        flash(request, "error", "Link passwords must contain at least 8 characters.")
        return redirect(page_url)
    password_hash = hash_password(password) if password else None
    entries = []
    new_links = []
    destinations = recipients if share_type == "student" else [None]
    for file in files:
        for recipient in destinations:
            token = opaque_token() if is_link else ""
            share_id = uuid4().hex
            share = {
                "id": share_id, "file_id": file["id"], "sender_id": user["id"],
                "recipient_id": recipient["id"] if recipient else None,
                "group_id": group["id"] if group else None,
                "is_link": is_link, "token_hash": token_digest(token, _pepper(request)) if is_link else None,
                "password_hash": password_hash, "created_at": now, "expires_at": expires_at,
                "revoked_at": None, "download_limit": limit, "download_count": 0,
            }
            entries.append({"share": share, "file": file, "sender": user, "recipient": recipient, "group": group})
            if is_link:
                new_links.append({"filename": file["filename"], "url": get_settings(request).base_url.rstrip("/") + f"/s/{token}"})

    await commit_shares(db, entries, sender=user)
    email_delivery_failed = False
    if recipients and request.app.state.email.is_configured:
        for recipient in recipients:
            names = [entry["file"]["filename"] for entry in entries if entry["recipient"]["id"] == recipient["id"]]
            try:
                await request.app.state.email.send(
                    recipient["email"],
                    "Files were shared with you on SecureShare",
            "A SecureShare member shared files with you",
                    f"{user['name']} shared {len(names)} files with you: {', '.join(names[:10])}.",
                    action_url=get_settings(request).base_url.rstrip("/") + "/sharing/shared-with-me",
                )
            except Exception:
                logger.exception("Share notification email failed")
                email_delivery_failed = True

    if is_link:
        request.session["new_share_links"] = new_links
        flash(request, "success", f"Created {len(new_links)} secure links. Copy them now; they will not be shown again.")
    elif recipients:
        flash(request, "success", f"Shared {len(files)} file{'s' if len(files) != 1 else ''} with {len(recipients)} account{'s' if len(recipients) != 1 else ''}.")
        if email_delivery_failed:
            flash(request, "error", "The shares were created, but one or more email alerts could not be delivered.")
    else:
        flash(request, "success", f"Shared {len(files)} file{'s' if len(files) != 1 else ''} with the group.")
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
