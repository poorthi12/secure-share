from fastapi import APIRouter, Depends, Request

from app.web import get_db, render, require_user

router = APIRouter()


@router.get("/activity")
async def activity(request: Request, user=Depends(require_user)):
    rows = await get_db(request).find_many("activity_logs", {"user_id": user["id"]}, sort=[("created_at", -1)], limit=200)
    return render(request, "activity/activity.html", {"activity": rows})
