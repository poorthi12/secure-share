from pydantic import BaseModel, EmailStr, Field


class UserProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    avatar_url: str = ""


class UserSummary(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str = "student"
