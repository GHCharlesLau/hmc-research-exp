from models.participant import Step
from dependencies.participant import can_access_payment, should_reuse_consent_session
from schemas.survey import validate_likert_fields, DemographicsSubmit
from services.export import _build_survey_header
from services.scales import LIKERT_SCALES, get_page_likert_fields
from config import _convert_db_url
from services.auth import parse_participant_cookie, sign_participant_id


class _P:
    def __init__(self, current_step, is_finished=False):
        self.current_step = current_step
        self.is_finished = is_finished


def test_payment_blocked_before_demographics():
    assert can_access_payment(_P(Step.survey_a)) is False
    assert can_access_payment(_P(Step.welcome)) is False
    assert can_access_payment(_P(Step.chat_r2)) is False


def test_payment_allowed_at_payment_or_finished():
    assert can_access_payment(_P(Step.payment)) is True
    assert can_access_payment(_P(Step.survey_a, is_finished=True)) is True


def test_likert_validation_rejects_out_of_range():
    err = validate_likert_fields({"sen_a_1": 8}, ["sen_a_1"])
    assert err is not None
    assert validate_likert_fields({"sen_a_1": 4}, ["sen_a_1"]) is None


def test_page_a_fields_match_registry():
    fields = get_page_likert_fields("A")
    assert "sen_a_1" in fields
    assert "fee_h_4" in fields
    assert "ce_4" in fields
    assert len(fields) == 12


def test_export_headers_include_scale_fields():
    header = _build_survey_header()
    for scale in LIKERT_SCALES:
        if scale.page.startswith("_"):
            continue
        for name in scale.field_names:
            assert name in header
    assert "age" in header
    assert "partner_label_check" in header or "manip_check" in header


def test_format_export_timestamp_excel_safe():
    from datetime import datetime, timezone
    from services.export import format_export_timestamp

    assert format_export_timestamp(None) == ""
    dt = datetime(2026, 8, 26, 9, 15, 3, tzinfo=timezone.utc)
    assert format_export_timestamp(dt) == '="2026-08-26 09:15:03"'
    naive = datetime(2026, 8, 26, 9, 15, 3)
    assert format_export_timestamp(naive) == '="2026-08-26 09:15:03"'


def test_partner_display_for_room_uses_shared_room_not_latest_partner():
    from models.chat import RoomType
    from services.export import partner_display_for_room

    class _Room:
        def __init__(self, room_type, room_id, partner_id=None):
            self.room_type = room_type
            self.room_id = room_id
            self.partner_id = partner_id

    p1, p2, p3 = "id-1", "id-2", "id-3"
    lookup = {p1: "P-0001", p2: "P-0002", p3: "P-0003"}
    members = {
        "hhc-1-ab": {p1: "P-0001", p2: "P-0002"},
        "hhc-2-ac": {p1: "P-0001", p3: "P-0003"},
    }
    r1 = _Room(RoomType.HHC, "hhc-1-ab")
    r2 = _Room(RoomType.HHC, "hhc-2-ac")
    hmc = _Room(RoomType.HMC, "solo-room")

    assert partner_display_for_room(r1, p1, members, lookup) == "P-0002"
    assert partner_display_for_room(r2, p1, members, lookup) == "P-0003"
    assert partner_display_for_room(hmc, p1, members, lookup) == ""


def test_best_room_for_round_prefers_more_turns():
    from datetime import datetime, timezone
    from models.chat import SenderRole
    from services.export import best_room_for_round

    class _Msg:
        def __init__(self, role):
            self.sender_role = role

    class _Room:
        def __init__(self, round_number, n_complete, created):
            self.round_number = round_number
            self.created_at = created
            self.messages = (
                [_Msg(SenderRole.user)] * n_complete
                + [_Msg(SenderRole.partner)] * n_complete
            )

    early = datetime(2026, 1, 1, tzinfo=timezone.utc)
    late = datetime(2026, 1, 2, tzinfo=timezone.utc)
    retry = _Room(1, 1, early)
    keep = _Room(1, 4, late)
    r2 = _Room(2, 2, late)
    chosen = best_room_for_round([retry, keep, r2], 1)
    assert chosen is keep
    assert best_room_for_round([retry, keep, r2], 2) is r2
    assert best_room_for_round([retry, keep, r2], 3) is None


def test_chat_message_unique_constraint_declared():
    from models.chat import ChatMessage

    names = {c.name for c in ChatMessage.__table__.constraints if getattr(c, "name", None)}
    assert "uq_chat_messages_room_role_turn" in names


def test_convert_db_url_adds_driver():
    raw = "postgresql://user:pass@localhost:5432/db"
    assert _convert_db_url(raw, "asyncpg") == "postgresql+asyncpg://user:pass@localhost:5432/db"
    already = "postgresql+psycopg2://user:pass@localhost:5432/db"
    assert _convert_db_url(already, "asyncpg").startswith("postgresql+asyncpg://")


def test_convert_db_url_accepts_postgres_scheme_and_sslmode():
    url = _convert_db_url(
        "postgres://user:pass@host/db?sslmode=require",
        "asyncpg",
    )
    assert url.startswith("postgresql+asyncpg://")
    assert "ssl=require" in url
    assert "sslmode=" not in url


def test_convert_db_url_psycopg2_keeps_sslmode():
    url = _convert_db_url(
        "postgresql://user:pass@host/db?sslmode=require",
        "psycopg2",
    )
    assert url.startswith("postgresql+psycopg2://")
    assert "sslmode=require" in url


def test_signed_participant_cookie_roundtrip():
    pid = "11111111-1111-1111-1111-111111111111"
    signed = sign_participant_id(pid)
    parsed = parse_participant_cookie(signed)
    assert str(parsed) == pid


def test_tampered_cookie_rejected():
    pid = "11111111-1111-1111-1111-111111111111"
    signed = sign_participant_id(pid)
    tampered = signed[:-1] + ("0" if signed[-1] != "0" else "1")
    assert parse_participant_cookie(tampered) is None


def test_legacy_unsigned_uuid_cookie_still_accepted():
    pid = "11111111-1111-1111-1111-111111111111"
    assert str(parse_participant_cookie(pid)) == pid


def test_demographics_age_bounds():
    DemographicsSubmit(age=18)
    try:
        DemographicsSubmit(age=17)
        assert False, "expected validation error"
    except Exception:
        pass


def test_consent_reuses_session_only_at_consent_step():
    assert should_reuse_consent_session(_P(Step.consent)) is True
    assert should_reuse_consent_session(_P(Step.welcome)) is False
    assert should_reuse_consent_session(_P(Step.priming)) is False
    assert should_reuse_consent_session(None) is False


def test_duration_over_max_threshold():
    from services.export import duration_over_max

    assert duration_over_max(None, 600) is False
    assert duration_over_max(599, 600) is False
    assert duration_over_max(600, 600) is True
    assert duration_over_max(900, 600) is True
    assert duration_over_max("", 600) is False


def test_export_quality_filters():
    from services.export import should_exclude_from_export

    assert should_exclude_from_export(is_timeout=True, exclude_timeout=True) is True
    assert should_exclude_from_export(is_timeout=True, exclude_timeout=False) is False
    assert should_exclude_from_export(is_dropout=True, exclude_dropout=True) is True
    assert should_exclude_from_export(r1_over_max=True, exclude_over_max=True) is True
    assert should_exclude_from_export(r2_over_max=True, exclude_over_max=True) is True
    assert should_exclude_from_export(r1_over_max=True, exclude_over_max=False) is False
