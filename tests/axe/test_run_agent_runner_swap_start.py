"""An agent runner that starts during a code swap restarts fresh first."""

from __future__ import annotations

import sys
from io import StringIO
import signal

import pytest

from sase.axe import run_agent_runner
from sase.core.index_lookup_patience import LookupPatience, LookupRetryEvent


class _Stop(Exception):
    """Stands in for the re-exec, which never returns."""


def test_runner_start_arms_the_retry_and_defers_with_its_own_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        run_agent_runner, "arm_code_swap_retry", lambda: calls.append("arm")
    )
    monkeypatch.setattr(
        run_agent_runner,
        "defer_launch_for_code_swap",
        lambda argv: calls.append(list(argv)),
    )
    monkeypatch.setattr(sys, "argv", ["/src/sase/axe/run_agent_runner.py", "--x"])

    run_agent_runner._defer_start_across_code_swap()

    assert calls == [
        "arm",
        [sys.executable, "/src/sase/axe/run_agent_runner.py", "--x"],
    ]


def test_runner_main_defers_before_it_touches_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stop() -> None:
        raise _Stop

    monkeypatch.setattr(run_agent_runner, "_defer_start_across_code_swap", stop)
    monkeypatch.setattr(
        run_agent_runner,
        "install_sigterm_handler",
        lambda *_args, **_kwargs: pytest.fail("ran before the swap deferral"),
    )

    with pytest.raises(_Stop):
        run_agent_runner.main()


def test_runner_installs_sixty_second_lookup_patience_before_building_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[LookupPatience | None] = []

    def stop_before_state(_argv: list[str]) -> object:
        raise _Stop

    monkeypatch.setattr(run_agent_runner, "_defer_start_across_code_swap", lambda: None)
    monkeypatch.setattr(
        run_agent_runner, "install_sigterm_handler", lambda *_a, **_k: None
    )
    monkeypatch.setattr(signal, "pthread_sigmask", lambda *_a, **_k: None)
    monkeypatch.setattr(run_agent_runner, "_stamp_host_path_snapshot", lambda: None)
    monkeypatch.setattr(
        run_agent_runner, "set_process_lookup_patience", installed.append
    )
    monkeypatch.setattr(run_agent_runner, "_build_run_state", stop_before_state)
    monkeypatch.setattr(
        "sase.feature_flags.install_process_feature_flags", lambda: None
    )

    with pytest.raises(_Stop):
        run_agent_runner.main()

    assert len(installed) == 1
    policy = installed[0]
    assert policy is not None
    assert policy.budget_seconds == 60
    assert policy.on_retry is not None


def test_runner_retry_logger_has_stable_rate_limited_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()
    monkeypatch.setattr(run_agent_runner.sys, "stderr", output)
    log = run_agent_runner._runner_lookup_retry_logger()

    log(LookupRetryEvent("agent artifact index", 1, 0, 0.25, "database\nis locked"))
    log(LookupRetryEvent("agent artifact index", 2, 9.9, 0.5, "database is locked"))
    log(LookupRetryEvent("agent artifact index", 3, 10, 1, "database is locked"))
    log(LookupRetryEvent("agent artifact index", 4, 10.25, 0, None, recovered=True))

    assert output.getvalue().splitlines() == [
        "Lookup agent artifact index busy; attempt 1, waited 0.0s, retrying in 0.25s (database is locked)",
        "Lookup agent artifact index busy; attempt 3, waited 10.0s, retrying in 1.00s (database is locked)",
        "Lookup agent artifact index recovered after 10.2s",
    ]
