from pydantic import BaseModel


class AdminLogin(BaseModel):
    password: str


class ConfigUpdate(BaseModel):
    key: str
    value: str
    description: str | None = None


class ExportRequest(BaseModel):
    format: str  # "participant" or "chat"
