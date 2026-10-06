from tests.conftest import csrf, create_user, sign_in


def test_upload_download_rename_and_delete(client):
    user = create_user(client)
    sign_in(client, user)
    payload = b"course notes must never be saved as plaintext"
    page = client.get("/files/upload")
    response = client.post("/files/upload", data={"_csrf": csrf(page), "group_id": ""}, files={"upload": ("week 1 notes.txt", payload, "text/plain")}, follow_redirects=False)
    assert response.status_code == 303
    file = client.app.state.db.tables["files"][0]
    stored = __import__("asyncio").run(client.app.state.storage.get(file["storage_key"]))
    assert payload not in stored
    assert file["encrypted"] is True
    response = client.get(f"/files/{file['id']}/download")
    assert response.status_code == 200
    assert response.content == payload
    assert client.app.state.db.tables["files"][0]["download_count"] == 1
    page = client.get(f"/files/{file['id']}")
    response = client.post(f"/files/{file['id']}/rename", data={"_csrf": csrf(page), "filename": "week 1 revised.txt"}, follow_redirects=False)
    assert response.status_code == 303
    assert client.app.state.db.tables["files"][0]["filename"] == "week 1 revised.txt"
    page = client.get(f"/files/{file['id']}")
    response = client.post(f"/files/{file['id']}/delete", data={"_csrf": csrf(page)}, follow_redirects=False)
    assert response.status_code == 303
    assert client.app.state.db.tables["files"][0]["deleted_at"] is not None


def test_other_student_cannot_download_private_file(client):
    owner = create_user(client)
    sign_in(client, owner)
    page = client.get("/files/upload")
    client.post("/files/upload", data={"_csrf": csrf(page), "group_id": ""}, files={"upload": ("private.txt", b"secret", "text/plain")}, follow_redirects=False)
    file = client.app.state.db.tables["files"][0]
    other = create_user(client, name="Sam Student", email="sam@example.edu")
    sign_in(client, other)
    assert client.get(f"/files/{file['id']}/download").status_code == 403
    assert client.app.state.db.tables.get("downloads", []) == []
