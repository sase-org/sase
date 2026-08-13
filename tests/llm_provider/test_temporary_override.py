"""Tests for the shared temporary LLM override state."""

from __future__ import annotations

import json
import time

import pytest

from sase.llm_provider.temporary_override import (
    clear_temporary_override,
    get_active_temporary_override,
    parse_override_duration,
    set_temporary_override,
)
from sase.llm_provider.temporary_override_state import state_path


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


def test_set_unknown_bare_model_falls_back_to_configured_default_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config",
        lambda: {"provider": "claude"},
    )

    override = set_temporary_override("mystery-model", 60.0, source="ace")

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
    path = state_path()
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
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json{{{", encoding="utf-8")

    assert get_active_temporary_override() is None
    assert not path.exists()


def test_missing_required_fields_returns_none_and_deletes() -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provider": "claude"}), encoding="utf-8")

    assert get_active_temporary_override() is None
    assert not path.exists()


def test_wrong_field_types_returns_none_and_deletes() -> None:
    path = state_path()
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
    path = state_path()
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


def test_state_file_uses_v2_keyed_schema() -> None:
    """The default override is written under the v2 ``overrides.default`` key."""
    set_temporary_override("codex/o3", 3600.0, source="ace")
    raw = state_path().read_text(encoding="utf-8")
    data = json.loads(raw)

    assert data["version"] == 2
    entry = data["overrides"]["default"]
    assert entry["provider"] == "codex"
    assert entry["model"] == "o3"
    assert entry["raw_model"] == "codex/o3"
    assert entry["source"] == "ace"
    assert isinstance(entry["created_at"], float)
    assert isinstance(entry["expires_at"], float)


def test_state_file_lives_under_sase_home() -> None:
    set_temporary_override("opus", 60.0, source="ace")
    assert state_path().name == "llm_override.json"
    assert state_path().exists()


def test_legacy_state_file_with_pre_override_keys_still_loads() -> None:
    """A state file written before the worker lane retirement still loads.

    Older SASE versions persisted ``pre_override_*`` snapshot keys (used by the
    now-removed ``@other`` alias). The retired keys must be tolerated/ignored so
    a stale state file does not break a fresh launch.
    """
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = {
        "provider": "codex",
        "model": "o3",
        "raw_model": "codex/o3",
        "created_at": time.time(),
        "expires_at": time.time() + 3600,
        "source": "ace",
        "pre_override_provider": "claude",
        "pre_override_model": "opus",
        "pre_override_raw_model": "opus",
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    fetched = get_active_temporary_override()
    assert fetched is not None
    assert fetched.provider == "codex"
    assert fetched.model == "o3"
    assert not hasattr(fetched, "pre_override_provider")
