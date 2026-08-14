import uuid
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
from database import Base


class SurveyResponse(Base):
    __tablename__ = "survey_responses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    participant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("participants.id"), unique=True, index=True)

    # Page A: Agency (sen_a) × 4 + Feeling Heard (fee_h) × 4 + Cognitive Engagement (ce) × 4
    sen_a_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sen_a_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sen_a_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sen_a_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_h_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_h_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_h_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_h_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ce_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ce_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ce_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ce_4: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Page B: Manipulation Check (manip_check) × 1 + AI Usage (ai_usage) × 1 + AI Literacy (ail) × 4
    manip_check: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_usage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ail_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ail_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ail_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ail_4: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Page C: Outcome Variables (25 items) ──
    # Common Ground Perception (ccg) × 3
    ccg_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ccg_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ccg_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Communication Satisfaction (ccs) × 4
    ccs_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ccs_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ccs_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ccs_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Perceived Communication Effectiveness (pce) × 4
    pce_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pce_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pce_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pce_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Perceived Communication Appropriateness (pca) × 4
    pca_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pca_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pca_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pca_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Homophily — Attitude (phom) × 4
    phom_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phom_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phom_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phom_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Self-Other Similarity (psos) × 2
    psos_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    psos_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Perspective Taking — IRI (iri_pt) × 4
    iri_pt_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_pt_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_pt_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_pt_4: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Demographics
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(50), nullable=True)
    race: Mapped[str | None] = mapped_column(String(50), nullable=True)
    education: Mapped[str | None] = mapped_column(String(50), nullable=True)
    partisanship: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Religiosity × 4
    rlg_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rlg_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rlg_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rlg_4: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    participant: Mapped["Participant"] = relationship(back_populates="survey_response")
