from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from app.core.exceptions import Forbidden, NotFound, RateLimited
from app.core.rate_limiter import limiter
from app.database import utcnow
from app.services.activity_service import log_activity
from app.services.notification_service import notify
from app.web import ensure_csrf, flash, get_db, redirect, render, require_csrf, require_user

router = APIRouter(dependencies=[Depends(require_csrf)])

REQUEST_MESSAGES = {
    "send_file": "Please send me the requested file.",
    "reminder": "Reminder: please send me the file.",
}


@router.get("/file-requests")
async def file_requests_page(request: Request, user=Depends(require_user)):
    ensure_csrf(request)
    db = get_db(request)
    incoming = await db.find_many("file_requests", {"recipient_id": user["id"]}, sort=[("created_at", -1)], limit=100)
    outgoing = await db.find_many("file_requests", {"requester_id": user["id"]}, sort=[("created_at", -1)], limit=100)
    other_ids = {
        item["requester_id"] for item in incoming
    } | {
        item["recipient_id"] for item in outgoing
    }
    people = await db.find_many("users", {"id": {"$in": list(other_ids)}}) if other_ids else []
    people_by_id = {person["id"]: person for person in people}
    incoming = [{**item, "other": people_by_id.get(item["requester_id"])} for item in incoming]
    outgoing = [{**item, "other": people_by_id.get(item["recipient_id"])} for item in outgoing]
    accounts = await db.find_many("users", {"email_verified": True}, sort=[("name", 1)], limit=1000)
    accounts = [account for account in accounts if account.get("id") != user["id"] and not account.get("disabled")]
    return render(request, "file_requests/file_requests.html", {
        "accounts": accounts,
        "incoming": incoming,
        "outgoing": outgoing,
        "request_messages": REQUEST_MESSAGES,
    })


@router.post("/file-requests")
async def create_file_request(request: Request, user=Depends(require_user)):
    form = await request.form()
    recipient_id = str(form.get("recipient_id", "")).strip()
    request_type = str(form.get("request_type", "")).strip()
    if request_type not in REQUEST_MESSAGES:
        flash(request, "error", "Choose one of the preset request messages.")
        return redirect("/file-requests")
    if recipient_id == user["id"]:
        flash(request, "error", "Choose another account to request a file from.")
        return redirect("/file-requests")
    if not limiter.allow(f"file-request:{user['id']}", limit=10, period=3600):
        raise RateLimited("You have sent several file requests recently. Please try again later.")

    db = get_db(request)
    recipient = await db.find_one("users", {"id": recipient_id})
    if not recipient or not recipient.get("email_verified") or recipient.get("disabled"):
        flash(request, "error", "Choose an active, verified SecureShare account.")
        return redirect("/file-requests")

    now = utcnow()
    item = {
        "id": uuid4().hex,
        "requester_id": user["id"],
        "recipient_id": recipient["id"],
        "request_type": request_type,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
    }
    async with db.transaction():
        await db.insert_one("file_requests", item)
        await log_activity(db, "file_request_sent", user_id=user["id"], detail=f"Requested a file from {recipient['name']}", target_id=item["id"], target_type="file_request")
        await notify(
            db,
            recipient["id"],
            "file_request",
            f"File request from {user['name']}",
            REQUEST_MESSAGES[request_type],
            target_url="/file-requests",
        )
    flash(request, "success", f"Your file request was sent to {recipient['name']}.")
    return redirect("/file-requests")


@router.post("/file-requests/{request_id}/status")
async def update_file_request(request: Request, request_id: str, user=Depends(require_user)):
    form = await request.form()
    status = str(form.get("status", "")).strip()
    if status not in {"fulfilled", "declined"}:
        flash(request, "error", "Choose a valid request action.")
        return redirect("/file-requests")
    db = get_db(request)
    item = await db.find_one("file_requests", {"id": request_id})
    if not item:
        raise NotFound("File request not found.")
    if item.get("recipient_id") != user["id"]:
        raise Forbidden("Only the recipient can update this file request.")
    if item.get("status") != "pending":
        flash(request, "info", "This file request has already been updated.")
        return redirect("/file-requests")

    now = utcnow()
    requester = await db.find_one("users", {"id": item["requester_id"]})
    label = "marked your request as sent" if status == "fulfilled" else "declined your request"
    async with db.transaction():
        updated = await db.update_one(
            "file_requests",
            {"id": request_id, "recipient_id": user["id"], "status": "pending"},
            {"$set": {"status": status, "updated_at": now, "resolved_at": now}},
        )
        if not updated:
            flash(request, "info", "This file request has already been updated.")
            return redirect("/file-requests")
        await log_activity(db, f"file_request_{status}", user_id=user["id"], detail=f"{label.capitalize()} for {requester['name'] if requester else 'a student'}", target_id=request_id, target_type="file_request")
        if requester:
            await notify(
                db,
                requester["id"],
                "file_request",
                "Your file request was updated",
                f"{user['name']} {label}.",
                target_url="/file-requests",
            )
    flash(request, "success", "The request was updated.")
    return redirect("/file-requests")


@router.post("/file-requests/{request_id}/cancel")
async def cancel_file_request(request: Request, request_id: str, user=Depends(require_user)):
    db = get_db(request)
    item = await db.find_one("file_requests", {"id": request_id})
    if not item:
        raise NotFound("File request not found.")
    if item.get("requester_id") != user["id"]:
        raise Forbidden("Only the requester can cancel this file request.")
    now = utcnow()
    async with db.transaction():
        updated = await db.update_one(
            "file_requests",
            {"id": request_id, "requester_id": user["id"], "status": "pending"},
            {"$set": {"status": "cancelled", "updated_at": now, "resolved_at": now}},
        )
        if updated:
            await log_activity(db, "file_request_cancelled", user_id=user["id"], detail="Cancelled a file request", target_id=request_id, target_type="file_request")
    flash(request, "success" if updated else "info", "File request cancelled." if updated else "This request is no longer pending.")
    return redirect("/file-requests")
