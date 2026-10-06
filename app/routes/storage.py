from collections import Counter

from fastapi import APIRouter, Depends, Request

from app.web import get_db, render, require_user

router = APIRouter()


@router.get("/storage")
async def storage_page(request: Request, user=Depends(require_user)):
    db = get_db(request)
    files = await db.find_many("files", {"owner_id": user["id"], "deleted_at": None}, sort=[("size", -1)], limit=500)
    types = Counter((file.get("content_type", "application/octet-stream").split("/")[0]).title() for file in files)
    total = request.app.state.settings.storage_quota_bytes
    used = user.get("storage_used", 0)
    return render(request, "storage/storage.html", {"files": files, "types": types.most_common(), "used": used, "quota": total, "percent": min(100, round(used * 100 / total)) if total else 0, "remaining": max(0, total - used)})
