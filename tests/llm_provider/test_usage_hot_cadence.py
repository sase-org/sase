"""Hot cadence: active refresh setting, admission passthrough, and hot hints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.llm_provider._provider_config_helpers import mock_provider_config


def _settings(monkeypatch: pytest.MonkeyPatch, cfg: dict[str, object]):
    from sase.llm_provider.usage.config import get_usage_metrics_settings

    mock_provider_config(monkeypatch, cfg)
    return get_usage_metrics_settings()


def test_active_refresh_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, {})
    assert settings.active_refresh_seconds == 120.0


@pytest.mark.parametrize(
    ("usage_metrics", "expected"),
    [
        pytest.param({"refresh_seconds": 300}, 120.0, id="default"),
        pytest.param(
            {"refresh_seconds": 300, "active_refresh_seconds": 90},
            90.0,
            id="explicit-below-idle",
        ),
        pytest.param(
            {"refresh_seconds": 300, "active_refresh_seconds": 600},
            300.0,
            id="capped-at-idle-cadence",
        ),
        pytest.param(
            {"refresh_seconds": 300, "active_refresh_seconds": 30},
            120.0,
            id="below-minimum-falls-back-to-default",
        ),
        pytest.param(
            {"refresh_seconds": 300, "active_refresh_seconds": "soon"},
            120.0,
            id="non-numeric-falls-back-to-default",
        ),
        pytest.param({"refresh_seconds": 60}, 60.0, id="default-capped-by-fast-idle"),
        pytest.param(
            {"refresh_seconds": 60, "active_refresh_seconds": 90},
            60.0,
            id="explicit-capped-by-fast-idle",
        ),
    ],
)
def test_active_refresh_parsing_and_clamping(
    monkeypatch: pytest.MonkeyPatch,
    usage_metrics: dict[str, object],
    expected: float,
) -> None:
    settings = _settings(monkeypatch, {"usage_metrics": usage_metrics})
    assert settings.active_refresh_seconds == expected


def test_admit_one_passes_active_cadence_and_warn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.llm_provider.usage import refresh as refresh_mod
    from sase.llm_provider.usage._refresh_submit import _admit_one

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    monkeypatch.setattr(refresh_mod, "usage_probe_floor", lambda _p: 120.0)
    monkeypatch.setattr(refresh_mod, "usage_cli_fingerprint", lambda _p: "fp-1")

    seen: dict[str, dict[str, Any]] = {}

    def fake_due(*args: object, **kwargs: object):
        seen["due"] = dict(kwargs)

        class _Due:
            due = True

        return _Due()

    def fake_admit(*args: object, **kwargs: object):
        seen["admit"] = dict(kwargs)

        class _Reservation:
            operation_id = "op-1"
            lease_id = "lease-1"

        class _Admitted:
            status = "reserved"
            reason = "never_observed"
            due_at = None
            reservation = _Reservation()

        return _Admitted()

    monkeypatch.setattr(refresh_mod, "evaluate_provider_usage_refresh_due", fake_due)
    monkeypatch.setattr(refresh_mod, "admit_provider_usage_refresh", fake_admit)
    monkeypatch.setattr(
        refresh_mod,
        "prepare_provider_usage_account_context",
        lambda provider, context_id, **_kw: type(
            "Ctx", (), {"context_id": context_id, "account_generation": 1}
        )(),
    )
    _admit_one(
        "codex", operation_id="op-1", explicit=False, cadence_seconds=300.0, now=None
    )
    assert seen["due"]["active_cadence_seconds"] == 120.0
    assert seen["due"]["warn_percent"] == 75.0
    assert seen["admit"]["active_cadence_seconds"] == 120.0
    assert seen["admit"]["warn_percent"] == 75.0

    _admit_one(
        "codex",
        operation_id="op-1",
        explicit=False,
        cadence_seconds=300.0,
        now=None,
        active_cadence_seconds=90.0,
        warn_percent=70.0,
    )
    assert seen["due"]["active_cadence_seconds"] == 90.0
    assert seen["due"]["warn_percent"] == 70.0
    assert seen["admit"]["active_cadence_seconds"] == 90.0
    assert seen["admit"]["warn_percent"] == 70.0


def test_mark_hot_facade_writes_and_coalesces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.llm_provider.usage.store import mark_provider_usage_hot

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    now = 1_800_000_000.0
    first = mark_provider_usage_hot("synth", now + 900.0, now=now)
    assert first is not None
    assert first.marked is True
    assert first.hot_until == pytest.approx(now + 900.0)
    second = mark_provider_usage_hot("synth", now + 900.0, now=now + 1.0)
    assert second is not None
    assert second.marked is False


def test_mark_hot_facade_swallows_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.llm_provider.usage import _facade as facade_mod

    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    def _boom(*args: object, **kwargs: object):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(facade_mod, "prepare_provider_usage_account_context", _boom)
    assert (
        facade_mod.mark_provider_usage_hot(
            "synth", 1_800_000_900.0, now=1_800_000_000.0
        )
        is None
    )
    assert facade_mod.mark_provider_usage_hot("", float("nan")) is None


def test_hot_hint_only_when_eligible_and_capable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.llm_provider.usage import refresh as refresh_mod
    from sase.llm_provider.usage import _refresh_triggers as triggers_mod

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    calls: list[dict[str, Any]] = []

    def fake_mark_hot(provider: str, until: float, **kwargs: object):
        calls.append({"provider": provider, "until": until, **kwargs})

    monkeypatch.setattr(refresh_mod, "mark_provider_usage_hot", fake_mark_hot)
    monkeypatch.setattr(triggers_mod, "_provider_has_probe_capability", lambda _p: True)

    now = 1_800_000_000.0
    assert refresh_mod.mark_provider_usage_hot_hint("synth", now=now) is None
    assert len(calls) == 1
    assert calls[0]["provider"] == "synth"
    assert calls[0]["until"] == pytest.approx(now + 900.0)

    mock_provider_config(
        monkeypatch, {"usage_metrics": {"providers": {"synth": {"enabled": False}}}}
    )
    refresh_mod.mark_provider_usage_hot_hint("synth", now=now)
    assert len(calls) == 1

    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    monkeypatch.setattr(
        triggers_mod, "_provider_has_probe_capability", lambda _p: False
    )
    refresh_mod.mark_provider_usage_hot_hint("synth", now=now)
    assert len(calls) == 1

    def _boom(provider: str, until: float, **kwargs: object):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(refresh_mod, "mark_provider_usage_hot", _boom)
    monkeypatch.setattr(triggers_mod, "_provider_has_probe_capability", lambda _p: True)
    assert refresh_mod.mark_provider_usage_hot_hint("synth", now=now) is None


def test_limit_event_writes_hot_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.llm_provider.usage import refresh as refresh_mod

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    monkeypatch.setattr(
        "sase.procs.submit_proc_request",
        lambda request: pytest.fail("limit event submitted a probe"),
    )
    calls: list[dict[str, Any]] = []

    def fake_mark_hot(provider: str, until: float, **kwargs: object):
        calls.append({"provider": provider, "until": until, **kwargs})

    monkeypatch.setattr(refresh_mod, "mark_provider_usage_hot", fake_mark_hot)
    now = 1_800_000_000.0
    assert refresh_mod.trigger_usage_refresh_after_limit_event("synth", now=now) is None
    assert len(calls) == 1
    assert calls[0]["until"] == pytest.approx(now + 900.0)


def test_launch_marks_provider_hot(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.llm_provider._invoke import invoke_agent
    from sase.llm_provider.launch_selection import LaunchSelection
    from sase.llm_provider.types import InvokeResult

    hinted: list[str] = []
    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.mark_provider_usage_hot_hint",
        lambda provider, **_kw: hinted.append(provider),
    )

    class _FakeProvider:
        def resolve_model_name(self, model_tier: str) -> str:
            return "synth-model"

        def invoke(self, query: str, **kwargs: object) -> InvokeResult:
            return InvokeResult(content="hi")

    monkeypatch.setattr(
        "sase.llm_provider._invoke.get_provider", lambda *a, **k: _FakeProvider()
    )
    monkeypatch.setattr(
        "sase.llm_provider._invoke.postprocess_success", lambda **_kw: None
    )
    result = invoke_agent(
        "hello",
        agent_type="test",
        suppress_output=True,
        skip_preprocessing=True,
        launch_selection=LaunchSelection(
            provider="synth",
            model="synth-model",
            reasoning_effort=None,
            effort_explicit=False,
        ),
    )
    assert result.content == "hi"
    assert hinted == ["synth"]


def _observation(
    provider: str, *, at: float, used_percent: float = 10.0, reset_at: float
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider": provider,
        "context_id": "default",
        "account_generation": 1,
        "ordering_token": at,
        "received_at": at,
        "source": "probe",
        "outcome": "ok",
        "reason_code": None,
        "diagnostic": None,
        "completeness": "complete",
        "authoritative_empty": False,
        "account_mode": "subscription",
        "plan": "synthetic",
        "windows": [
            {
                "key": "default",
                "label": "Synthetic default",
                "used_percent": used_percent,
                "resets_at": reset_at,
                "duration_seconds": None,
                "period_start": None,
                "applicability": {"kind": "account"},
                "observed_at": at,
                "source": "probe",
                "vendor_state": "allowed",
            }
        ],
    }


def test_hot_codex_due_early_while_hot_claude_waits_for_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.llm_provider.usage.store import (
        admit_provider_usage_refresh,
        evaluate_provider_usage_refresh_due,
        mark_provider_usage_hot,
        prepare_provider_usage_account_context,
        record_provider_usage_observation,
    )

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mock_provider_config(monkeypatch, {"usage_metrics": {"enabled": True}})
    now = 1_800_000_000.0
    codex = prepare_provider_usage_account_context("codex", "default", now=now)
    claude = prepare_provider_usage_account_context("claude", "default", now=now)
    codex_admitted = admit_provider_usage_refresh(
        "codex",
        codex.context_id,
        codex.account_generation,
        "op-hot-codex",
        75.0,
        cadence_seconds=300.0,
        explicit=False,
        adaptive=True,
        min_interval_seconds=120.0,
        active_cadence_seconds=120.0,
        warn_percent=75.0,
        now=now,
    )
    claude_admitted = admit_provider_usage_refresh(
        "claude",
        claude.context_id,
        claude.account_generation,
        "op-hot-claude",
        75.0,
        cadence_seconds=300.0,
        explicit=False,
        adaptive=True,
        min_interval_seconds=300.0,
        active_cadence_seconds=120.0,
        warn_percent=75.0,
        now=now,
    )
    assert codex_admitted.status == "reserved"
    assert claude_admitted.status == "reserved"
    for provider in ("codex", "claude"):
        record_provider_usage_observation(
            _observation(provider, at=now, reset_at=now + 3600.0), now=now
        )
    assert mark_provider_usage_hot("codex", now + 900.0, now=now) is not None
    assert mark_provider_usage_hot("claude", now + 900.0, now=now) is not None
    codex_due = evaluate_provider_usage_refresh_due(
        "codex",
        codex.context_id,
        codex.account_generation,
        cadence_seconds=300.0,
        explicit=False,
        adaptive=True,
        min_interval_seconds=120.0,
        active_cadence_seconds=120.0,
        warn_percent=75.0,
        now=now + 150.0,
    )
    assert codex_due.due is True
    claude_due = evaluate_provider_usage_refresh_due(
        "claude",
        claude.context_id,
        claude.account_generation,
        cadence_seconds=300.0,
        explicit=False,
        adaptive=True,
        min_interval_seconds=300.0,
        active_cadence_seconds=120.0,
        warn_percent=75.0,
        now=now + 150.0,
    )
    assert claude_due.due is False
    assert claude_due.reason == "floor"
