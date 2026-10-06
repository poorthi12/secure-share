from datetime import datetime

from pydantic import BaseModel, Field


class ShareDocument(BaseModel):
    id: str
    file_id: str
    sender_id: str
    recipient_id: str | None = None
    group_id: str | None = None
    token_hash: str | None = None
    password_hash: str | None = None
    is_link: bool = False
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    download_limit: int | None = Field(default=None, ge=1)
    download_count: int = Field(default=0, ge=0)
