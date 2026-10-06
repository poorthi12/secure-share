from pydantic import BaseModel, Field


class FileRenameRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
