from __future__ import annotations

import hmac
import secrets
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.exceptions import Forbidden, NotFound


def _base_context(request: Request) -> dict[str, Any]:
    messages = request.session.pop("flash", []) if request.session else []
    return {
        "csrf_token": request.session.get("csrf_token", "") if request.session else "",
        "current_user": request.session.get("user") if request.session else None,
        "theme": request.session.get("theme", "system") if request.session else "system",
        "unread_count": request.session.get("unread_count", 0) if request.session else 0,
        "notification_preview": request.session.get("notification_preview", []) if request.session else [],
        "flash_messages": messages,
    }


templates = Jinja2Templates(directory="templates", context_processors=[_base_context])


def render(request: Request, template: str, context: dict[str, Any] | None = None, *, status_code: int = 200):
    return templates.TemplateResponse(request=request, name=template, context=context or {}, status_code=status_code)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def get_db(request: Request):
    return request.app.state.db


def get_settings(request: Request):
    return request.app.state.settings


def flash(request: Request, kind: str, message: str) -> None:
    request.session.setdefault("flash", []).append({"kind": kind, "message": message})


def ensure_csrf(request: Request) -> str:
    request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return request.session["csrf_token"]


async def require_csrf(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return
    expected = ensure_csrf(request)
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied and "application/x-www-form-urlencoded" in request.headers.get("content-type", ""):
        supplied = (await request.form()).get("_csrf", "")
    elif not supplied and "multipart/form-data" in request.headers.get("content-type", ""):
        supplied = (await request.form()).get("_csrf", "")
    if not supplied or not hmac.compare_digest(expected, str(supplied)):
        raise HTTPException(status_code=403, detail="Your form expired. Refresh the page and try again.")


async def require_user(request: Request):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=303, detail="Sign in required", headers={"Location": "/login"})
    user = await request.app.state.db.find_one("users", {"id": user_data.get("id")})
    if not user or user.get("disabled"):
        request.session.clear()
        raise HTTPException(status_code=303, detail="Sign in required", headers={"Location": "/login"})
    if not user.get("email_verified"):
        raise HTTPException(status_code=303, detail="Verify your email", headers={"Location": "/verify-otp?email=" + user.get("email", "")})
    request.session["unread_count"] = await request.app.state.db.count("notifications", {"user_id": user["id"], "read_at": None})
    preview = await request.app.state.db.find_many("notifications", {"user_id": user["id"]}, sort=[("created_at", -1)], limit=4)
    request.session["notification_preview"] = [
        {
            "title": item["title"],
            "message": item["message"],
            "target_url": item.get("target_url", "/notifications"),
            "read_at": item["read_at"].isoformat() if item.get("read_at") else None,
        }
        for item in preview
    ]
    return user


async def require_admin(user=Depends(require_user)):
    if user.get("role") != "admin":
        raise Forbidden("Administrator access is required")
    return user


def user_session(user: dict[str, Any]) -> dict[str, Any]:
    return {"id": user["id"], "name": user.get("name", "Student"), "email": user["email"], "role": user.get("role", "student"), "avatar_url": user.get("avatar_url", ""), "storage_used": user.get("storage_used", 0)}


def not_found(message: str = "We couldn't find that page.") -> None:
    raise NotFound(message)
