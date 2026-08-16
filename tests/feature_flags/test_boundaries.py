"""Feature-flag boundary install tests."""

from __future__ import annotations

import argparse

import pytest

from sase.axe import run_agent_runner
from sase.main import ace_handler, axe_handler


def test_handle_ace_installs_after_disabling_local_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []

    monkeypatch.setattr(
        "sase.config.core.set_include_local_config",
        lambda value: events.append(("set_include_local_config", value)),
    )
    monkeypatch.setattr(
        "sase.feature_flags.install_process_feature_flags",
        lambda: events.append(("install_process_feature_flags", None)),
    )
    monkeypatch.setattr(
        "sase.ace.tui.log_setup.install_tui_file_logging",
        lambda: events.append(("install_tui_file_logging", None)),
    )

    class FakeAceApp:
        exit_action = None

        def __init__(self, **kwargs: object) -> None:
            events.append(("AceApp", kwargs))

    monkeypatch.setattr("sase.ace.tui.AceApp", FakeAceApp)

    def stop_after_construction(app: object) -> None:
        events.append(("_run_ace_app", app))
        raise SystemExit(0)

    monkeypatch.setattr(ace_handler, "_run_ace_app", stop_after_construction)

    with pytest.raises(SystemExit):
        ace_handler.handle_ace_command(
            argparse.Namespace(
                tmux=False,
                profile=None,
                model_tier=None,
                model_size=None,
                tab="agents",
                query=None,
                refresh_interval=1.0,
                no_axe=True,
                restart_axe=False,
                vcs_provider=None,
            )
        )

    assert events[:4] == [
        ("set_include_local_config", False),
        ("install_process_feature_flags", None),
        ("install_tui_file_logging", None),
        ("AceApp", events[3][1]),
    ]


def test_handle_axe_installs_before_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        "sase.feature_flags.install_process_feature_flags",
        lambda: events.append("install"),
    )

    with pytest.raises(SystemExit):
        axe_handler.handle_axe_command(
            argparse.Namespace(axe_subcommand=None, vcs_provider=None)
        )

    assert events == ["install"]


def test_run_agent_runner_installs_before_building_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        "sase.feature_flags.install_process_feature_flags",
        lambda: events.append("install"),
    )

    def fail_after_order_is_observed(argv: list[str]) -> object:
        events.append("build_state")
        raise RuntimeError("stop")

    monkeypatch.setattr(
        run_agent_runner,
        "_build_run_state",
        fail_after_order_is_observed,
    )

    with pytest.raises(RuntimeError):
        run_agent_runner.main()

    assert events == ["install", "build_state"]
