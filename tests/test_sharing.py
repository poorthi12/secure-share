import re

from fastapi.testclient import TestClient

from app.database import utcnow
from tests.conftest import csrf, create_user, sign_in


def upload_text_file(client, name="outline.txt", content=b"encrypted research outline"):
    page = client.get("/files/upload")
    response = client.post("/files/upload", data={"_csrf": csrf(page), "group_id": ""}, files={"upload": (name, content, "text/plain")}, follow_redirects=False)
    assert response.status_code == 303
    return client.app.state.db.tables["files"][-1]


def create_link_share(client, owner, file, *, password="", limit="1"):
    page = client.get(f"/sharing/create?file_id={file['id']}")
    data = {"_csrf": csrf(page), "file_id": file["id"], "is_link": "on", "expiry": "never", "download_limit": limit}
    if password:
        data["link_password"] = password
    response = client.post("/shares", data=data, follow_redirects=False)
    assert response.status_code == 303
    detail = client.get("/sharing/shared-by-me")
    match = re.search(r'value="(http://localhost:8000/s/[^\"]+)"', detail.text)
    assert match, "new share link should be presented once for copying"
    return match.group(1).rsplit("/", 1)[-1], client.app.state.db.tables["shares"][-1]


def test_password_link_download_limit_and_tracking(client):
    owner = create_user(client)
    sign_in(client, owner)
    original = b"private bytes stay encrypted at rest"
    file = upload_text_file(client, content=original)
    blob = client.app.state.db.tables["files"][-1]
    assert blob["encrypted"] is True
    stored = client.app.state.storage.get(blob["storage_key"])
    assert original not in __import__("asyncio").run(stored)
    token, share = create_link_share(client, owner, file, password="ShareSecret123!", limit="1")

    anonymous = TestClient(client.app, raise_server_exceptions=False)
    page = anonymous.get(f"/s/{token}")
    assert page.status_code == 200
    assert "password protected" in page.text
    response = anonymous.post(f"/s/{token}/download", data={"_csrf": csrf(page), "password": "wrong-password"}, follow_redirects=False)
    assert response.status_code == 303
    assert client.app.state.db.tables["shares"][-1]["download_count"] == 0
    page = anonymous.get(f"/s/{token}")
    response = anonymous.post(f"/s/{token}/download", data={"_csrf": csrf(page), "password": "ShareSecret123!"}, follow_redirects=False)
    assert response.status_code == 303
    page = anonymous.get(f"/s/{token}")
    assert "outline.txt" in page.text
    response = anonymous.post(f"/s/{token}/download", data={"_csrf": csrf(page)}, follow_redirects=False)
    assert response.status_code == 200
    assert response.content == original
    assert response.headers["cache-control"] == "private, no-store"
    assert len(client.app.state.db.tables["downloads"]) == 1
    unavailable = anonymous.get(f"/s/{token}")
    assert unavailable.status_code == 404


def test_revocation_blocks_secure_link(client):
    owner = create_user(client)
    sign_in(client, owner)
    file = upload_text_file(client, name="study.txt")
    token, share = create_link_share(client, owner, file, limit="unlimited")
    page = client.get("/sharing/shared-by-me")
    response = client.post(f"/shares/{share['id']}/revoke", data={"_csrf": csrf(page)}, follow_redirects=False)
    assert response.status_code == 303
    anonymous = TestClient(client.app, raise_server_exceptions=False)
    assert anonymous.get(f"/s/{token}").status_code == 404
    assert client.app.state.db.tables["shares"][-1]["revoked_at"] is not None
    assert any(row["event"] == "revoke" for row in client.app.state.db.tables["activity_logs"])


def test_share_creation_rejects_non_owner(client):
    sender = create_user(client)
    sign_in(client, sender)
    file = upload_text_file(client, name="owned.txt")
    other = create_user(client, name="Other Student", email="other@example.edu")
    sign_in(client, other)
    page = client.get("/sharing/create")
    response = client.post("/shares", data={"_csrf": csrf(page), "file_id": file["id"], "email": "friend@example.edu", "expiry": "1d", "download_limit": "unlimited"}, follow_redirects=False)
    assert response.status_code == 403
