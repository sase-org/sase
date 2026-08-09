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
