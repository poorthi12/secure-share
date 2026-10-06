from pydantic import BaseModel


class NotificationPreferences(BaseModel):
    sharing: bool = True
    downloads: bool = True
    groups: bool = True
    security: bool = True
