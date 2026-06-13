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
    resolve_effective_worker_provider_model,
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


def _mock_provider_config(
    monkeypatch: pytest.MonkeyPatch, cfg: dict[str, object]
) -> None:
    """Patch the config lookup at every module that imported it directly."""
    monkeypatch.setattr("sase.llm_provider.config.get_llm_provider_config", lambda: cfg)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: cfg
    )


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


def test_worker_override_uses_separate_state_file() -> None:
    primary = set_temporary_override("claude/opus", 3600.0, source="test")
    worker = set_temporary_override(
        "codex/gpt-5.5", 3600.0, source="test", role="worker"
    )

    assert _state_path().name == "llm_override.json"
    assert _state_path(role="worker").name == "llm_worker_override.json"
    assert _state_path().exists()
    assert _state_path(role="worker").exists()
    assert primary.provider == "claude"
    assert worker.provider == "codex"

    fetched_primary = get_active_temporary_override()
    fetched_worker = get_active_temporary_override(role="worker")
    assert fetched_primary is not None
    assert fetched_worker is not None
    assert fetched_primary.model == "opus"
    assert fetched_worker.model == "gpt-5.5"


def test_clear_worker_override_does_not_touch_primary() -> None:
    set_temporary_override("claude/opus", 3600.0, source="test")
    set_temporary_override("codex/o3", 3600.0, source="test", role="worker")

    assert clear_temporary_override(role="worker") is True

    assert get_active_temporary_override(role="worker") is None
    primary = get_active_temporary_override()
    assert primary is not None
    assert primary.provider == "claude"
    assert primary.model == "opus"


def test_clear_primary_override_does_not_touch_worker() -> None:
    set_temporary_override("claude/opus", 3600.0, source="test")
    set_temporary_override("codex/o3", 3600.0, source="test", role="worker")

    assert clear_temporary_override() is True

    assert get_active_temporary_override() is None
    worker = get_active_temporary_override(role="worker")
    assert worker is not None
    assert worker.provider == "codex"
    assert worker.model == "o3"


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


def test_worker_expiry_deletes_only_worker_file() -> None:
    set_temporary_override("claude/opus", 3600.0, source="test")
    worker = set_temporary_override("codex/o3", 60.0, source="test", role="worker")

    assert worker.expires_at is not None
    assert get_active_temporary_override(now=worker.expires_at, role="worker") is None
    assert not _state_path(role="worker").exists()
    assert _state_path().exists()
    assert get_active_temporary_override() is not None


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


def test_worker_state_file_lives_under_sase_home() -> None:
    set_temporary_override("codex/o3", 60.0, source="ace", role="worker")
    assert _state_path(role="worker").name == "llm_worker_override.json"
    assert _state_path(role="worker").exists()


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


# ---------------------------------------------------------------------------
# resolve_effective_worker_provider_model
# ---------------------------------------------------------------------------


def test_resolve_effective_worker_prefers_worker_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"claude": "gemini/gemini-2.5-pro"}},
    )
    set_temporary_override("codex/o3", 3600.0, source="ace")
    set_temporary_override("codex/gpt-5.5", 3600.0, source="ace", role="worker")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_uses_configured_provider_syntax(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"claude": "codex/gpt-5.5"}},
    )
    set_temporary_override("claude/sonnet", 3600.0, source="ace")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_uses_configured_known_bare_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"claude": "gpt-5.5"}},
    )

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_uses_configured_alias_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {"claude": "fast-worker"},
            "model_aliases": {"fast-worker": "codex/gpt-5.5"},
        },
    )

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_exact_key_beats_bare_model_and_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {
                "claude": "claude/sonnet",
                "opus": "gemini/gemini-2.5-pro",
                "claude/opus": "codex/gpt-5.5",
            },
        },
    )

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_bare_model_key_beats_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {
                "claude": "gemini/gemini-2.5-pro",
                "opus": "codex/gpt-5.5",
            },
        },
    )

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "gpt-5.5")


def test_resolve_effective_worker_provider_key_does_not_cross_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {
            "provider": "codex",
            "worker_models": {"claude": "gemini/gemini-2.5-pro"},
        },
    )

    assert resolve_effective_worker_provider_model() == (
        resolve_effective_default_provider_model()
    )


def test_resolve_effective_worker_primary_override_selects_mapping_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "worker_models": {
                "claude": "gemini/gemini-2.5-pro",
                "codex": "claude/sonnet",
            },
        },
    )
    set_temporary_override("codex/o3", 3600.0, source="ace")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("claude", "sonnet")


def test_resolve_effective_worker_unknown_config_model_uses_config_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"codex": "custom-worker-model"}},
    )
    set_temporary_override("codex/o3", 3600.0, source="ace")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("claude", "custom-worker-model")


def test_resolve_effective_worker_falls_through_to_primary_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(monkeypatch, {"provider": "claude"})
    set_temporary_override("codex/o3", 3600.0, source="ace")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "o3")


def test_resolve_effective_worker_without_worker_state_matches_primary_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_effective_worker_provider_model() == (
        resolve_effective_default_provider_model()
    )


def test_resolve_effective_worker_self_reference_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"codex": "worker"}},
    )
    set_temporary_override("codex/o3", 3600.0, source="ace")

    provider, model = resolve_effective_worker_provider_model()
    assert (provider, model) == ("codex", "o3")


def test_worker_override_captures_worker_lane_pre_override_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_provider_config(
        monkeypatch,
        {"provider": "claude", "worker_models": {"claude": "codex/gpt-5.5"}},
    )

    override = set_temporary_override(
        "claude/sonnet", 3600.0, source="ace", role="worker"
    )

    assert override.pre_override_provider == "codex"
    assert override.pre_override_model == "gpt-5.5"
    assert override.pre_override_raw_model == "gpt-5.5"


# ---------------------------------------------------------------------------
# pre-override snapshot (for the reserved "other" alias)
# ---------------------------------------------------------------------------


def test_set_captures_configured_default_as_pre_override_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no prior override, the snapshot is the configured default."""
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config",
        lambda: {"provider": "claude"},
    )

    override = set_temporary_override("codex/o3", 3600.0, source="ace")

    assert override.pre_override_provider == "claude"
    # ClaudeCodeProvider resolves "large" → "opus".
    assert override.pre_override_model == "opus"


def test_set_on_top_of_existing_captures_prior_override_snapshot() -> None:
    """A second override snapshots the first override's resolved (provider, model)."""
    set_temporary_override("opus", 3600.0, source="ace")
    override = set_temporary_override("codex/o3", 3600.0, source="ace")

    assert override.pre_override_provider == "claude"
    assert override.pre_override_model == "opus"
    assert override.pre_override_raw_model == "opus"


def test_legacy_state_file_loads_with_none_pre_override_fields() -> None:
    """A state file written before pre_override_* existed still loads."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = {
        "provider": "codex",
        "model": "o3",
        "raw_model": "codex/o3",
        "created_at": time.time(),
        "expires_at": time.time() + 3600,
        "source": "ace",
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    fetched = get_active_temporary_override()
    assert fetched is not None
    assert fetched.provider == "codex"
    assert fetched.pre_override_provider is None
    assert fetched.pre_override_model is None
    assert fetched.pre_override_raw_model is None


def test_state_file_persists_pre_override_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new snapshot fields round-trip through the state file."""
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config",
        lambda: {"provider": "claude"},
    )
    set_temporary_override("codex/o3", 3600.0, source="ace")
    data = json.loads(_state_path().read_text(encoding="utf-8"))

    assert data["pre_override_provider"] == "claude"
    assert data["pre_override_model"] == "opus"
    assert data["pre_override_raw_model"] == "opus"
