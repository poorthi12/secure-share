from __future__ import annotations

import logging
import re
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from app.core.rate_limiter import limiter
from app.core.security import hash_password, verify_password
from app.database import utcnow
from app.services.activity_service import log_activity
from app.utils.validators import valid_password
from app.web import ensure_csrf, flash, get_db, get_settings, redirect, render, require_csrf, user_session

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_csrf)])


def _email(value: str) -> str:
    return value.strip().lower()[:254]


def _valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def _password_error(password: str, confirmation: str) -> str | None:
    if password != confirmation:
        return "The passwords do not match."
    if not valid_password(password):
        return "Use at least 10 characters with at least one letter and one number."
    return None


@router.get("/register")
async def register_page(request: Request):
    ensure_csrf(request)
    return render(request, "auth/register.html", {"error": None})


@router.post("/register")
async def register(request: Request):
    form = await request.form()
    name = str(form.get("name", "")).strip()[:80]
    email = _email(str(form.get("email", "")))
    raw_password = str(form.get("password", ""))
    password = raw_password[:256]
    raw_confirmation = str(form.get("confirm_password", ""))
    confirmation = raw_confirmation[:256]
    client_key = f"register:{request.client.host if request.client else 'unknown'}"
    if not limiter.allow(client_key, limit=5, period=3600):
        flash(request, "error", "Too many signup attempts. Please try again later.")
        return redirect("/register")
    error = _password_error(password, confirmation)
    if not name or not _valid_email(email) or error or len(raw_password) > 256 or len(raw_confirmation) > 256:
        flash(request, "error", error or "Enter your name, a valid email address and a password under 257 characters.")
        return redirect("/register")
    db = get_db(request)
    if await db.find_one("users", {"email": email}):
        flash(request, "error", "An account with that email already exists.")
        return redirect("/register")
    user = {
        "id": uuid4().hex, "name": name, "email": email, "password_hash": hash_password(password),
        "role": "student", "email_verified": False, "disabled": False,
        "notification_preferences": {"sharing": True, "downloads": True, "groups": True, "security": True},
        "storage_used": 0, "created_at": utcnow(), "updated_at": utcnow(),
    }
    try:
        async with db.transaction():
            await db.insert_one("users", user)
            otp = await request.app.state.otp.issue(db, email, "verify_email")
    except Exception:
        # A unique email index handles simultaneous registrations in MongoDB.
        if await db.find_one("users", {"email": email}):
            flash(request, "error", "An account with that email already exists.")
            return redirect("/register")
        raise
    email_service = request.app.state.email
    email_sent = False
    email_failed = False
    if otp:
        try:
            email_sent = await email_service.send(email, "Verify your SecureShare account", "Your verification code", f"Enter this code in SecureShare: {otp}\nIt expires in five minutes.")
        except Exception:
            logger.exception("Verification email delivery failed")
            email_failed = True
    await log_activity(db, "registration", user_id=user["id"], detail="Student account created", target_id=user["id"], target_type="user")
    if email_sent:
        flash(request, "success", "Account created. Check your email for a six-digit verification code.")
    elif email_failed:
        flash(request, "error", "Account created, but SMTP could not deliver the code. Check the SMTP host, port, and credentials.")
    else:
        flash(request, "error", "Account created, but no verification email was delivered. Set SMTP_HOST or MAIL_SERVER, then use Resend code.")
    return redirect(f"/verify-otp?email={email}")


@router.get("/verify-otp")
async def verify_page(request: Request, email: str = ""):
    ensure_csrf(request)
    return render(request, "auth/verify_otp.html", {"email": _email(email), "purpose": "verify_email"})


@router.post("/verify-otp")
async def verify(request: Request):
    form = await request.form()
    email = _email(str(form.get("email", "")))
    otp = str(form.get("otp", "")).strip()
    db = get_db(request)
    if not re.fullmatch(r"\d{6}", otp) or not await request.app.state.otp.verify(db, email, "verify_email", otp):
        await log_activity(db, "otp_verification_failed", user_id=None, detail="Email verification code rejected")
        flash(request, "error", "That code is invalid or expired. You can request another one when the resend timer ends.")
        return redirect(f"/verify-otp?email={email}")
    async with db.transaction():
        user = await db.find_one("users", {"email": email})
        if not user:
            flash(request, "error", "No account was found for that email.")
            return redirect("/register")
        await db.update_one("users", {"id": user["id"]}, {"$set": {"email_verified": True, "updated_at": utcnow()}})
        await log_activity(db, "email_verified", user_id=user["id"], detail="Email address verified", target_id=user["id"], target_type="user")
    flash(request, "success", "Email verified. You can now sign in.")
    return redirect("/login")


@router.post("/verify-otp/resend")
async def resend_otp(request: Request):
    form = await request.form()
    email = _email(str(form.get("email", "")))
    user = await get_db(request).find_one("users", {"email": email})
    delivery_failed = False
    smtp_failed = False
    cooling_down = False
    if user and not user.get("email_verified"):
        otp = await request.app.state.otp.issue(get_db(request), email, "verify_email")
        if otp:
            try:
                delivered = await request.app.state.email.send(email, "Your SecureShare verification code", "A fresh verification code", f"Your code is {otp}. It expires in five minutes.")
                delivery_failed = not delivered
            except Exception:
                logger.exception("Verification email delivery failed")
                delivery_failed = True
                smtp_failed = True
        else:
            cooling_down = True
    if delivery_failed:
        message = "SMTP could not deliver the code. Check the host, port, and credentials, then try again." if smtp_failed else "No code was delivered. Set SMTP_HOST or MAIL_SERVER, then try again."
        flash(request, "error", message)
    elif cooling_down:
        flash(request, "info", "Please wait before requesting another verification code.")
    else:
        flash(request, "success", "If the account needs verification, a fresh code has been sent.")
    return redirect(f"/verify-otp?email={email}")


@router.get("/login")
async def login_page(request: Request):
    ensure_csrf(request)
    if request.session.get("user"):
        return redirect("/dashboard")
    return render(request, "auth/login.html", {})


@router.post("/login")
async def login(request: Request):
    form = await request.form()
    email = _email(str(form.get("email", "")))
    password = str(form.get("password", ""))
    key = f"login:{request.client.host if request.client else 'unknown'}:{email}"
    ip_key = f"login-ip:{request.client.host if request.client else 'unknown'}"
    if len(password) > 256 or not limiter.allow(ip_key, limit=30, period=300) or not limiter.allow(key, limit=8, period=300):
        flash(request, "error", "Too many sign-in attempts. Wait a few minutes and try again.")
        return redirect("/login")
    db = get_db(request)
    user = await db.find_one("users", {"email": email})
    valid = bool(user and verify_password(user.get("password_hash", ""), password))
    if not valid or not user or user.get("disabled"):
        await log_activity(db, "failed_login", user_id=user.get("id") if user else None, detail="Sign-in failed")
        flash(request, "error", "Email or password is incorrect.")
        return redirect("/login")
    if not user.get("email_verified"):
        flash(request, "error", "Verify your email before signing in.")
        return redirect(f"/verify-otp?email={email}")
    request.session.clear()
    ensure_csrf(request)
    request.session["user"] = user_session(user)
    request.session["theme"] = user.get("theme_preference", "system")
    await log_activity(db, "login", user_id=user["id"], detail="Signed in", target_id=user["id"], target_type="user")
    if request.app.state.email.is_configured and user.get("notification_preferences", {}).get("security", True):
        try:
            await request.app.state.email.send(user["email"], "New sign-in to SecureShare", "Your account was signed in", "A new sign-in to your SecureShare account just occurred. If this was not you, change your password.", action_url=get_settings(request).base_url.rstrip("/") + "/settings/security")
        except Exception:
            logger.exception("Sign-in security email delivery failed")
    return redirect("/dashboard")


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    session_user = request.session.get("user")
    if session_user:
        await log_activity(get_db(request), "logout", user_id=session_user.get("id"), detail="Signed out")
    request.session.clear()
    flash(request, "success", "You are signed out.")
    return redirect("/login")


@router.get("/forgot-password")
async def forgot_page(request: Request):
    ensure_csrf(request)
    return render(request, "auth/forgot_password.html", {"step": "request"})


@router.post("/forgot-password")
async def forgot_password(request: Request):
    form = await request.form()
    email = _email(str(form.get("email", "")))
    db = get_db(request)
    ip = request.client.host if request.client else "unknown"
    user = await db.find_one("users", {"email": email}) if _valid_email(email) else None
    if user and limiter.allow(f"reset:{ip}", limit=5, period=600):
        otp = await request.app.state.otp.issue(db, email, "reset_password")
        if otp:
            try:
                await request.app.state.email.send(email, "Reset your SecureShare password", "Password reset code", f"Enter this code to continue: {otp}\nIt expires in five minutes.")
            except Exception:
                logger.exception("Password reset email delivery failed")
    flash(request, "success", "If an account matches that email, we sent a password reset code.")
    return redirect(f"/reset-password?email={email}")


@router.get("/reset-password")
async def reset_page(request: Request, email: str = ""):
    ensure_csrf(request)
    return render(request, "auth/reset_password.html", {"email": _email(email), "verified": request.session.get("reset_email") == _email(email) and request.session.get("reset_until", 0) > utcnow().timestamp()})


@router.post("/reset-password/verify")
async def verify_reset(request: Request):
    form = await request.form()
    email, otp = _email(str(form.get("email", ""))), str(form.get("otp", "")).strip()
    if not re.fullmatch(r"\d{6}", otp) or not await request.app.state.otp.verify(get_db(request), email, "reset_password", otp):
        await log_activity(get_db(request), "otp_verification_failed", user_id=None, detail="Password reset code rejected")
        flash(request, "error", "That code is invalid or expired.")
        return redirect(f"/reset-password?email={email}")
    request.session["reset_email"] = email
    request.session["reset_until"] = (utcnow() + timedelta(minutes=10)).timestamp()
    user = await get_db(request).find_one("users", {"email": email})
    await log_activity(get_db(request), "password_reset_otp_verified", user_id=user["id"] if user else None, detail="Password reset code verified")
    flash(request, "success", "Code verified. Choose a new password.")
    return redirect(f"/reset-password?email={email}")


@router.post("/reset-password")
async def reset_password(request: Request):
    form = await request.form()
    email = _email(str(form.get("email", "")))
    raw_password = str(form.get("password", ""))
    password, confirmation = raw_password[:256], str(form.get("confirm_password", ""))[:256]
    if request.session.get("reset_email") != email or request.session.get("reset_until", 0) <= utcnow().timestamp():
        flash(request, "error", "Verify a current reset code before choosing a new password.")
        return redirect(f"/reset-password?email={email}")
    error = _password_error(password, confirmation)
    if error or len(raw_password) > 256:
        flash(request, "error", error or "Choose a password under 257 characters.")
        return redirect(f"/reset-password?email={email}")
    user = await get_db(request).find_one("users", {"email": email})
    if user:
        await get_db(request).update_one("users", {"id": user["id"]}, {"$set": {"password_hash": hash_password(password), "updated_at": utcnow()}})
        await log_activity(get_db(request), "password_reset", user_id=user["id"], detail="Password reset completed")
        if request.app.state.email.is_configured and user.get("notification_preferences", {}).get("security", True):
            try:
                await request.app.state.email.send(email, "Your SecureShare password changed", "Password updated", "Your account password was changed. If you did not make this change, contact your administrator.")
            except Exception:
                logger.exception("Password reset security email delivery failed")
    request.session.pop("reset_email", None)
    request.session.pop("reset_until", None)
    flash(request, "success", "Your password has been updated. Sign in with the new password.")
    return redirect("/login")
