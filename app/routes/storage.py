from fastapi import APIRouter, Depends, Request

from app.web import get_db, render, require_user

router = APIRouter()


@router.get("/storage")
async def storage_page(request: Request, user=Depends(require_user)):
    db = get_db(request)
    files = await db.find_many("files", {"owner_id": user["id"], "deleted_at": None}, sort=[("size", -1)])
    categories = {
        "image": "Images",
        "application": "Documents & archives",
        "text": "Text files",
        "audio": "Audio",
        "video": "Video",
    }
    type_totals = {}
    for file in files:
        content_type = str(file.get("content_type", "")).split(";", 1)[0].lower()
        if content_type == "application/octet-stream":
            category = "Other files"
        else:
            category = categories.get(content_type.split("/", 1)[0], "Other files")
        totals = type_totals.setdefault(category, {"count": 0, "bytes": 0})
        totals["count"] += 1
        totals["bytes"] += max(0, int(file.get("size") or 0))
    file_bytes = sum(totals["bytes"] for totals in type_totals.values())
    types = [
        {
            "name": name,
            "count": totals["count"],
            "bytes": totals["bytes"],
            "percent": round(totals["bytes"] * 100 / file_bytes, 1) if file_bytes else 0,
            "bar_percent": max(1, round(totals["bytes"] * 100 / file_bytes, 1)) if totals["bytes"] and file_bytes else 0,
            "color": (index % 4) + 1,
        }
        for index, (name, totals) in enumerate(sorted(type_totals.items(), key=lambda item: item[1]["bytes"], reverse=True))
    ]
    total = request.app.state.settings.storage_quota_bytes
    used = user.get("storage_used", 0)
    return render(request, "storage/storage.html", {"files": files, "types": types, "type_bytes": file_bytes, "used": used, "quota": total, "percent": min(100, round(used * 100 / total)) if total else 0, "remaining": max(0, total - used)})
