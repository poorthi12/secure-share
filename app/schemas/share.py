from datetime import datetime

from pydantic import BaseModel, Field


class ShareCreateRequest(BaseModel):
    file_id: str
    recipient_email: str | None = None
    group_id: str | None = None
    expires_at: datetime | None = None
    download_limit: int | None = Field(default=None, ge=1)
    password: str | None = Field(default=None, min_length=8)
