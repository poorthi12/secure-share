from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class UserDocument(BaseModel):
    id: str
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password_hash: str
    role: Literal["student", "admin"] = "student"
    email_verified: bool = False
    disabled: bool = False
    storage_used: int = 0
    created_at: datetime

