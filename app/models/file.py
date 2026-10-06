from datetime import datetime

from pydantic import BaseModel, Field


class FileDocument(BaseModel):
    id: str
    filename: str = Field(max_length=180)
    content_type: str
    size: int = Field(ge=0)
    owner_id: str
    group_id: str | None = None
    storage_key: str
    encrypted: bool = True
    encryption_algorithm: str = "AES-256-GCM"
    created_at: datetime
    deleted_at: datetime | None = None
