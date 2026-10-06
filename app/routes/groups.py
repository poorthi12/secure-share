from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from app.core.exceptions import Forbidden, NotFound
from app.core.permissions import can_manage_group, group_role
from app.database import utcnow
from app.services.activity_service import log_activity
from app.services.file_service import user_can_upload_to_group
from app.services.notification_service import notify
from app.web import flash, get_db, redirect, render, require_csrf, require_user

router = APIRouter(dependencies=[Depends(require_csrf)])


@router.get("/groups")
async def list_groups(request: Request, user=Depends(require_user)):
    groups = await get_db(request).find_many("groups", {"members.user_id": user["id"], "deleted_at": None}, sort=[("created_at", -1)])
    return render(request, "groups/groups.html", {"groups": groups})


@router.post("/groups")
async def create_group(request: Request, user=Depends(require_user)):
    form = await request.form()
    name = str(form.get("name", "")).strip()[:100]
    description = str(form.get("description", "")).strip()[:500]
    if len(name) < 2:
        flash(request, "error", "Group names need at least two characters.")
        return redirect("/groups")
    db = get_db(request)
    group = {"id": uuid4().hex, "name": name, "description": description, "owner_id": user["id"], "members": [{"user_id": user["id"], "role": "owner", "can_upload": True, "joined_at": utcnow()}], "created_at": utcnow(), "updated_at": utcnow()}
    async with db.transaction():
        await db.insert_one("groups", group)
        await log_activity(db, "group_created", user_id=user["id"], detail=f"Created group {name}", target_id=group["id"], target_type="group")
    flash(request, "success", "Your group is ready.")
    return redirect(f"/groups/{group['id']}")


@router.get("/groups/{group_id}")
async def group_details(request: Request, group_id: str, user=Depends(require_user)):
    db = get_db(request)
    group = await db.find_one("groups", {"id": group_id})
    if not group or group.get("deleted_at"):
        raise NotFound("Group not found.")
    role = group_role(group, user["id"])
    if not role:
        raise Forbidden("You are not a member of this group.")
    members = []
    for item in group.get("members", []):
        member_id = item.get("user_id") if isinstance(item, dict) else item
        member = await db.find_one("users", {"id": member_id})
        if member:
            members.append({"user": member, "role": item.get("role", "member") if isinstance(item, dict) else "member", "can_upload": item.get("can_upload", False) if isinstance(item, dict) else False})
    files = await db.find_many("files", {"group_id": group_id, "deleted_at": None}, sort=[("created_at", -1)], limit=20)
    return render(request, "groups/group_details.html", {"group": group, "members": members, "files": files, "role": role, "can_manage": can_manage_group(group, user["id"])})


@router.get("/groups/{group_id}/files")
async def group_files(request: Request, group_id: str, q: str = "", user=Depends(require_user)):
    db = get_db(request)
    group = await db.find_one("groups", {"id": group_id})
    if not group or group.get("deleted_at") or not group_role(group, user["id"]):
        raise Forbidden("You do not have access to this group repository.")
    query = {"group_id": group_id, "deleted_at": None}
    if q.strip():
        query["filename"] = {"$regex": q.strip()[:80], "$options": "i"}
    files = await db.find_many("files", query, sort=[("created_at", -1)], limit=100)
    return render(request, "groups/group_files.html", {"group": group, "files": files, "q": q, "can_upload": await user_can_upload_to_group(db, group_id, user["id"])})


@router.post("/groups/{group_id}/members")
async def add_member(request: Request, group_id: str, user=Depends(require_user)):
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    can_upload = str(form.get("can_upload", "")) == "on"
    db = get_db(request)
    group = await db.find_one("groups", {"id": group_id})
    if not group:
        raise NotFound("Group not found.")
    if not can_manage_group(group, user["id"]):
        raise Forbidden("Only group owners and administrators can add members.")
    member = await db.find_one("users", {"email": email, "email_verified": True, "disabled": False})
    if not member:
        flash(request, "error", "Use the email address of an active, verified SecureShare student.")
        return redirect(f"/groups/{group_id}")
    if group_role(group, member["id"]):
        flash(request, "info", "That student is already a member.")
        return redirect(f"/groups/{group_id}")
    new_member = {"user_id": member["id"], "role": "member", "can_upload": can_upload, "joined_at": utcnow()}
    async with db.transaction():
        await db.update_one("groups", {"id": group_id}, {"$push": {"members": new_member}, "$set": {"updated_at": utcnow()}})
        await log_activity(db, "group_member_added", user_id=user["id"], detail=f"Added {member['email']} to {group['name']}", target_id=group_id, target_type="group")
        await notify(db, member["id"], "group", "You were added to a group", f"{user['name']} added you to {group['name']}.", target_url=f"/groups/{group_id}")
    try:
        if not request.app.state.email.is_configured:
            raise RuntimeError("SMTP not configured")
        await request.app.state.email.send(member["email"], "You were added to a SecureShare group", "A group invitation", f"{user['name']} added you to {group['name']}.", action_url=request.app.state.settings.base_url.rstrip("/") + f"/groups/{group_id}")
    except Exception:
        pass
    flash(request, "success", "Student added to the group.")
    return redirect(f"/groups/{group_id}")


@router.post("/groups/{group_id}/members/{member_id}/remove")
async def remove_member(request: Request, group_id: str, member_id: str, user=Depends(require_user)):
    db = get_db(request)
    group = await db.find_one("groups", {"id": group_id})
    if not group:
        raise NotFound("Group not found.")
    if not can_manage_group(group, user["id"]):
        raise Forbidden("Only group owners and administrators can remove members.")
    role = group_role(group, member_id)
    if not role or role == "owner" or (group_role(group, user["id"]) == "admin" and role == "admin"):
        raise Forbidden("You cannot remove this group member.")
    members = [m for m in group.get("members", []) if (m.get("user_id") if isinstance(m, dict) else m) != member_id]
    async with db.transaction():
        await db.update_one("groups", {"id": group_id}, {"$set": {"members": members, "updated_at": utcnow()}})
        await log_activity(db, "group_member_removed", user_id=user["id"], detail=f"Removed member from {group['name']}", target_id=group_id, target_type="group")
        await notify(db, member_id, "group", "You were removed from a group", f"Your access to {group['name']} has ended.")
    flash(request, "success", "Member removed and group access updated.")
    return redirect(f"/groups/{group_id}")


@router.post("/groups/{group_id}/members/{member_id}/permissions")
async def update_member_permissions(request: Request, group_id: str, member_id: str, user=Depends(require_user)):
    form = await request.form()
    can_upload = str(form.get("can_upload", "")) == "on"
    db = get_db(request)
    group = await db.find_one("groups", {"id": group_id})
    if not group or not can_manage_group(group, user["id"]):
        raise Forbidden("You cannot manage this group.")
    members = []
    found = False
    for item in group.get("members", []):
        if isinstance(item, dict) and item.get("user_id") == member_id:
            item = {**item, "can_upload": can_upload}
            found = True
        members.append(item)
    if not found:
        raise NotFound("Group member not found.")
    await db.update_one("groups", {"id": group_id}, {"$set": {"members": members, "updated_at": utcnow()}})
    await log_activity(db, "group_permissions_updated", user_id=user["id"], detail=f"Updated group permissions in {group['name']}", target_id=group_id, target_type="group")
    flash(request, "success", "Member permissions updated.")
    return redirect(f"/groups/{group_id}")


@router.post("/groups/{group_id}/members/{member_id}/role")
async def update_member_role(request: Request, group_id: str, member_id: str, user=Depends(require_user)):
    form = await request.form()
    next_role = str(form.get("role", "member"))
    db = get_db(request)
    group = await db.find_one("groups", {"id": group_id})
    if not group or group.get("deleted_at"):
        raise NotFound("Group not found.")
    if group.get("owner_id") != user["id"]:
        raise Forbidden("Only the group owner can assign administrator roles.")
    if next_role not in {"admin", "member"}:
        flash(request, "error", "Choose a valid group role.")
        return redirect(f"/groups/{group_id}")
    members = []
    found = False
    for item in group.get("members", []):
        if isinstance(item, dict) and item.get("user_id") == member_id:
            item = {**item, "role": next_role, "can_upload": True if next_role == "admin" else item.get("can_upload", False)}
            found = True
        members.append(item)
    if not found:
        raise NotFound("Group member not found.")
    async with db.transaction():
        await db.update_one("groups", {"id": group_id}, {"$set": {"members": members, "updated_at": utcnow()}})
        await log_activity(db, "group_role_updated", user_id=user["id"], detail=f"Changed a group member role in {group['name']}", target_id=group_id, target_type="group")
        await notify(db, member_id, "group", "Your group role changed", f"Your role in {group['name']} is now {next_role}.", target_url=f"/groups/{group_id}")
    flash(request, "success", "Group role updated.")
    return redirect(f"/groups/{group_id}")


@router.post("/groups/{group_id}/delete")
async def delete_group(request: Request, group_id: str, user=Depends(require_user)):
    db = get_db(request)
    group = await db.find_one("groups", {"id": group_id})
    if not group or group.get("owner_id") != user["id"]:
        raise Forbidden("Only the group owner can delete this group.")
    async with db.transaction():
        await db.update_one("groups", {"id": group_id}, {"$set": {"deleted_at": utcnow()}})
        await db.update_one("files", {"group_id": group_id, "deleted_at": None}, {"$set": {"group_id": None}})
        await db.update_one("shares", {"group_id": group_id, "revoked_at": None}, {"$set": {"revoked_at": utcnow()}})
        await log_activity(db, "group_deleted", user_id=user["id"], detail=f"Deleted group {group['name']}", target_id=group_id, target_type="group")
    flash(request, "success", "Group deleted. Its files remain in their owners’ file spaces.")
    return redirect("/groups")
