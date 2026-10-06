from app.core.permissions import can_manage_group, group_role


def test_group_role_hierarchy_and_upload_access_shape():
    group = {"owner_id": "owner", "members": [
        {"user_id": "owner", "role": "owner", "can_upload": True},
        {"user_id": "admin", "role": "admin", "can_upload": True},
        {"user_id": "member", "role": "member", "can_upload": False},
    ]}
    assert group_role(group, "owner") == "owner"
    assert group_role(group, "admin") == "admin"
    assert group_role(group, "member") == "member"
    assert group_role(group, "outsider") is None
    assert can_manage_group(group, "owner")
    assert can_manage_group(group, "admin")
    assert not can_manage_group(group, "member")
