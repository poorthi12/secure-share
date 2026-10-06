from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request

from app.core.exceptions import NotFound
from app.database import utcnow
from app.services.activity_service import log_activity
from app.web import flash, get_db, redirect, render, require_admin, require_csrf

router = APIRouter(prefix="/admin", dependencies=[Depends(require_csrf)])


@router.get("")
async def admin_dashboard(request: Request, user=Depends(require_admin)):
    db = get_db(request)
    users = await db.find_many("users", {})
    files = await db.find_many("files", {"deleted_at": None})
    shares = await db.find_many("shares", {"revoked_at": None})
    recent = await db.find_many("activity_logs", {}, sort=[("created_at", -1)], limit=8)
    stats = {"students": sum(u.get("role") != "admin" for u in users), "active": sum(u.get("role") != "admin" and not u.get("disabled") for u in users), "disabled": sum(bool(u.get("disabled")) for u in users), "files": len(files), "storage": sum(f.get("size", 0) for f in files), "shares": len(shares), "downloads": await db.count("downloads", {}), "groups": await db.count("groups", {"deleted_at": None})}
    return render(request, "admin/dashboard.html", {"stats": stats, "recent": recent})


@router.get("/students")
async def students(request: Request, q: str = "", user=Depends(require_admin)):
    query = {"role": {"$ne": "admin"}}
    if q.strip():
        query["$or"] = [{"name": {"$regex": re.escape(q.strip()[:80]), "$options": "i"}}, {"email": {"$regex": re.escape(q.strip()[:80]), "$options": "i"}}]
    rows = await get_db(request).find_many("users", query, sort=[("created_at", -1)], limit=200)
    return render(request, "admin/students.html", {"students": rows, "q": q})


@router.post("/students/{student_id}/status")
async def update_student_status(request: Request, student_id: str, user=Depends(require_admin)):
    form = await request.form()
    disable = str(form.get("action", "")) == "disable"
    db = get_db(request)
    student = await db.find_one("users", {"id": student_id, "role": {"$ne": "admin"}})
    if not student:
        raise NotFound("Student account not found.")
    await db.update_one("users", {"id": student_id}, {"$set": {"disabled": disable, "updated_at": utcnow()}})
    await log_activity(db, "admin_account_disabled" if disable else "admin_account_enabled", user_id=user["id"], detail=f"{'Disabled' if disable else 'Enabled'} {student['email']}", target_id=student_id, target_type="user")
    flash(request, "success", "Account disabled." if disable else "Account enabled.")
    return redirect("/admin/students")


@router.get("/groups")
async def admin_groups(request: Request, user=Depends(require_admin)):
    rows = await get_db(request).find_many("groups", {"deleted_at": None}, sort=[("created_at", -1)], limit=200)
    return render(request, "admin/groups.html", {"groups": rows})


@router.post("/groups/{group_id}/remove")
async def admin_remove_group(request: Request, group_id: str, user=Depends(require_admin)):
    db = get_db(request)
    group = await db.find_one("groups", {"id": group_id, "deleted_at": None})
    if not group:
        raise NotFound("Group not found.")
    async with db.transaction():
        await db.update_one("groups", {"id": group_id}, {"$set": {"deleted_at": utcnow()}})
        await db.update_one("files", {"group_id": group_id, "deleted_at": None}, {"$set": {"group_id": None}})
        await db.update_one("shares", {"group_id": group_id, "revoked_at": None}, {"$set": {"revoked_at": utcnow()}})
        await log_activity(db, "admin_group_removed", user_id=user["id"], detail=f"Removed group {group['name']}", target_id=group_id, target_type="group")
    flash(request, "success", "Group removed and active shares revoked.")
    return redirect("/admin/groups")


@router.get("/files")
async def admin_files(request: Request, q: str = "", user=Depends(require_admin)):
    query = {"deleted_at": None}
    if q.strip():
        query["filename"] = {"$regex": re.escape(q.strip()[:80]), "$options": "i"}
    rows = await get_db(request).find_many("files", query, sort=[("created_at", -1)], limit=200)
    return render(request, "admin/files.html", {"files": rows, "q": q})


@router.get("/activity")
async def admin_activity(request: Request, q: str = "", user=Depends(require_admin)):
    query = {"event": {"$regex": re.escape(q.strip()[:80]), "$options": "i"}} if q else {}
    rows = await get_db(request).find_many("activity_logs", query, sort=[("created_at", -1)], limit=300)
    return render(request, "admin/activity_logs.html", {"activity": rows, "q": q})


@router.get("/system")
async def admin_system(request: Request, user=Depends(require_admin)):
    db = get_db(request)
    stats = {"users": await db.count("users", {}), "files": await db.count("files", {"deleted_at": None}), "shares": await db.count("shares", {"revoked_at": None}), "downloads": await db.count("downloads", {}), "groups": await db.count("groups", {"deleted_at": None})}
    return render(request, "admin/system_statistics.html", {"stats": stats, "database": "MongoDB" if request.app.state.settings.mongodb_uri else "Demo memory store"})
