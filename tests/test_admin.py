from tests.conftest import csrf, create_user, sign_in


def test_admin_can_manage_student_status_and_view_stats(client):
    admin = create_user(client, name="Admin User", email="admin@example.edu", role="admin")
    student = create_user(client, name="Pat Student", email="pat@example.edu")
    sign_in(client, admin)
    dashboard = client.get("/admin")
    assert dashboard.status_code == 200
    assert "System overview" in dashboard.text
    page = client.get("/admin/students?q=pat")
    assert "pat@example.edu" in page.text
    response = client.post(f"/admin/students/{student['id']}/status", data={"_csrf": csrf(page), "action": "disable"}, follow_redirects=False)
    assert response.status_code == 303
    stored = next(row for row in client.app.state.db.tables["users"] if row["id"] == student["id"])
    assert stored["disabled"] is True
    assert any(row["event"] == "admin_account_disabled" for row in client.app.state.db.tables["activity_logs"])
    assert client.get("/admin/system").status_code == 200


def test_student_cannot_open_admin_pages(client):
    student = create_user(client)
    sign_in(client, student)
    assert client.get("/admin").status_code == 403
