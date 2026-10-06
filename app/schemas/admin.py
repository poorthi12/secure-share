from pydantic import BaseModel


class AccountStatusUpdate(BaseModel):
    disabled: bool
