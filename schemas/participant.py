from pydantic import BaseModel
from datetime import datetime
from models.participant import TaskType, Partnership, PartnerLabel, Step


class ParticipantCreate(BaseModel):
    prolific_id: str | None = None
    session_id: str | None = None
    study_id: str | None = None


class ParticipantResponse(BaseModel):
    id: str
    display_id: str
    task_type: TaskType
    partnership: Partnership
    partner_label: PartnerLabel
    current_step: Step
    current_round: int
    is_finished: bool
    avatar: str | None = None
    nickname: str | None = None
    chatbot_identity: str = ""
    chatbot_avatar: str = ""
    hhc_fallback: bool = False

    class Config:
        from_attributes = True
