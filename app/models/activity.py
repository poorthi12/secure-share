from datetime import datetime

from pydantic import BaseModel, Field


class ActivityDocument(BaseModel):
    id: str
    event: str
    user_id: str | None = None
    detail: str = ""
    target_id: str | None = None
    target_type: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
