import asyncio

from app.config import get_settings
from app.database import make_database


async def main() -> None:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise SystemExit("Set MONGODB_URI before creating production indexes.")
    database = make_database(settings.mongodb_uri, settings.mongodb_database, production=True)
    try:
        await database.ping()
        await database.create_indexes()
        print(f"Indexes are ready in {settings.mongodb_database}.")
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
