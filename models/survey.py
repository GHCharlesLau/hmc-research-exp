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

    # ── Page C: Outcome Variables ──
    # Conversation outcomes
    # Conversation Goal Attainment (cga) × 2
    cga_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cga_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Perceived Conversation Informativeness (cinf) × 2
    cinf_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cinf_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Common Ground Perception (ccg) × 3
    ccg_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ccg_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ccg_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Perceived Mutual Understanding (cmu) × 1
    cmu_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Perceived Understanding (cpu) × 4
    cpu_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpu_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpu_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpu_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Communication Satisfaction (ccs) × 4
    ccs_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ccs_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ccs_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ccs_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Connection Felt During Conversations (cconn) × 4
    cconn_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cconn_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cconn_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cconn_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Enjoyment (cenj) × 3
    cenj_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cenj_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cenj_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Intention to Engage in Future Social Interactions (cfsi) × 1
    cfsi_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Partner perceptions
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
    # Active-Empathic Listening (pael) × 4
    pael_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pael_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pael_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pael_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Interpersonal Attraction - Task (pta) × 4
    pta_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pta_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pta_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pta_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Interpersonal Attraction - Social (psa) × 4
    psa_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    psa_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    psa_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    psa_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Homophily - Attitude (phom) × 4
    phom_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phom_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phom_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phom_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Self-Other Similarity (psos) × 2
    psos_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    psos_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Willingness to Communicate Again (pwca) × 2
    pwca_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pwca_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Willingness to Seek Future Advice (pwsa) × 2
    pwsa_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pwsa_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Liking (plik) × 4
    plik_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plik_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plik_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plik_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Empathic Concern (pec) × 3
    pec_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pec_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pec_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Perceived Empathic Concern (ppec) × 3
    ppec_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ppec_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ppec_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Individual differences
    # Dehumanization Propensity (dhm) × 4
    dhm_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dhm_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dhm_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dhm_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # IRI Perspective Taking (iri_pt) × 4
    iri_pt_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_pt_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_pt_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_pt_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # IRI Empathic Concern (iri_ec) × 4
    iri_ec_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_ec_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_ec_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_ec_4: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # IRI Personal Distress (iri_pd) × 4
    iri_pd_1: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_pd_2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_pd_3: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iri_pd_4: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
