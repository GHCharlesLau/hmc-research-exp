import uuid
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
from database import Base
import enum


class RoomType(str, enum.Enum):
    HHC = "HHC"
    HMC = "HMC"


class SenderRole(str, enum.Enum):
    user = "user"
    partner = "partner"


class ChatRoom(Base):
    __tablename__ = "chat_rooms"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"), index=True)

    room_type: Mapped[RoomType] = mapped_column(SAEnum(RoomType))
    round_number: Mapped[int] = mapped_column(Integer)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)

    # For HHC: the room_id shared by two participants
    room_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # For HMC: the partner participant_id (LLM virtual participant)
    partner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    is_active: Mapped[bool] = mapped_column(default=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    participant: Mapped["Participant"] = relationship(back_populates="chat_rooms")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="chat_room",
        order_by="ChatMessage.created_at",
        lazy="selectin",
        cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_rooms.id"), index=True)

    sender_role: Mapped[SenderRole] = mapped_column(SAEnum(SenderRole))
    text: Mapped[str] = mapped_column(String(5000))
    turn_number: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    chat_room: Mapped["ChatRoom"] = relationship(back_populates="messages")
