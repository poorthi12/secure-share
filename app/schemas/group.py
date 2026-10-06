from pydantic import BaseModel, Field


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=500)
