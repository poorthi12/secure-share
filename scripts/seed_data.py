"""Seed a disposable local-memory database for tests is intentionally not persisted."""
from app.core.security import hash_password
from app.database import utcnow


def demo_student(name: str, email: str, password: str) -> dict:
    return {"id": email, "name": name, "email": email, "password_hash": hash_password(password), "role": "student", "email_verified": True, "disabled": False, "storage_used": 0, "notification_preferences": {}, "created_at": utcnow()}


if __name__ == "__main__":
    print("Use scripts/create_admin.py for persistent setup. Local demo records are created at runtime and are not persistent.")
