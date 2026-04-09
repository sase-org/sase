"""Tests for HookJobRunner mentor check orchestration."""

from typing import Any

from sase.axe.hook_jobs import HookJobRunner
from sase.axe.state import AxeMetrics
from test_utils import build_changespec, make_mentor_config


def test_run_mentor_checks_reuses_loaded_profiles(monkeypatch: Any) -> None:
    """Hook runner should load mentor profiles once per mentor-check pass."""
    cs_one = build_changespec(name="one")
    cs_two = build_changespec(name="two")
    profile = [make_mentor_config()]
    profile_loads = 0
    check_calls = 0

    def _get_profiles() -> list[Any]:
        nonlocal profile_loads
        profile_loads += 1
        return profile

    def _check_mentors(
        _changespec: Any,
        _log: Any,
        _zombie_timeout: int,
        _max_runners: int,
        _started: int,
        mentor_profiles: list[Any] | None = None,
    ) -> tuple[list[str], int]:
        nonlocal check_calls
        check_calls += 1
        assert mentor_profiles is profile
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
