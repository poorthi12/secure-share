from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.security import hash_password, verify_password
from app.database import utcnow
from app.services.activity_service import log_activity
from app.web import flash, get_db, redirect, render, require_csrf, require_user

router = APIRouter(dependencies=[Depends(require_csrf)])


@router.get("/profile")
async def profile(request: Request, user=Depends(require_user)):
    return render(request, "profile/profile.html", {"profile_user": user})


@router.post("/profile")
async def update_profile(request: Request, user=Depends(require_user)):
    form = await request.form()
    name = str(form.get("name", "")).strip()[:80]
    avatar_url = str(form.get("avatar_url", "")).strip()[:500]
    if len(name) < 2 or (avatar_url and not avatar_url.startswith("https://")):
        flash(request, "error", "Enter a name and use an HTTPS image address for an optional avatar.")
        return redirect("/profile")
    db = get_db(request)
    await db.update_one("users", {"id": user["id"]}, {"$set": {"name": name, "avatar_url": avatar_url, "updated_at": utcnow()}})
    request.session["user"] = {**request.session["user"], "name": name, "avatar_url": avatar_url}
    await log_activity(db, "profile_updated", user_id=user["id"], detail="Updated profile")
    flash(request, "success", "Profile updated.")
    return redirect("/profile")


@router.get("/settings")
async def settings_page(request: Request, user=Depends(require_user)):
    return render(request, "settings/settings.html", {"profile_user": user})


@router.get("/settings/security")
async def security_page(request: Request, user=Depends(require_user)):
    return render(request, "settings/security.html", {"profile_user": user})


@router.post("/settings/security/password")
async def change_password(request: Request, user=Depends(require_user)):
    form = await request.form()
    current = str(form.get("current_password", ""))
    password = str(form.get("password", ""))
    confirmation = str(form.get("confirm_password", ""))
    db = get_db(request)
    stored = await db.find_one("users", {"id": user["id"]})
    if not stored or not verify_password(stored["password_hash"], current):
        flash(request, "error", "Current password is incorrect.")
    elif password != confirmation or len(password) < 10 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        flash(request, "error", "Choose a matching password with at least 10 characters, one letter, and one number.")
    else:
        await db.update_one("users", {"id": user["id"]}, {"$set": {"password_hash": hash_password(password), "updated_at": utcnow()}})
        await log_activity(db, "password_changed", user_id=user["id"], detail="Changed account password")
        flash(request, "success", "Password changed successfully.")
    return redirect("/settings/security")


@router.get("/settings/notifications")
async def notification_settings(request: Request, user=Depends(require_user)):
    return render(request, "settings/notification_settings.html", {"preferences": user.get("notification_preferences", {})})


@router.post("/settings/notifications")
async def update_notification_settings(request: Request, user=Depends(require_user)):
    form = await request.form()
    preferences = {key: str(form.get(key, "")) == "on" for key in ("sharing", "downloads", "groups", "security")}
    await get_db(request).update_one("users", {"id": user["id"]}, {"$set": {"notification_preferences": preferences, "updated_at": utcnow()}})
    flash(request, "success", "Notification preferences saved.")
    return redirect("/settings/notifications")


@router.post("/settings/theme")
async def set_theme(request: Request, user=Depends(require_user)):
    form = await request.form()
    theme = str(form.get("theme", "system"))
    if theme not in {"light", "dark", "system"}:
        theme = "system"
    request.session["theme"] = theme
    await get_db(request).update_one("users", {"id": user["id"]}, {"$set": {"theme_preference": theme, "updated_at": utcnow()}})
    flash(request, "success", f"Theme set to {theme}.")
    return redirect(request.headers.get("referer", "/settings"))
