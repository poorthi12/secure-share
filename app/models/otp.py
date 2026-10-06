from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class OtpDocument(BaseModel):
    id: str
    email: str
    purpose: Literal["verify_email", "reset_password"]
    otp_hash: str
    attempts: int = 0
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
