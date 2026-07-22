"""Temporary maximum-running-agents facade and effective-limit tests."""

from __future__ import annotations

import math

import pytest

import sase.config.runner_limit_override as runner_state
from sase.config.runner_limit_override import (
    EffectiveRunnerLimitSnapshot,
    RunnerLimitOverrideStateError,
    TemporaryRunnerLimitOverride,
    clear_runner_limit_override,
    get_active_runner_limit_override,
    set_runner_limit_override,
    set_runner_limit_override_until,
)

_NOW = 1_800_000_000.0


def _record(
    limit: int = 4, *, expires_at: float | None = _NOW + 900.0
) -> TemporaryRunnerLimitOverride:
    return TemporaryRunnerLimitOverride(
        version=1,
        limit=limit,
        created_at=_NOW,
        expires_at=expires_at,
        source="test",
    )


def test_facade_round_trips_positive_limits_and_honors_sase_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    for limit in (1, 10, 128):
        written = set_runner_limit_override(limit, 900.0, source="test", now=_NOW)
        assert written.limit == limit
        assert written.expires_at == _NOW + 900.0
        assert get_active_runner_limit_override(_NOW) == written
    assert (tmp_path / "max_running_agents_override.json").is_file()


def test_facade_exact_expiry_replacement_and_idempotent_clear(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    first = set_runner_limit_override(4, None, source="test", now=_NOW)
    assert first.limit == 4
    replacement = set_runner_limit_override_until(
        8, _NOW + 5.0, source="test", now=_NOW
    )
    assert get_active_runner_limit_override(_NOW + 4.999) == replacement
    assert get_active_runner_limit_override(_NOW + 5.0) is None
    assert clear_runner_limit_override() is False
    set_runner_limit_override(1, None, source="test", now=_NOW)
    assert clear_runner_limit_override() is True
    assert clear_runner_limit_override() is False


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "4"])
def test_facade_rejects_non_positive_or_non_integer_limits(limit: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        set_runner_limit_override(limit, None, source="test", now=_NOW)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {
            "version": 999,
            "limit": 4,
            "created_at": _NOW,
            "expires_at": None,
            "source": "test",
        },
        {
            "version": 1,
            "limit": True,
            "created_at": _NOW,
            "expires_at": None,
            "source": "test",
        },
        {
            "version": 1,
            "limit": 4,
            "created_at": 0.0,
            "expires_at": None,
            "source": "test",
        },
        {
            "version": 1,
            "limit": 4,
            "created_at": math.nan,
            "expires_at": None,
            "source": "test",
        },
        {
            "version": 1,
            "limit": 4,
            "created_at": _NOW,
            "expires_at": _NOW,
            "source": "test",
        },
    ],
)
def test_wire_rehydration_rejects_stale_or_malformed_payloads(payload) -> None:
    with pytest.raises(RunnerLimitOverrideStateError):
        TemporaryRunnerLimitOverride.from_wire(payload)


def test_snapshot_prefers_active_override_and_locally_expires() -> None:
    snapshot = EffectiveRunnerLimitSnapshot(
        configured_limit=10,
        temporary_override=_record(4, expires_at=_NOW + 5.0),
        captured_at=_NOW,
    )
    assert snapshot.effective_limit(_NOW + 4.999) == 4
    assert snapshot.effective_limit(_NOW + 5.0) == 10
    assert snapshot.active_override(_NOW + 5.0) is None


def test_facade_surfaces_binding_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def binding(_name: str):
        def fail(*_args):
            raise TimeoutError("state lock busy")

        return fail

    monkeypatch.setattr(runner_state, "require_rust_binding", binding)
    with pytest.raises(TimeoutError, match="state lock busy"):
        get_active_runner_limit_override(_NOW)


def test_effective_accessor_prefers_override_and_propagates_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(config_core, "get_configured_max_running_agents", lambda: 10)
    monkeypatch.setattr(
        runner_state,
        "get_active_runner_limit_override",
        lambda now=None: _record(3),
    )
    assert config_core.get_max_running_agents(_NOW) == 3

    def fail(now=None):
        raise TimeoutError("busy")

    monkeypatch.setattr(runner_state, "get_active_runner_limit_override", fail)
    with pytest.raises(TimeoutError, match="busy"):
        config_core.get_max_running_agents(_NOW)
