"""Tests for the shared temporary LLM override state."""

from __future__ import annotations

import json
import time

import pytest

from sase.llm_provider.temporary_override import (
    _state_path,
    clear_temporary_override,
    get_active_temporary_override,
    parse_override_duration,
    resolve_effective_default_provider_model,
    set_temporary_override,
)


# ---------------------------------------------------------------------------
# parse_override_duration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("15m", 900.0),
        ("30m", 1800.0),
        ("1h", 3600.0),
        ("2h", 7200.0),
        ("1h30m", 5400.0),
        ("90m", 5400.0),
        ("2h15m30s", 8130.0),
        ("45s", 45.0),
        ("until cleared", None),
        ("Until Cleared", None),
        ("until_cleared", None),
    ],
)
def test_parse_override_duration_valid(value: str, expected: float | None) -> None:
    assert parse_override_duration(value) == expected


def test_parse_override_duration_bare_minutes() -> None:
    assert parse_override_duration("45") == 45 * 60


@pytest.mark.parametrize(
    "value",
    ["", "   ", "abc", "1d", "1h-30m", "1.5h", "-30m"],
)
def test_parse_override_duration_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        parse_override_duration(value)


# ---------------------------------------------------------------------------
# set / get / clear
# ---------------------------------------------------------------------------


def test_get_when_no_state_returns_none() -> None:
    assert get_active_temporary_override() is None


def test_set_then_get_known_bare_model() -> None:
    override = set_temporary_override("opus", 3600.0, source="test")

    assert override.provider == "claude"
    assert override.model == "opus"
    assert override.raw_model == "opus"
    assert override.source == "test"
    assert override.expires_at is not None
    assert override.expires_at > override.created_at

    fetched = get_active_temporary_override()
    assert fetched is not None
    assert fetched.provider == "claude"
    assert fetched.model == "opus"


def test_set_explicit_provider_model_syntax() -> None:
    override = set_temporary_override("codex/o3", 60.0, source="ace")
    assert override.provider == "codex"
    assert override.model == "o3"
    assert override.raw_model == "codex/o3"


def test_set_unknown_bare_model_falls_back_to_default_provider() -> None:
    override = set_temporary_override("mystery-model", 60.0, source="ace")
    # Default provider in the test environment is "claude" (first by
    # autodetect priority among installed plugins).
    assert override.provider == "claude"
    assert override.model == "mystery-model"


def test_set_until_cleared_writes_no_expiry() -> None:
    override = set_temporary_override("opus", None, source="ace")
    assert override.expires_at is None

    fetched = get_active_temporary_override()
    assert fetched is not None
    assert fetched.expires_at is None


def test_set_overwrites_existing_override() -> None:
    set_temporary_override("opus", 60.0, source="ace")
    set_temporary_override("codex/o3", 120.0, source="ace")

    fetched = get_active_temporary_override()
    assert fetched is not None
    assert fetched.provider == "codex"
    assert fetched.model == "o3"


def test_clear_removes_active_override() -> None:
    set_temporary_override("opus", 60.0, source="ace")
    assert clear_temporary_override() is True
    assert get_active_temporary_override() is None


def test_clear_when_none_returns_false() -> None:
    assert clear_temporary_override() is False


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def test_expired_override_returns_none_and_deletes_file() -> None:
    set_temporary_override("opus", 60.0, source="ace")
    path = _state_path()
    assert path.exists()

    future = time.time() + 3600
    assert get_active_temporary_override(now=future) is None
    assert not path.exists()


def test_expiry_at_exact_boundary_is_expired() -> None:
    override = set_temporary_override("opus", 60.0, source="ace")
    assert override.expires_at is not None
    # `now == expires_at` is treated as expired (not strictly less than).
    assert get_active_temporary_override(now=override.expires_at) is None


def test_until_cleared_never_expires() -> None:
    set_temporary_override("opus", None, source="ace")
    far_future = time.time() + 10 * 365 * 24 * 3600
    fetched = get_active_temporary_override(now=far_future)
    assert fetched is not None
    assert fetched.model == "opus"


# ---------------------------------------------------------------------------
# Robustness against bad state files
# ---------------------------------------------------------------------------


def test_malformed_json_returns_none_and_deletes() -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json{{{", encoding="utf-8")

    assert get_active_temporary_override() is None
    assert not path.exists()


def test_missing_required_fields_returns_none_and_deletes() -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provider": "claude"}), encoding="utf-8")

    assert get_active_temporary_override() is None
    assert not path.exists()


def test_wrong_field_types_returns_none_and_deletes() -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "provider": 123,  # wrong type
                "model": "opus",
                "raw_model": "opus",
                "created_at": time.time(),
                "expires_at": None,
                "source": "ace",
            }
        ),
        encoding="utf-8",
    )

    assert get_active_temporary_override() is None
    assert not path.exists()


def test_top_level_list_returns_none_and_deletes() -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    assert get_active_temporary_override() is None
    assert not path.exists()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "   "])
def test_set_empty_raw_model_raises(raw: str) -> None:
    with pytest.raises(ValueError):
        set_temporary_override(raw, 60.0, source="ace")


@pytest.mark.parametrize("duration", [0.0, -1.0, -3600.0])
def test_set_non_positive_duration_raises(duration: float) -> None:
    with pytest.raises(ValueError):
        set_temporary_override("opus", duration, source="ace")


def test_set_empty_source_raises() -> None:
    with pytest.raises(ValueError):
        set_temporary_override("opus", 60.0, source=" ")


# ---------------------------------------------------------------------------
# State-file shape
# ---------------------------------------------------------------------------


def test_state_file_contains_expected_keys() -> None:
    set_temporary_override("codex/o3", 3600.0, source="ace")
    raw = _state_path().read_text(encoding="utf-8")
    data = json.loads(raw)

    assert data["provider"] == "codex"
    assert data["model"] == "o3"
    assert data["raw_model"] == "codex/o3"
    assert data["source"] == "ace"
    assert isinstance(data["created_at"], float)
    assert isinstance(data["expires_at"], float)


def test_state_file_lives_under_sase_home() -> None:
    set_temporary_override("opus", 60.0, source="ace")
    assert _state_path().name == "llm_override.json"
    assert _state_path().exists()


# ---------------------------------------------------------------------------
# resolve_effective_default_provider_model
# ---------------------------------------------------------------------------


def test_resolve_effective_default_no_override() -> None:
    provider, model = resolve_effective_default_provider_model()
    assert provider in {"claude", "codex", "gemini"}
    assert isinstance(model, str) and model


def test_resolve_effective_default_with_override() -> None:
    set_temporary_override("codex/o3", 3600.0, source="ace")
    provider, model = resolve_effective_default_provider_model()
    assert provider == "codex"
    assert model == "o3"


def test_resolve_effective_default_ignores_expired_override() -> None:
    set_temporary_override("codex/o3", 60.0, source="ace")
    # Force the override to be in the past by rewriting state.
    path = _state_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["expires_at"] = time.time() - 1
    path.write_text(json.dumps(data), encoding="utf-8")

    provider, _ = resolve_effective_default_provider_model()
    assert provider != "codex" or _ != "o3"
    # And the stale state file is cleaned up by the read.
    assert not path.exists()
