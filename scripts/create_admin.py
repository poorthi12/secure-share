import asyncio
import getpass
import re
from uuid import uuid4

from app.config import get_settings
from app.core.security import hash_password
from app.database import make_database, utcnow


async def main() -> None:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise SystemExit("Set MONGODB_URI before creating an administrator.")
    name = input("Administrator name: ").strip()[:80]
    email = input("Administrator email: ").strip().lower()
    password = getpass.getpass("Password (10+ characters, with a letter and number): ")
    if len(name) < 2 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise SystemExit("Enter a valid name and email address.")
    if len(password) < 10 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise SystemExit("Choose a password with at least 10 characters, a letter and a number.")
    db = make_database(settings.mongodb_uri, settings.mongodb_database, production=True)
    try:
        await db.ping()
        await db.create_indexes()
        if await db.find_one("users", {"email": email}):
            raise SystemExit("An account with that email already exists.")
        await db.insert_one("users", {
            "id": uuid4().hex, "name": name, "email": email,
            "password_hash": hash_password(password), "role": "admin", "email_verified": True,
            "disabled": False, "storage_used": 0,
            "notification_preferences": {"sharing": True, "downloads": True, "groups": True, "security": True},
            "created_at": utcnow(), "updated_at": utcnow(),
        })
        print("Administrator created.")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
