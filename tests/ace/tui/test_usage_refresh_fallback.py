"""Scheduler-ownership gate for the ACE usage-refresh fallback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.actions import _usage_refresh_fallback as fallback


def _config(*chops: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(lumberjacks={"usage": SimpleNamespace(chops=list(chops))})


def _chop(
    *, name: str = "usage_refresh", script: str | None = None, enabled: bool = True
) -> SimpleNamespace:
    return SimpleNamespace(name=name, script=script or name, enabled=enabled)


def test_fallback_gate_quiet_without_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.axe.process.is_axe_running", lambda: False)
    monkeypatch.setattr(
        "sase.axe.config.load_axe_config",
        lambda: pytest.fail("config must not load when axe is down"),
    )
    assert fallback._scheduler_owns_usage_collection() is False


def test_fallback_gate_quiet_when_job_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.axe.process.is_axe_running", lambda: True)
    monkeypatch.setattr(
        "sase.axe.config.load_axe_config",
        lambda: _config(_chop(name="other", script="sase_job_other")),
    )
    assert fallback._scheduler_owns_usage_collection() is False


def test_fallback_gate_quiet_when_job_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.axe.process.is_axe_running", lambda: True)
    monkeypatch.setattr(
        "sase.axe.config.load_axe_config",
        lambda: _config(
            _chop(name="usage_refresh", script="sase_job_usage_refresh", enabled=False)
        ),
    )
    assert fallback._scheduler_owns_usage_collection() is False


def test_fallback_gate_owned_by_enabled_usage_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.axe.process.is_axe_running", lambda: True)
    monkeypatch.setattr(
        "sase.axe.config.load_axe_config",
        lambda: _config(
            _chop(name="usage_refresh", script="sase_job_usage_refresh", enabled=True)
        ),
    )
    assert fallback._scheduler_owns_usage_collection() is True


def test_fallback_skips_submission_when_scheduler_owns_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fallback, "_scheduler_owns_usage_collection", lambda: True)
    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.request_due_usage_refresh",
        lambda **kwargs: pytest.fail("owned collection must not submit"),
    )
    fallback._maybe_request_due_refresh()


def test_fallback_submits_due_work_when_scheduler_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fallback, "_scheduler_owns_usage_collection", lambda: False)
    calls: dict[str, object] = {}

    def fake_request(**kwargs: object) -> object:
        calls.update(kwargs)
        return None

    monkeypatch.setattr(
        "sase.llm_provider.usage.refresh.request_due_usage_refresh", fake_request
    )
    fallback._maybe_request_due_refresh()
    assert calls == {"origin": "ace"}
