import uuid
from sqlalchemy import String, Boolean, Integer, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
from database import Base
import enum


class TaskType(str, enum.Enum):
    emotionTask = "emotionTask"
    functionTask = "functionTask"


class Partnership(str, enum.Enum):
    HHC = "HHC"
    HMC = "HMC"


class PartnerLabel(str, enum.Enum):
    chatbot = "chatbot"
    human = "human"


class Step(str, enum.Enum):
    consent = "consent"
    welcome = "welcome"
    priming = "priming"
    instructions_r1 = "instructions_r1"
    chat_r1 = "chat_r1"
    instructions_r2 = "instructions_r2"
    chat_r2 = "chat_r2"
    survey_prompt = "survey_prompt"
    survey_a = "survey_a"
    survey_b = "survey_b"
    survey_c = "survey_c"
    demographics = "demographics"
    payment = "payment"


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    display_id: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    prolific_id_encrypted: Mapped[str] = mapped_column(String(256), unique=True, nullable=True)
    session_id: Mapped[str] = mapped_column(String(100), nullable=True)
    study_id: Mapped[str] = mapped_column(String(100), nullable=True)

    # Conditions
    task_type: Mapped[TaskType] = mapped_column(SAEnum(TaskType))
    partnership: Mapped[Partnership] = mapped_column(SAEnum(Partnership))
    partner_label: Mapped[PartnerLabel] = mapped_column(SAEnum(PartnerLabel))

    # State
    current_step: Mapped[Step] = mapped_column(SAEnum(Step), default=Step.consent)
    current_round: Mapped[int] = mapped_column(Integer, default=1)
    is_finished: Mapped[bool] = mapped_column(Boolean, default=False)
    is_timeout: Mapped[bool] = mapped_column(Boolean, default=False)
    hhc_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)

    # Profile
    avatar: Mapped[str] = mapped_column(String(50), nullable=True)
    nickname: Mapped[str] = mapped_column(String(50), nullable=True)

    # Priming text
    priming_text: Mapped[str] = mapped_column(String(2000), nullable=True)

    # Secure resume token (for bookmarkable session resumption)
    resume_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)

    # Chat partner info (for HHC)
    partner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    chat_rooms: Mapped[list["ChatRoom"]] = relationship(back_populates="participant", lazy="selectin")
    survey_response: Mapped["SurveyResponse | None"] = relationship(back_populates="participant", uselist=False, lazy="selectin")

    @property
    def chatbot_identity(self) -> str:
        """Return the chatbot identity based on partner_label."""
        return "MyBot" if self.partner_label == PartnerLabel.chatbot else "Tommy"

    @property
    def chatbot_avatar(self) -> str:
        """Return the partner avatar filename based on partner_label."""
        return "myBot.png" if self.partner_label == PartnerLabel.chatbot else "fox.png"


# Import at end to avoid circular imports
from models.chat import ChatRoom  # noqa: E402
from models.survey import SurveyResponse  # noqa: E402
