"""Rust-backed temporary default-effort facade and launch precedence tests."""

from __future__ import annotations

import math

import pytest

import sase.llm_provider.config as llm_config
import sase.llm_provider.effort_override as effort_state
from sase.llm_provider.effort_override import (
    EffortOverrideStateError,
    TemporaryEffortOverride,
    clear_effort_override,
    get_active_effort_override,
    set_effort_override,
    set_effort_override_until,
)
from sase.xprompt.directives import PromptDirectives
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED

_NOW = 1_800_000_000.0


def _record(
    effort: str = "medium", *, expires_at: float | None = _NOW + 900.0
) -> TemporaryEffortOverride:
    return TemporaryEffortOverride(
        version=1,
        effort=effort,
        created_at=_NOW,
        expires_at=expires_at,
        source="test",
    )


def test_facade_round_trips_every_level_and_honors_sase_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    for level in EFFORT_LEVELS_ORDERED:
        written = set_effort_override(level, 900.0, source="test", now=_NOW)
        assert written.effort == level
        assert written.expires_at == _NOW + 900.0
        assert get_active_effort_override(_NOW) == written
    assert (tmp_path / "llm_effort_override.json").is_file()


def test_facade_exact_expiry_and_idempotent_clear(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    written = set_effort_override_until("high", _NOW + 5.0, source="test", now=_NOW)
    assert get_active_effort_override(_NOW + 4.999) == written
    assert get_active_effort_override(_NOW + 5.0) is None
    assert clear_effort_override() is False
    set_effort_override("low", None, source="test", now=_NOW)
    assert clear_effort_override() is True
    assert clear_effort_override() is False


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {
            "version": 999,
            "effort": "high",
            "created_at": _NOW,
            "expires_at": None,
            "source": "test",
        },
        {
            "version": 1,
            "effort": "turbo",
            "created_at": _NOW,
            "expires_at": None,
            "source": "test",
        },
        {
            "version": 1,
            "effort": "high",
            "created_at": math.nan,
            "expires_at": None,
            "source": "test",
        },
    ],
)
def test_wire_rehydration_rejects_stale_or_malformed_payloads(payload) -> None:
    if payload is None:
        with pytest.raises(EffortOverrideStateError, match="not an object"):
            TemporaryEffortOverride.from_wire(payload)
    else:
        with pytest.raises(EffortOverrideStateError):
            TemporaryEffortOverride.from_wire(payload)


def test_facade_surfaces_binding_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def binding(_name: str):
        def fail(*_args):
            raise TimeoutError("state lock busy")

        return fail

    monkeypatch.setattr(effort_state, "require_rust_binding", binding)
    with pytest.raises(TimeoutError, match="state lock busy"):
        get_active_effort_override(_NOW)


def test_launch_resolution_precedence_and_non_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_config, "_get_default_effort", lambda: "low")
    monkeypatch.setattr(
        llm_config,
        "_get_temporary_default_effort",
        lambda now: _record("medium"),
    )
    assert llm_config.resolve_effective_effort(PromptDirectives()) == (
        "medium",
        False,
    )
    assert llm_config.resolve_effective_effort(PromptDirectives(), "high") == (
        "high",
        False,
    )
    assert llm_config.resolve_effective_effort(
        PromptDirectives(reasoning_effort="xhigh"), "high"
    ) == ("xhigh", True)


def test_expired_override_falls_back_to_configured_then_provider_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm_config,
        "_get_temporary_default_effort",
        lambda now: _record("medium", expires_at=now),
    )
    monkeypatch.setattr(llm_config, "_get_default_effort", lambda: "low")
    assert llm_config.resolve_effective_effort(PromptDirectives()) == (
        "low",
        False,
    )
    monkeypatch.setattr(llm_config, "_get_default_effort", lambda: None)
    assert llm_config.resolve_effective_effort(PromptDirectives()) == (
        None,
        False,
    )
