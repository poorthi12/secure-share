from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class GroupMember(BaseModel):
    user_id: str
    role: Literal["owner", "admin", "member"] = "member"
    can_upload: bool = False
    joined_at: datetime


class GroupDocument(BaseModel):
    id: str
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=500)
    owner_id: str
    members: list[GroupMember]
    created_at: datetime
