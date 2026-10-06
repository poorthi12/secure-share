from fastapi import APIRouter, Depends, Request

from app.database import utcnow
from app.web import flash, get_db, redirect, render, require_csrf, require_user

router = APIRouter(dependencies=[Depends(require_csrf)])


@router.get("/notifications")
async def notifications_page(request: Request, user=Depends(require_user)):
    db = get_db(request)
    rows = await db.find_many("notifications", {"user_id": user["id"]}, sort=[("created_at", -1)], limit=100)
    unread = await db.count("notifications", {"user_id": user["id"], "read_at": None})
    return render(request, "notifications/notifications.html", {"notifications": rows, "unread_count": unread})


@router.post("/notifications/{notification_id}/read")
async def mark_read(request: Request, notification_id: str, user=Depends(require_user)):
    await get_db(request).update_one("notifications", {"id": notification_id, "user_id": user["id"], "read_at": None}, {"$set": {"read_at": utcnow()}})
    request.session["unread_count"] = await get_db(request).count("notifications", {"user_id": user["id"], "read_at": None})
    return redirect("/notifications")


@router.post("/notifications/read-all")
async def mark_all_read(request: Request, user=Depends(require_user)):
    await get_db(request).update_one("notifications", {"user_id": user["id"], "read_at": None}, {"$set": {"read_at": utcnow()}})
    request.session["unread_count"] = 0
    flash(request, "success", "All notifications marked as read.")
    return redirect("/notifications")
