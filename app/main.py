from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.core.encryption import FileEncryptor
from app.core.exceptions import SecureShareError
from app.database import make_database
from app.integrations.cloudinary import BlobStorage
from app.integrations.email import EmailService
from app.middleware.security_middleware import SecurityHeadersMiddleware
from app.routes import admin, auth, dashboard, files, groups, notifications, profile, sharing, storage, activity
from app.services.otp_service import OtpService
from app.web import render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("secureshare")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.local_demo_mode and settings.is_production:
        raise RuntimeError("LOCAL_DEMO_MODE cannot be enabled in production")
    if settings.is_production and not (settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret):
        raise RuntimeError("Cloudinary credentials must be set in production")
    if settings.is_production and not (settings.smtp_host and settings.smtp_from_email):
        raise RuntimeError("SMTP_HOST and SMTP_FROM_EMAIL must be set in production")
    if not settings.local_demo_mode and not settings.mongodb_uri:
        raise RuntimeError("MONGODB_URI must be configured unless LOCAL_DEMO_MODE=true")
    app.state.settings = settings
    mongodb_uri = "" if settings.local_demo_mode else settings.mongodb_uri
    app.state.db = make_database(mongodb_uri, settings.mongodb_database, production=settings.is_production)
    app.state.db_ready = False
    app.state.storage = BlobStorage(settings)
    app.state.encryptor = FileEncryptor(settings.encryption_secret())
    app.state.email = EmailService(settings)
    pepper = settings.token_signing_secret()
    app.state.otp = OtpService(settings, pepper)
    if mongodb_uri:
        try:
            await app.state.db.ping()
            await app.state.db.create_indexes()
            logger.info("Connected to MongoDB successfully")
        except Exception as exc:
            try:
                await app.state.db.close()
            except Exception:
                logger.debug("Closing the failed MongoDB client also failed", exc_info=True)
            logger.exception("Could not connect to configured MongoDB; refusing temporary storage")
            raise RuntimeError("Configured MongoDB is unavailable. Check the Atlas URI, database user, and Atlas network access list.") from exc
    else:
        await app.state.db.create_indexes()
        logger.warning("LOCAL_DEMO_MODE is enabled; records are temporary and cleared when the server stops")
    app.state.db_ready = True
    yield
    await app.state.storage.close()
    await app.state.db.close()


app = FastAPI(title="SecureShare", description="Secure student file sharing and collaboration", version="1.0.0", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SessionMiddleware, secret_key=get_settings().session_signing_secret(), session_cookie="secureshare_session", max_age=60 * 60 * 12, same_site="lax", https_only=get_settings().cookie_secure)
app.mount("/static", StaticFiles(directory="static"), name="static")

for router in (auth.router, dashboard.router, files.router, sharing.router, groups.router, notifications.router, activity.router, storage.router, profile.router, admin.router):
    app.include_router(router)


@app.exception_handler(SecureShareError)
async def secure_share_error(request: Request, exc: SecureShareError):
    template = {403: "errors/403.html", 404: "errors/404.html", 429: "errors/429.html"}.get(exc.status_code, "errors/500.html")
    return render(request, template, {"message": exc.message}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    logger.info("Rejected invalid request for %s", request.url.path)
    return render(request, "errors/400.html", {"message": "Some submitted details were invalid. Please review them and try again."}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("Unhandled application error on %s", request.url.path)
    return render(request, "errors/500.html", {"message": "Something went wrong. Please try again."}, status_code=500)


@app.exception_handler(404)
async def not_found_error(request: Request, exc: Exception):
    return render(request, "errors/404.html", status_code=404)


@app.exception_handler(403)
async def forbidden_error(request: Request, exc: Exception):
    return render(request, "errors/403.html", status_code=403)


@app.exception_handler(401)
async def unauthorized_error(request: Request, exc: Exception):
    return RedirectResponse("/login", status_code=303)


@app.get("/health", include_in_schema=False)
async def health(request: Request):
    try:
        await request.app.state.db.ping()
    except Exception:
        return HTMLResponse("unavailable", status_code=503)
    from app.database import MongoDatabase
    using_mongodb = isinstance(request.app.state.db, MongoDatabase)
    return {"status": "ok", "database": "connected" if using_mongodb else "demo"}
