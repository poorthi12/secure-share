from tests.conftest import csrf, create_user, sign_in


def test_group_creation_and_member_upload_permissions(client):
    owner = create_user(client)
    member = create_user(client, name="Riley Classmate", email="riley@example.edu")
    sign_in(client, owner)
    page = client.get("/groups")
    response = client.post("/groups", data={"_csrf": csrf(page), "name": "Research Studio", "description": "Shared references"}, follow_redirects=False)
    assert response.status_code == 303
    group_id = response.headers["location"].split("/")[-1]
    page = client.get(f"/groups/{group_id}")
    response = client.post(f"/groups/{group_id}/members", data={"_csrf": csrf(page), "email": member["email"], "can_upload": "on"}, follow_redirects=False)
    assert response.status_code == 303
    group = client.app.state.db.tables["groups"][0]
    assert len(group["members"]) == 2
    assert group["members"][1]["can_upload"] is True
    assert client.app.state.db.tables["notifications"][0]["user_id"] == member["id"]


def test_non_member_cannot_open_group_repository(client):
    owner = create_user(client)
    sign_in(client, owner)
    page = client.get("/groups")
    client.post("/groups", data={"_csrf": csrf(page), "name": "Private class"}, follow_redirects=False)
    group_id = client.app.state.db.tables["groups"][0]["id"]
    client.post("/logout", data={"_csrf": csrf(client.get("/dashboard"))}, follow_redirects=False)
    outsider = create_user(client, name="Kai Outside", email="kai@example.edu")
    sign_in(client, outsider)
    response = client.get(f"/groups/{group_id}/files")
    assert response.status_code == 403
