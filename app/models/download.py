from datetime import datetime

from pydantic import BaseModel


class DownloadDocument(BaseModel):
    id: str
    user_id: str | None = None
    file_id: str
    share_id: str | None = None
    ip: str | None = None
    user_agent: str = ""
    created_at: datetime
