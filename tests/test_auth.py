import re

from app.integrations.email import EmailService
from tests.conftest import csrf, create_user, sign_in


def test_signup_verifies_email_before_login(client):
    page = client.get("/register")
    response = client.post("/register", data={
        "_csrf": csrf(page), "name": "Avery Student", "email": "avery@example.edu",
        "password": "LearningSecure123!", "confirm_password": "LearningSecure123!",
    }, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/verify-otp?email=avery@example.edu"
    user = client.app.state.db.tables["users"][0]
    assert user["email_verified"] is False
    assert "password_hash" in user and "LearningSecure123!" not in repr(user)
    assert client.post("/login", data={"_csrf": csrf(client.get("/login")), "email": user["email"], "password": "LearningSecure123!"}, follow_redirects=False).status_code == 303
    email = client.outbox[-1]
    code = re.search(r"\b\d{6}\b", email["message"]).group(0)
    verify = client.get("/verify-otp?email=avery@example.edu")
    response = client.post("/verify-otp", data={"_csrf": csrf(verify), "email": user["email"], "otp": code}, follow_redirects=False)
    assert response.status_code == 303
    assert client.app.state.db.tables["users"][0]["email_verified"] is True
    sign_in(client, client.app.state.db.tables["users"][0])
    assert client.get("/dashboard").status_code == 200


def test_signup_reports_missing_email_delivery(client, monkeypatch):
    async def not_configured(self, recipient, subject, title, message, *, action_url=None):
        return False

    monkeypatch.setattr(EmailService, "send", not_configured)
    page = client.get("/register")
    response = client.post("/register", data={
        "_csrf": csrf(page), "name": "Avery Student", "email": "no-mail@example.edu",
        "password": "LearningSecure123!", "confirm_password": "LearningSecure123!",
    }, follow_redirects=False)
    result = client.get(response.headers["location"])
    assert response.status_code == 303
    assert "no verification email was delivered" in result.text
    assert "SMTP_HOST" in result.text


def test_password_policy_and_csrf_are_enforced(client):
    page = client.get("/register")
    response = client.post("/register", data={
        "_csrf": csrf(page), "name": "Avery Student", "email": "weak@example.edu",
        "password": "short", "confirm_password": "short",
    }, follow_redirects=False)
    assert response.status_code == 303
    assert not client.app.state.db.tables.get("users")
    denied = client.post("/login", data={"email": "x@example.edu", "password": "anything"}, follow_redirects=False)
    assert denied.status_code == 403


def test_disabled_accounts_cannot_sign_in(client):
    user = create_user(client)
    user["disabled"] = True
    client.app.state.db.tables["users"][0]["disabled"] = True
    page = client.get("/login")
    response = client.post("/login", data={"_csrf": csrf(page), "email": user["email"], "password": "LearningSecure123!"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_password_reset_uses_verified_otp_and_rehashes(client):
    user = create_user(client)
    page = client.get("/forgot-password")
    response = client.post("/forgot-password", data={"_csrf": csrf(page), "email": user["email"]}, follow_redirects=False)
    assert response.status_code == 303
    code = re.search(r"\b\d{6}\b", client.outbox[-1]["message"]).group(0)
    page = client.get(f"/reset-password?email={user['email']}")
    response = client.post("/reset-password/verify", data={"_csrf": csrf(page), "email": user["email"], "otp": code}, follow_redirects=False)
    assert response.status_code == 303
    page = client.get(f"/reset-password?email={user['email']}")
    response = client.post("/reset-password", data={"_csrf": csrf(page), "email": user["email"], "password": "AnotherSafePass123!", "confirm_password": "AnotherSafePass123!"}, follow_redirects=False)
    assert response.status_code == 303
    page = client.get("/login")
    denied = client.post("/login", data={"_csrf": csrf(page), "email": user["email"], "password": "LearningSecure123!"}, follow_redirects=False)
    assert denied.headers["location"] == "/login"
    page = client.get("/login")
    accepted = client.post("/login", data={"_csrf": csrf(page), "email": user["email"], "password": "AnotherSafePass123!"}, follow_redirects=False)
    assert accepted.headers["location"] == "/dashboard"
