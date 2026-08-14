from services.prolific import (
    hash_prolific_id,
    is_prolific_unique_violation,
    is_valid_prolific_id,
    normalize_prolific_id,
    sanitize_prolific_id,
    validate_for_welcome,
)


VALID_ID = "a" * 24


def test_normalize_strips_whitespace():
    assert normalize_prolific_id("  abc  ") == "abc"


def test_valid_prolific_id_accepts_24_alnum():
    assert is_valid_prolific_id(VALID_ID)
    assert is_valid_prolific_id("Ab12" * 6)


def test_valid_prolific_id_rejects_wrong_length_or_chars():
    assert not is_valid_prolific_id("short")
    assert not is_valid_prolific_id("a" * 23)
    assert not is_valid_prolific_id("a" * 25)
    assert not is_valid_prolific_id("a" * 23 + "-")


def test_sanitize_discards_invalid():
    assert sanitize_prolific_id("not-valid") == ""
    assert sanitize_prolific_id(VALID_ID) == VALID_ID


def test_hash_is_deterministic():
    assert hash_prolific_id(VALID_ID) == hash_prolific_id(VALID_ID)
    assert hash_prolific_id(VALID_ID) != hash_prolific_id("b" * 24)


def test_validate_for_welcome_format_error():
    pid, error = validate_for_welcome("too-short")
    assert error is not None
    assert "24" in error


def test_prolific_unique_violation_detects_hash_and_encrypted():
    assert is_prolific_unique_violation(
        Exception('duplicate key value violates unique constraint "ix_participants_prolific_id_hash"')
    )
    assert is_prolific_unique_violation(
        Exception("UniqueViolation on participants_prolific_id_encrypted_key")
    )
    assert not is_prolific_unique_violation(Exception("duplicate key on display_id"))
