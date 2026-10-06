from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request

from app.core.permissions import active_share
from app.database import utcnow
from app.web import get_db, redirect, render, require_user

router = APIRouter()


@router.get("/")
async def home(request: Request):
    if request.session.get("user"):
        return redirect("/dashboard")
    return render(request, "landing.html", {})


@router.get("/dashboard")
async def dashboard(request: Request, user=Depends(require_user)):
    db = get_db(request)
    files = await db.find_many("files", {"owner_id": user["id"], "deleted_at": None}, sort=[("created_at", -1)], limit=6)
    shares = await db.find_many("shares", {"sender_id": user["id"], "revoked_at": None})
    active_shares = [s for s in shares if active_share(s)]
    received = await db.count("shares", {"recipient_id": user["id"], "revoked_at": None})
    notifications = await db.find_many("notifications", {"user_id": user["id"]}, sort=[("created_at", -1)], limit=5)
    activity = await db.find_many("activity_logs", {"user_id": user["id"]}, sort=[("created_at", -1)], limit=6)
    downloads = await db.find_many("downloads", {"file_id": {"$in": [f["id"] for f in files]}} if files else {"user_id": user["id"]}, sort=[("created_at", -1)], limit=5)
    unread = await db.count("notifications", {"user_id": user["id"], "read_at": None})
    return render(request, "dashboard/dashboard.html", {
        "files": files, "file_count": await db.count("files", {"owner_id": user["id"], "deleted_at": None}),
        "share_count": len(active_shares), "received_count": received, "storage_used": user.get("storage_used", 0),
        "storage_quota": request.app.state.settings.storage_quota_bytes,
        "notifications": notifications, "activity": activity, "downloads": downloads, "unread_count": unread,
    })


@router.get("/search")
async def search(request: Request, q: str = "", user=Depends(require_user)):
    db = get_db(request)
    if len(q.strip()) < 2:
        return render(request, "files/search.html", {"q": q, "files": []})
    needle = q.strip()[:100].casefold()
    owned = await db.find_many("files", {"owner_id": user["id"], "deleted_at": None}, sort=[("created_at", -1)], limit=200)
    shares = await db.find_many("shares", {"recipient_id": user["id"], "revoked_at": None})
    groups = await db.find_many("groups", {"members.user_id": user["id"], "deleted_at": None})
    group_ids = [group["id"] for group in groups]
    shared_ids = [share["file_id"] for share in shares if active_share(share)]
    if group_ids:
        group_shares = await db.find_many("shares", {"group_id": {"$in": group_ids}, "revoked_at": None})
        shared_ids.extend(share["file_id"] for share in group_shares if active_share(share))
    shared = await db.find_many("files", {"id": {"$in": list(set(shared_ids))}, "deleted_at": None}, sort=[("created_at", -1)], limit=200) if shared_ids else []
    candidates = {file["id"]: file for file in [*owned, *shared]}
    group_names = {group["id"]: group["name"].casefold() for group in groups}
    matches = []
    for file in candidates.values():
        owner = await db.find_one("users", {"id": file["owner_id"]})
        owner_text = f"{owner.get('name', '')} {owner.get('email', '')}".casefold() if owner else ""
        group_text = group_names.get(file.get("group_id"), "")
        haystack = f"{file.get('filename', '')} {file.get('content_type', '')} {owner_text} {group_text}".casefold()
        if needle in haystack:
            matches.append(file)
    return render(request, "files/search.html", {"q": q, "files": matches[:100]})
