from tests.conftest import csrf, create_user, sign_in


def test_preset_file_request_notifies_recipient_and_can_be_completed(client):
    requester = create_user(client, name="Avery Requester", email="avery@example.edu")
    recipient = create_user(client, name="Riley Recipient", email="riley@example.edu")
    unverified = create_user(client, name="Unverified Member", email="unverified@example.edu", verified=False)
    sign_in(client, requester)

    page = client.get("/file-requests")
    assert "Please send me the requested file." in page.text
    assert "Reminder: please send me the file." in page.text
    assert "riley@example.edu" in page.text
    assert "unverified@example.edu" not in page.text
    assert "<textarea" not in page.text

    response = client.post("/file-requests", data={"_csrf": csrf(page), "recipient_id": recipient["id"], "request_type": "custom", "message": "free chat"}, follow_redirects=False)
    assert response.status_code == 303
    assert client.app.state.db.tables.get("file_requests", []) == []

    page = client.get("/file-requests")
    response = client.post("/file-requests", data={"_csrf": csrf(page), "recipient_id": recipient["id"], "request_type": "reminder"}, follow_redirects=False)
    assert response.status_code == 303
    file_request = client.app.state.db.tables["file_requests"][0]
    assert file_request["request_type"] == "reminder"
    assert file_request["status"] == "pending"
    assert client.app.state.db.tables["notifications"][-1]["user_id"] == recipient["id"]

    client.post("/logout", data={"_csrf": csrf(client.get("/dashboard"))}, follow_redirects=False)
    sign_in(client, recipient)
    update = client.get("/notifications/updates").json()
    assert update["latest"]["kind"] == "file_request"
    assert update["latest"]["target_url"] == "/file-requests"
    page = client.get("/file-requests")
    assert "Avery Requester" in page.text
    response = client.post(f"/file-requests/{file_request['id']}/status", data={"_csrf": csrf(page), "status": "fulfilled"}, follow_redirects=False)
    assert response.status_code == 303
    assert client.app.state.db.tables["file_requests"][0]["status"] == "fulfilled"
    assert client.app.state.db.tables["notifications"][-1]["user_id"] == requester["id"]


def test_only_request_participants_can_change_file_request_status(client):
    requester = create_user(client, name="Avery Requester", email="avery@example.edu")
    recipient = create_user(client, name="Riley Recipient", email="riley@example.edu")
    outsider = create_user(client, name="Kai Outsider", email="kai@example.edu")
    sign_in(client, requester)
    page = client.get("/file-requests")
    client.post("/file-requests", data={"_csrf": csrf(page), "recipient_id": recipient["id"], "request_type": "send_file"}, follow_redirects=False)
    file_request = client.app.state.db.tables["file_requests"][0]

    client.post("/logout", data={"_csrf": csrf(client.get("/dashboard"))}, follow_redirects=False)
    sign_in(client, outsider)
    page = client.get("/file-requests")
    response = client.post(f"/file-requests/{file_request['id']}/status", data={"_csrf": csrf(page), "status": "fulfilled"}, follow_redirects=False)
    assert response.status_code == 403
    assert client.app.state.db.tables["file_requests"][0]["status"] == "pending"
