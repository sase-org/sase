"""An agent runner that starts during a code swap restarts fresh first."""

from __future__ import annotations

import sys

import pytest

from sase.axe import run_agent_runner


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
