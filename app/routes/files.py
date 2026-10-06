from __future__ import annotations

import logging
import mimetypes
import re
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response

from app.core.exceptions import Forbidden, NotFound
from app.core.permissions import group_role
from app.database import utcnow
from app.services.activity_service import log_activity
from app.services.file_service import file_access, record_download, user_can_upload_to_group
from app.transactions.saga import Saga
from app.transactions.upload_transaction import persist_upload
from app.utils.file_utils import attachment_header, content_type, safe_filename
from app.web import flash, get_db, get_settings, redirect, render, require_csrf, require_user

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_csrf)])


async def _upload(request: Request, user: dict, upload: UploadFile, group_id: str | None) -> dict:
    settings = get_settings(request)
    filename = safe_filename(upload.filename or "untitled")
    content = await upload.read(settings.max_upload_bytes + 1)
    if not content:
        raise ValueError("Choose a file before uploading.")
    if len(content) > settings.max_upload_bytes:
        raise ValueError(f"Files must be smaller than {settings.max_upload_bytes // (1024 * 1024)} MB.")
    if group_id and not await user_can_upload_to_group(get_db(request), group_id, user["id"]):
        raise Forbidden("You do not have upload permission for this group.")
    db = get_db(request)
    existing = await db.find_one("users", {"id": user["id"]})
    if (existing or {}).get("storage_used", 0) + len(content) > settings.storage_quota_bytes:
        raise ValueError("This upload would exceed your storage quota.")
    file_id = uuid4().hex
    kind = content_type(filename, upload.content_type)
    encrypted = request.app.state.encryptor.encrypt(content, associated_data=file_id.encode())
    storage_key = await request.app.state.storage.put(encrypted, content_type=kind)
    record = {
        "id": file_id, "filename": filename, "content_type": kind, "size": len(content),
        "owner_id": user["id"], "group_id": group_id, "storage_key": storage_key,
        "encrypted": True, "encryption_algorithm": "AES-256-GCM", "download_count": 0,
        "created_at": utcnow(), "updated_at": utcnow(), "deleted_at": None,
    }
    async def persist() -> None:
        await persist_upload(db, user["id"], record, settings.storage_quota_bytes)

    async def compensate() -> None:
        await request.app.state.storage.delete(storage_key)

    try:
        await Saga.run(persist, [compensate])
    except Exception as exc:
        from app.core.exceptions import Conflict

        if isinstance(exc, Conflict):
            raise ValueError(exc.message) from exc
        raise
    return record


@router.get("/my-files")
async def my_files(request: Request, q: str = "", kind: str = "", sort: str = "newest", date_from: str = "", date_to: str = "", status: str = "", user=Depends(require_user)):
    db = get_db(request)
    query: dict = {"owner_id": user["id"], "deleted_at": None}
    if q.strip():
        query["filename"] = {"$regex": re.escape(q.strip()[:80]), "$options": "i"}
    if kind:
        query["content_type"] = {"$regex": "^" + re.escape(kind) + "/"}
    created: dict[str, datetime] = {}
    try:
        if date_from:
            created["$gte"] = datetime.combine(date.fromisoformat(date_from), time.min, timezone.utc)
        if date_to:
            created["$lt"] = datetime.combine(date.fromisoformat(date_to) + timedelta(days=1), time.min, timezone.utc)
    except ValueError:
        flash(request, "error", "Enter a valid date range.")
    if created:
        query["created_at"] = created
    if status == "downloaded":
        query["download_count"] = {"$gt": 0}
    elif status == "encrypted":
        query["encrypted"] = True
    elif status == "shared":
        shares = await db.find_many("shares", {"sender_id": user["id"], "revoked_at": None})
        query["id"] = {"$in": [share["file_id"] for share in shares]}
    sort_field = {"oldest": "created_at", "largest": "size", "downloads": "download_count"}.get(sort, "created_at")
    files = await db.find_many("files", query, sort=[(sort_field, 1 if sort in {"oldest"} else -1)], limit=100)
    return render(request, "files/my_files.html", {"files": files, "q": q, "kind": kind, "sort": sort, "date_from": date_from, "date_to": date_to, "status": status})


@router.get("/files/upload")
async def upload_page(request: Request, group_id: str | None = None, user=Depends(require_user)):
    group = None
    if group_id:
        db = get_db(request)
        group = await db.find_one("groups", {"id": group_id, "deleted_at": None})
        if not group or not await user_can_upload_to_group(db, group_id, user["id"]):
            raise Forbidden("You do not have upload permission for this group.")
    return render(request, "files/upload.html", {"group": group, "group_id": group["id"] if group else ""})


@router.post("/files/upload")
async def upload_file(request: Request, upload: UploadFile = File(...), group_id: str | None = Form(None), user=Depends(require_user)):
    try:
        record = await _upload(request, user, upload, group_id or None)
    except (ValueError, Forbidden) as exc:
        flash(request, "error", str(exc))
        return redirect(f"/files/upload?group_id={group_id}" if group_id else "/files/upload")
    flash(request, "success", f"{record['filename']} was encrypted and uploaded.")
    return redirect(f"/groups/{group_id}/files" if group_id else "/my-files")


@router.get("/files/{file_id}")
async def file_details(request: Request, file_id: str, user=Depends(require_user)):
    db = get_db(request)
    file = await db.find_one("files", {"id": file_id, "deleted_at": None})
    if not file:
        raise NotFound("File not found.")
    allowed, share = await file_access(db, user, file)
    if not allowed:
        raise Forbidden("You do not have access to this file.")
    downloads = await db.find_many("downloads", {"file_id": file_id}, sort=[("created_at", -1)], limit=20)
    return render(request, "files/file_details.html", {"file": file, "downloads": downloads, "can_manage": file.get("owner_id") == user["id"]})


@router.post("/files/{file_id}/rename")
async def rename_file(request: Request, file_id: str, user=Depends(require_user)):
    form = await request.form()
    filename = safe_filename(str(form.get("filename", "")))
    db = get_db(request)
    file = await db.find_one("files", {"id": file_id, "owner_id": user["id"], "deleted_at": None})
    if not file:
        raise NotFound("File not found.")
    if not filename:
        flash(request, "error", "Enter a valid filename.")
    else:
        await db.update_one("files", {"id": file_id}, {"$set": {"filename": filename, "updated_at": utcnow()}})
        await log_activity(db, "rename", user_id=user["id"], detail=f"Renamed file to {filename}", target_id=file_id, target_type="file")
        flash(request, "success", "File renamed.")
    return redirect(f"/files/{file_id}")


@router.post("/files/{file_id}/delete")
async def delete_file(request: Request, file_id: str, user=Depends(require_user)):
    db = get_db(request)
    file = await db.find_one("files", {"id": file_id, "owner_id": user["id"], "deleted_at": None})
    if not file:
        raise NotFound("File not found.")
    async with db.transaction():
        await db.update_one("files", {"id": file_id, "deleted_at": None}, {"$set": {"deleted_at": utcnow()}})
        await db.update_one("users", {"id": user["id"]}, {"$inc": {"storage_used": -file["size"]}})
        await db.update_one("shares", {"file_id": file_id, "revoked_at": None}, {"$set": {"revoked_at": utcnow()}})
        await log_activity(db, "delete", user_id=user["id"], detail=f"Deleted {file['filename']}", target_id=file_id, target_type="file")
    try:
        await request.app.state.storage.delete(file["storage_key"])
    except Exception:
        logger.exception("File cleanup deferred for %s", file_id)
        await db.insert_one("cleanup_queue", {"id": uuid4().hex, "storage_key": file["storage_key"], "file_id": file_id, "created_at": utcnow()})
    flash(request, "success", "File deleted and all shares revoked.")
    return redirect("/my-files")


@router.get("/files/{file_id}/download")
async def download_file(request: Request, file_id: str, user=Depends(require_user)):
    db = get_db(request)
    file = await db.find_one("files", {"id": file_id, "deleted_at": None})
    if not file:
        raise NotFound("File not found.")
    allowed, share = await file_access(db, user, file)
    if not allowed:
        raise Forbidden("You do not have access to this file.")
    await record_download(db, file, user, share, request=request)
    ciphertext = await request.app.state.storage.get(file["storage_key"])
    plaintext = request.app.state.encryptor.decrypt(ciphertext, associated_data=file_id.encode())
    return Response(plaintext, media_type=file.get("content_type", "application/octet-stream"), headers={"Content-Disposition": attachment_header(file["filename"]), "Cache-Control": "private, no-store"})
