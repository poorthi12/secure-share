from datetime import datetime

from pydantic import BaseModel


class NotificationDocument(BaseModel):
    id: str
    user_id: str
    kind: str
    title: str
    message: str
    target_url: str = ""
    read_at: datetime | None = None
    created_at: datetime
