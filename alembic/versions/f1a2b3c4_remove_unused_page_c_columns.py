"""remove unused Page C survey columns

Keeps only: ccg(3), ccs(4), pce(4), pca(4), phom(4), psos(2), iri_pt(4) = 25 items.
Drops 55 columns from 18 unused scales.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f1a2b3c4'
down_revision: Union[str, None] = 'e8f2a1b3c4d5'

DROP_COLUMNS = [
    # Conversation Goal Attainment
    "cga_1", "cga_2",
    # Perceived Conversation Informativeness
    "cinf_1", "cinf_2",
    # Perceived Mutual Understanding
    "cmu_1",
    # Perceived Understanding
    "cpu_1", "cpu_2", "cpu_3", "cpu_4",
    # Connection Felt During Conversations
    "cconn_1", "cconn_2", "cconn_3", "cconn_4",
    # Enjoyment
    "cenj_1", "cenj_2", "cenj_3",
    # Intention to Engage in Future Social Interactions
    "cfsi_1",
    # Active-Empathic Listening
    "pael_1", "pael_2", "pael_3", "pael_4",
    # Interpersonal Attraction — Task
    "pta_1", "pta_2", "pta_3", "pta_4",
    # Interpersonal Attraction — Social
    "psa_1", "psa_2", "psa_3", "psa_4",
    # Willingness to Communicate Again
    "pwca_1", "pwca_2",
    # Willingness to Seek Future Advice
    "pwsa_1", "pwsa_2",
    # Liking
    "plik_1", "plik_2", "plik_3", "plik_4",
    # Empathic Concern
    "pec_1", "pec_2", "pec_3",
    # Perceived Empathic Concern
    "ppec_1", "ppec_2", "ppec_3",
    # Dehumanization Propensity
    "dhm_1", "dhm_2", "dhm_3", "dhm_4",
    # IRI Empathic Concern
    "iri_ec_1", "iri_ec_2", "iri_ec_3", "iri_ec_4",
    # IRI Personal Distress
    "iri_pd_1", "iri_pd_2", "iri_pd_3", "iri_pd_4",
]


def upgrade() -> None:
    for col in DROP_COLUMNS:
        op.execute(sa.text(f"ALTER TABLE survey_responses DROP COLUMN IF EXISTS {col}"))


def downgrade() -> None:
    for col in DROP_COLUMNS:
        op.execute(sa.text(
            f"ALTER TABLE survey_responses ADD COLUMN IF NOT EXISTS {col} INTEGER"
        ))
