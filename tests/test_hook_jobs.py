"""Tests for HookJobRunner mentor check orchestration."""

from typing import Any

import pytest

from sase.axe.hook_jobs import HookJobRunner
from sase.axe.state import AxeMetrics
from test_utils import build_patch, make_mentor_config


def test_run_mentor_checks_reuses_loaded_profiles(monkeypatch: Any) -> None:
    """Hook runner should load mentor profiles once per mentor-check pass."""
    cs_one = build_patch(name="one")
    cs_two = build_patch(name="two")
    profile = [make_mentor_config()]
    profile_loads = 0
    check_calls = 0

    def _get_profiles() -> list[Any]:
        nonlocal profile_loads
        profile_loads += 1
        return profile

    def _check_mentors(
        _patch: Any,
        _log: Any,
        _zombie_timeout: int,
        _max_runners: int,
        _started: int,
        mentor_profiles: list[Any] | None = None,
        verbose_diagnostics: bool = False,
    ) -> tuple[list[str], int]:
        nonlocal check_calls
        check_calls += 1
        assert mentor_profiles is profile
        assert verbose_diagnostics is False
        return ([], 0)

    monkeypatch.setattr("sase.axe.hook_jobs.get_all_mentor_profiles", _get_profiles)
    monkeypatch.setattr("sase.axe.hook_jobs.check_mentors", _check_mentors)

    runner = HookJobRunner(
        metrics=AxeMetrics(),
        zombie_timeout_seconds=30,
        max_hook_runners=10,
        max_agent_runners=10,
        log_callback=lambda _msg, _style=None: None,
    )
    runner.run_mentor_checks([cs_one, cs_two])

    assert profile_loads == 1
    assert check_calls == 2


def test_run_hook_checks_emits_noop_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    cs = build_patch(name="one", hooks=[object()])
    logs: list[str] = []

    monkeypatch.setattr(
        "sase.axe.hook_jobs.check_hooks",
        lambda *_args, **_kwargs: ([], 0),
    )

    runner = HookJobRunner(
        metrics=AxeMetrics(),
        zombie_timeout_seconds=30,
        max_hook_runners=10,
        max_agent_runners=10,
        log_callback=lambda msg, _style=None: logs.append(msg),
    )
    runner.run_hook_checks([cs])

    assert logs[-1] == (
        "hook_checks: patches=1 hooks=1 updates=0 started=0 "
        "reason=no_updates_or_launches"
    )


def test_run_mentor_checks_emits_action_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cs = build_patch(name="one", mentors=[object()])
    logs: list[str] = []

    monkeypatch.setattr("sase.axe.hook_jobs.get_all_mentor_profiles", lambda: [])
    monkeypatch.setattr(
        "sase.axe.hook_jobs.check_mentors",
        lambda *_args, **_kwargs: (["Started mentor"], 1),
    )

    runner = HookJobRunner(
        metrics=AxeMetrics(),
        zombie_timeout_seconds=30,
        max_hook_runners=10,
        max_agent_runners=10,
        log_callback=lambda msg, _style=None: logs.append(msg),
    )
    runner.run_mentor_checks([cs])

    assert "* one: Started mentor" in logs
    assert logs[-1] == (
        "mentor_checks: patches=1 mentors=1 profiles=0 updates=1 started=1"
    )


def test_run_stale_running_cleanup_reconciles_before_releasing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A healthy sweep reconciles monitors, then releases claims normally."""
    calls: list[str] = []

    def _reconcile_dead_supervisors() -> list[object]:
        calls.append("reconcile")
        return [object()]

    def _cleanup(_log: Any, *, skip_monitor_claims: bool = False) -> int:
        calls.append("cleanup")
        assert skip_monitor_claims is False
        return 2

    monkeypatch.setattr(
        "sase.monitor.reconcile_dead_supervisors", _reconcile_dead_supervisors
    )
    monkeypatch.setattr("sase.axe.hook_jobs.cleanup_stale_running_entries", _cleanup)

    runner = HookJobRunner(
        metrics=AxeMetrics(),
        zombie_timeout_seconds=30,
        max_hook_runners=10,
        max_agent_runners=10,
        log_callback=lambda _msg, _style=None: None,
    )
    runner.run_stale_running_cleanup()

    assert calls == ["reconcile", "cleanup"]
    assert runner.metrics.stale_running_cleaned == 2


def test_run_stale_running_cleanup_blocks_monitor_release_on_reconcile_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reconciliation failure leaves ace-monitor claims untouched this sweep."""
    logs: list[str] = []
    seen_skip_monitor_claims: list[bool] = []

    def _reconcile_dead_supervisors() -> list[object]:
        raise RuntimeError("boom")

    def _cleanup(_log: Any, *, skip_monitor_claims: bool = False) -> int:
        seen_skip_monitor_claims.append(skip_monitor_claims)
        return 0

    monkeypatch.setattr(
        "sase.monitor.reconcile_dead_supervisors", _reconcile_dead_supervisors
    )
    monkeypatch.setattr("sase.axe.hook_jobs.cleanup_stale_running_entries", _cleanup)

    runner = HookJobRunner(
        metrics=AxeMetrics(),
        zombie_timeout_seconds=30,
        max_hook_runners=10,
        max_agent_runners=10,
        log_callback=lambda msg, _style=None: logs.append(msg),
    )
    runner.run_stale_running_cleanup()

    assert seen_skip_monitor_claims == [True]
    assert any("reconciliation failed" in msg for msg in logs)
