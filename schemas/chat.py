from pydantic import BaseModel


class ChatMessageCreate(BaseModel):
    text: str


class ChatEndRequest(BaseModel):
    reason: str = "user"  # "user" | "timeout" | "max_turns"
