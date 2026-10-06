import asyncio

from app.services.notification_service import notify
from tests.conftest import csrf, create_user, sign_in


def test_notification_preferences_and_mark_read(client):
    user = create_user(client)
    sign_in(client, user)
    db = client.app.state.db
    asyncio.run(notify(db, user["id"], "share", "A file was shared", "A classmate sent you a file."))
    assert db.tables["notifications"]
    page = client.get("/notifications")
    assert "A file was shared" in page.text
    notification = db.tables["notifications"][0]
    response = client.post(f"/notifications/{notification['id']}/read", data={"_csrf": csrf(page)}, follow_redirects=False)
    assert response.status_code == 303
    assert db.tables["notifications"][0]["read_at"] is not None
    page = client.get("/settings/notifications")
    response = client.post("/settings/notifications", data={"_csrf": csrf(page), "groups": "on"}, follow_redirects=False)
    assert response.status_code == 303
    asyncio.run(notify(db, user["id"], "group", "New group update", "A member was added."))
    assert len(db.tables["notifications"]) == 2


def test_disabled_notification_category_is_respected(client):
    user = create_user(client)
    asyncio.run(client.app.state.db.update_one("users", {"id": user["id"]}, {"$set": {"notification_preferences": {"sharing": False, "downloads": True, "groups": True, "security": True}}}))
    asyncio.run(notify(client.app.state.db, user["id"], "share", "Hidden notification", "Not saved."))
    assert client.app.state.db.tables.get("notifications", []) == []
