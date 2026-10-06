from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

# Tests are hermetic even when the developer's shell has production service credentials.
for _name, _value in {
    "APP_ENV": "development", "LOCAL_DEMO_MODE": "false", "MONGODB_URI": "", "CLOUDINARY_CLOUD_NAME": "",
    "CLOUDINARY_API_KEY": "", "CLOUDINARY_API_SECRET": "", "SMTP_HOST": "",
    "SMTP_USERNAME": "", "SMTP_PASSWORD": "", "MAIL_SERVER": "", "SESSION_SECRET": "test-session-secret-for-local-tests",
    "JWT_SECRET": "test-token-secret-for-local-tests", "ENCRYPTION_KEY": "", "BASE_URL": "http://localhost:8000",
}.items():
    os.environ[_name] = _value

from app.core.security import hash_password
from app.database import utcnow
from app.integrations.email import EmailService
from app.config import get_settings
from app.core.rate_limiter import limiter

get_settings.cache_clear()
from app.main import app


def csrf(response) -> str:
    match = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.text)
    assert match, "CSRF token should be present in page markup"
    return match.group(1)


def create_user(client: TestClient, *, name="Avery Student", email="avery@example.edu", password="LearningSecure123!", role="student", verified=True):
    user = {
        "id": f"test-{email}", "name": name, "email": email.lower(), "password_hash": hash_password(password),
        "role": role, "email_verified": verified, "disabled": False, "storage_used": 0,
        "notification_preferences": {"sharing": True, "downloads": True, "groups": True, "security": True},
        "created_at": utcnow(), "updated_at": utcnow(),
    }
    asyncio.run(client.app.state.db.insert_one("users", user))
    return user


def sign_in(client: TestClient, user: dict, password: str = "LearningSecure123!"):
    page = client.get("/login")
    response = client.post("/login", data={"_csrf": csrf(page), "email": user["email"], "password": password}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
    return response


@pytest.fixture
def client(monkeypatch):
    limiter._hits.clear()
    outbox = []

    async def capture(self, recipient, subject, title, message, *, action_url=None):
        outbox.append({"recipient": recipient, "subject": subject, "title": title, "message": message, "action_url": action_url})
        return True

    monkeypatch.setattr(EmailService, "send", capture)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.outbox = outbox
        yield test_client
