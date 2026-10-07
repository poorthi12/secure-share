from __future__ import annotations

import asyncio
import copy
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from pymongo import AsyncMongoClient, ReturnDocument


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _value(document: dict[str, Any], path: str) -> Any:
    value: Any = document
    for part in path.split("."):
        if isinstance(value, list):
            value = [item.get(part) for item in value if isinstance(item, dict) and part in item]
            continue
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(document, clause) for clause in expected):
                return False
            continue
        if key == "$and":
            if not all(_matches(document, clause) for clause in expected):
                return False
            continue
        actual = _value(document, key)
        if isinstance(expected, dict):
            options = expected.get("$options", "")
            for op, operand in expected.items():
                if op == "$options":
                    continue
                if op == "$in" and not (any(item in operand for item in actual) if isinstance(actual, list) else actual in operand):
                    return False
                if op == "$nin" and (any(item in operand for item in actual) if isinstance(actual, list) else actual in operand):
                    return False
                if op == "$ne" and actual == operand:
                    return False
                if op == "$gt" and (actual is None or actual <= operand):
                    return False
                if op == "$gte" and (actual is None or actual < operand):
                    return False
                if op == "$lt" and (actual is None or actual >= operand):
                    return False
                if op == "$lte" and (actual is None or actual > operand):
                    return False
                if op == "$exists" and ((actual is not None) != bool(operand)):
                    return False
                if op == "$regex":
                    flags = re.I if "i" in options else 0
                    if actual is None or re.search(str(operand), str(actual), flags) is None:
                        return False
        elif actual != expected and not (isinstance(actual, list) and expected in actual):
            return False
    return True


def _apply_update(document: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    for key, values in update.items():
        if key == "$set":
            document.update(copy.deepcopy(values))
        elif key == "$unset":
            for field in values:
                document.pop(field, None)
        elif key == "$inc":
            for field, amount in values.items():
                document[field] = document.get(field, 0) + amount
        elif key == "$push":
            for field, value in values.items():
                document.setdefault(field, []).append(copy.deepcopy(value))
        elif key == "$addToSet":
            for field, value in values.items():
                target = document.setdefault(field, [])
                candidates = value.get("$each", []) if isinstance(value, dict) else [value]
                for candidate in candidates:
                    if candidate not in target:
                        target.append(copy.deepcopy(candidate))
        else:
            document[key] = copy.deepcopy(values)
    return document


class MemoryDatabase:
    """Async document-store adapter used for local demos and isolated tests."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._in_transaction: ContextVar[bool] = ContextVar("memory_transaction", default=False)

    def _rows(self, collection: str) -> list[dict[str, Any]]:
        return self.tables.setdefault(collection, [])

    async def find_one(self, collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
        for row in self._rows(collection):
            if _matches(row, query):
                return copy.deepcopy(row)
        return None

    async def find_many(self, collection: str, query: dict[str, Any] | None = None, *, sort: list[tuple[str, int]] | None = None, skip: int = 0, limit: int = 0) -> list[dict[str, Any]]:
        rows = [copy.deepcopy(row) for row in self._rows(collection) if _matches(row, query or {})]
        for key, direction in reversed(sort or []):
            rows.sort(key=lambda row: (_value(row, key) is None, _value(row, key)), reverse=direction < 0)
        return rows[skip:skip + limit if limit else None]

    async def insert_one(self, collection: str, document: dict[str, Any]) -> dict[str, Any]:
        async def write() -> dict[str, Any]:
            row = copy.deepcopy(document)
            row.setdefault("created_at", utcnow())
            self._rows(collection).append(row)
            return copy.deepcopy(row)
        if self._in_transaction.get():
            return await write()
        async with self._lock:
            return await write()

    async def update_one(self, collection: str, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> bool:
        async def write() -> bool:
            for row in self._rows(collection):
                if _matches(row, query):
                    _apply_update(row, update)
                    return True
            if upsert:
                base = {k: v for k, v in query.items() if not k.startswith("$") and not isinstance(v, dict)}
                self._rows(collection).append(_apply_update(base, update))
                return True
            return False
        if self._in_transaction.get():
            return await write()
        async with self._lock:
            return await write()

    async def find_one_and_update(self, collection: str, query: dict[str, Any], update: dict[str, Any]) -> dict[str, Any] | None:
        async def write() -> dict[str, Any] | None:
            for row in self._rows(collection):
                if _matches(row, query):
                    _apply_update(row, update)
                    return copy.deepcopy(row)
            return None
        if self._in_transaction.get():
            return await write()
        async with self._lock:
            return await write()

    async def delete_one(self, collection: str, query: dict[str, Any]) -> bool:
        async def write() -> bool:
            rows = self._rows(collection)
            for i, row in enumerate(rows):
                if _matches(row, query):
                    del rows[i]
                    return True
            return False
        if self._in_transaction.get():
            return await write()
        async with self._lock:
            return await write()

    async def delete_many(self, collection: str, query: dict[str, Any]) -> int:
        async def write() -> int:
            rows = self._rows(collection)
            kept = [row for row in rows if not _matches(row, query)]
            removed = len(rows) - len(kept)
            self.tables[collection] = kept
            return removed
        if self._in_transaction.get():
            return await write()
        async with self._lock:
            return await write()

    async def count(self, collection: str, query: dict[str, Any] | None = None) -> int:
        return sum(1 for row in self._rows(collection) if _matches(row, query or {}))

    async def create_indexes(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    class _Transaction:
        def __init__(self, database: "MemoryDatabase") -> None:
            self.database = database
            self.snapshot: dict[str, list[dict[str, Any]]] | None = None
            self.token: Any = None
            self.nested = False

        async def __aenter__(self) -> "MemoryDatabase._Transaction":
            if self.database._in_transaction.get():
                self.nested = True
                return self
            await self.database._lock.acquire()
            self.snapshot = copy.deepcopy(self.database.tables)
            self.token = self.database._in_transaction.set(True)
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            if self.nested:
                return False
            if exc_type is not None and self.snapshot is not None:
                self.database.tables = self.snapshot
            if self.token is not None:
                self.database._in_transaction.reset(self.token)
            self.database._lock.release()
            return False

    def transaction(self) -> "MemoryDatabase._Transaction":
        return self._Transaction(self)


class MongoDatabase:
    def __init__(self, uri: str, name: str) -> None:
        self.client = AsyncMongoClient(uri, maxPoolSize=100, minPoolSize=2, serverSelectionTimeoutMS=15000, tz_aware=True)
        self.database = self.client[name]
        self._session: ContextVar[Any] = ContextVar("mongo_session", default=None)
        self._supports_transactions: bool | None = None

    def _kwargs(self) -> dict[str, Any]:
        session = self._session.get()
        return {"session": session} if session is not None else {}

    async def find_one(self, collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
        return await self.database[collection].find_one(query, **self._kwargs())

    async def find_many(self, collection: str, query: dict[str, Any] | None = None, *, sort: list[tuple[str, int]] | None = None, skip: int = 0, limit: int = 0) -> list[dict[str, Any]]:
        cursor = self.database[collection].find(query or {}, **self._kwargs())
        if sort:
            cursor = cursor.sort(sort)
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=limit or 1000)

    async def insert_one(self, collection: str, document: dict[str, Any]) -> dict[str, Any]:
        row = copy.deepcopy(document)
        row.setdefault("created_at", utcnow())
        await self.database[collection].insert_one(row, **self._kwargs())
        return row

    async def update_one(self, collection: str, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False) -> bool:
        result = await self.database[collection].update_one(query, update, upsert=upsert, **self._kwargs())
        return bool(result.modified_count or result.upserted_id)

    async def find_one_and_update(self, collection: str, query: dict[str, Any], update: dict[str, Any]) -> dict[str, Any] | None:
        return await self.database[collection].find_one_and_update(query, update, return_document=ReturnDocument.AFTER, **self._kwargs())

    async def delete_one(self, collection: str, query: dict[str, Any]) -> bool:
        result = await self.database[collection].delete_one(query, **self._kwargs())
        return bool(result.deleted_count)

    async def delete_many(self, collection: str, query: dict[str, Any]) -> int:
        result = await self.database[collection].delete_many(query, **self._kwargs())
        return result.deleted_count

    async def count(self, collection: str, query: dict[str, Any] | None = None) -> int:
        return await self.database[collection].count_documents(query or {}, **self._kwargs())

    async def create_indexes(self) -> None:
        indexes = {
            "users": [("email", {"unique": True}), ("role", {})],
            "files": [("owner_id", {}), ("group_id", {}), ("created_at", {})],
            "shares": [("token_hash", {"unique": True, "partialFilterExpression": {"token_hash": {"$type": "string"}}}), ("expires_at", {}), ("file_id", {}), ("recipient_id", {})],
            "downloads": [("file_id", {}), ("user_id", {}), ("created_at", {})],
            "groups": [("members", {}), ("owner_id", {})],
            "notifications": [("user_id", {}), ("read_at", {})],
            "file_requests": [("requester_id", {}), ("recipient_id", {}), ("status", {}), ("created_at", {})],
            "activity_logs": [("created_at", {}), ("user_id", {}), ("event", {})],
            "otp_records": [("email", {}), ("expires_at", {}), ([('email', 1), ('purpose', 1)], {"name": "one_active_otp_per_purpose", "unique": True, "partialFilterExpression": {"consumed_at": None}})],
        }
        for collection, specs in indexes.items():
            for field, options in specs:
                await self.database[collection].create_index(field, **options)

    async def ping(self) -> bool:
        await self.client.admin.command("ping")
        return True

    async def close(self) -> None:
        await self.client.close()

    class _Transaction:
        def __init__(self, db: "MongoDatabase") -> None:
            self.db = db
            self.session: Any = None
            self.token: Any = None

        async def __aenter__(self) -> "MongoDatabase._Transaction":
            if self.db._session.get() is not None:
                return self
            if self.db._supports_transactions is None:
                try:
                    hello = await self.db.client.admin.command("hello")
                    self.db._supports_transactions = bool(hello.get("setName") or hello.get("msg") == "isdbgrid")
                except Exception:
                    self.db._supports_transactions = False

            if not self.db._supports_transactions:
                self.session = None
                return self

            try:
                self.session = self.db.client.start_session()
                await self.session.start_transaction()
                self.token = self.db._session.set(self.session)
            except Exception:
                if self.session:
                    try:
                        await self.session.end_session()
                    except Exception:
                        pass
                self.session = None
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            if self.session is None:
                return False
            try:
                if exc_type is None:
                    await self.session.commit_transaction()
                else:
                    try:
                        await self.session.abort_transaction()
                    except Exception:
                        pass
            finally:
                if self.token is not None:
                    self.db._session.reset(self.token)
                await self.session.end_session()
            return False

    def transaction(self) -> "MongoDatabase._Transaction":
        return self._Transaction(self)


def make_database(mongodb_uri: str, mongodb_database: str, *, production: bool = False) -> MemoryDatabase | MongoDatabase:
    if mongodb_uri:
        return MongoDatabase(mongodb_uri, mongodb_database)
    if production:
        raise RuntimeError("MONGODB_URI must be configured in production")
    return MemoryDatabase()
