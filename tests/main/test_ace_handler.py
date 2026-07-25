"""Tests for the ``sase ace`` command handler."""

import argparse
import asyncio
from datetime import datetime
import logging
from pathlib import Path
import threading
import time
from unittest.mock import patch

import pytest

from sase.main import ace_handler
from sase.ace.tui import AceExitAction
from sase.main.parser_ace import register_ace_parser


class _FakeProfiler:
    def output_text(self, *, unicode: bool, color: bool, show_all: bool) -> str:
        assert unicode is True
        assert color is False
        assert show_all is True
        return "profile text"


def test_run_ace_app_does_not_join_default_executor_worker() -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def block() -> None:
        started.set()
        release.wait(timeout=5.0)
        finished.set()

    class _App:
        async def run_async(self) -> None:
            asyncio.get_running_loop().run_in_executor(None, block)
            while not started.is_set():
                await asyncio.sleep(0)

    start = time.monotonic()
    ace_handler._run_ace_app(_App())
    elapsed = time.monotonic() - start

    try:
        assert elapsed < 0.5
    finally:
        release.set()
        assert finished.wait(timeout=1.0)


def test_hard_exit_flushes_before_bypassing_interpreter_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase import telemetry

    calls: list[str] = []

    class _Stream:
        def __init__(self, name: str) -> None:
            self.name = name

        def flush(self) -> None:
            calls.append(self.name)

    monkeypatch.setattr(
        ace_handler,
        "_log_live_exit_threads",
        lambda: calls.append("threads"),
    )
    monkeypatch.setattr(telemetry, "flush_metrics", lambda: calls.append("telemetry"))
    monkeypatch.setattr(ace_handler.sys, "stdout", _Stream("stdout"))
    monkeypatch.setattr(ace_handler.sys, "stderr", _Stream("stderr"))
    monkeypatch.setattr(
        ace_handler.os,
        "_exit",
        lambda code: calls.append(f"exit:{code}"),
    )

    ace_handler._hard_exit_ace(7)

    assert calls == ["threads", "telemetry", "stdout", "stderr", "exit:7"]


def test_live_exit_thread_warning_names_known_non_daemon_workers(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    threads = [
        threading.Thread(name="asyncio_3", daemon=False),
        threading.Thread(name="sase-loader_1", daemon=False),
        threading.Thread(name="asyncio-daemon", daemon=True),
        threading.Thread(name="unrelated", daemon=False),
    ]
    monkeypatch.setattr(ace_handler.threading, "enumerate", lambda: threads)

    with caplog.at_level(logging.WARNING, logger=ace_handler.__name__):
        ace_handler._log_live_exit_threads()

    assert len(caplog.records) == 1
    assert "asyncio_3, sase-loader_1" in caplog.text


def test_write_profile_output_shortens_home_and_copies_path(
    tmp_path: Path,
    capsys,
) -> None:
    home = tmp_path / "home"
    tmpdir = home / "tmp" / "sase"
    tmpdir.mkdir(parents=True)

    def fake_managed_tmpdir(*parts: str) -> str:
        managed = tmpdir.joinpath(*parts)
        managed.mkdir(parents=True, exist_ok=True)
        return str(managed)

    with (
        patch(
            "sase.main.ace_handler.local_now",
            return_value=datetime(2026, 5, 13, 12, 9, 57),
        ),
        patch(
            "sase.main.ace_handler.get_sase_managed_tmpdir",
            side_effect=fake_managed_tmpdir,
        ),
        patch("sase.core.paths.Path.home", return_value=home),
        patch(
            "sase.main.ace_handler.copy_to_system_clipboard", return_value=True
        ) as copy_to_clipboard,
    ):
        output_path = ace_handler._write_profile_output(_FakeProfiler(), "")

    expected_path = tmpdir / "ace-profiles" / "ace_profile_20260513_120957.txt"
    assert output_path == str(expected_path)
    assert expected_path.read_text() == "profile text"
    copy_to_clipboard.assert_called_once_with(
        "~/tmp/sase/ace-profiles/ace_profile_20260513_120957.txt"
    )
    assert (
        capsys.readouterr().err
        == "Profile written to: ~/tmp/sase/ace-profiles/ace_profile_20260513_120957.txt\n"
        "Profile path copied to clipboard.\n"
    )


def test_profile_output_path_expands_explicit_tilde_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    with patch.dict("os.environ", {"HOME": str(home)}):
        output_path = ace_handler._profile_output_path("~/profile.txt")

    assert output_path == str(home / "profile.txt")
    assert (home / "profile.txt").parent.exists()


def _parse_ace_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="subcommand")
    register_ace_parser(subparsers)
    return parser.parse_args(["ace", *argv])


def test_tab_option_defaults_to_agents() -> None:
    args = _parse_ace_args([])
    assert args.tab == "agents"


@pytest.mark.parametrize("tab", ["artifacts", "changespecs", "agents", "axe"])
def test_tab_option_accepts_valid_choices(tab: str) -> None:
    args = _parse_ace_args(["--tab", tab])
    assert args.tab == tab


def test_tab_option_short_flag() -> None:
    args = _parse_ace_args(["-t", "changespecs"])
    assert args.tab == "changespecs"


def test_tab_option_rejects_invalid_choice() -> None:
    with pytest.raises(SystemExit):
        _parse_ace_args(["--tab", "bogus"])


def test_build_ace_restart_argv_strips_restart_and_tmux_flags() -> None:
    argv = [
        "ace",
        "--tab",
        "axe",
        "--restart-axe",
        "-R",
        "--tmux",
        "-T",
        '"Ready"',
    ]

    assert ace_handler._build_ace_restart_argv(
        restart_axe=False,
        argv=argv,
    ) == ["ace", "--tab", "axe", '"Ready"']
    assert ace_handler._build_ace_restart_argv(
        restart_axe=True,
        argv=argv,
    ) == ["ace", "--tab", "axe", '"Ready"', "--restart-axe"]


def test_build_ace_restart_argv_preserves_separator_query_flags() -> None:
    argv = ["ace", "--restart-axe", "--", "--restart-axe"]

    assert ace_handler._build_ace_restart_argv(
        restart_axe=True,
        argv=argv,
    ) == ["ace", "--restart-axe", "--", "--restart-axe"]


def test_build_ace_restart_argv_prepends_ace_subcommand_when_missing() -> None:
    assert ace_handler._build_ace_restart_argv(
        restart_axe=False,
        argv=["--tab", "agents"],
    ) == ["ace", "--tab", "agents"]


def test_exec_ace_restart_if_requested_quit_does_not_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_exec(*_args: object) -> None:
        raise AssertionError("QUIT must not exec")

    monkeypatch.setattr(ace_handler.os, "execv", fail_exec)

    ace_handler._exec_ace_restart_if_requested(AceExitAction.QUIT)


def test_exec_ace_restart_if_requested_execs_current_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_exec(executable: str, args: list[str]) -> None:
        calls.append((executable, args))

    monkeypatch.setattr(ace_handler.sys, "argv", ["sase", "ace", "-R", "-T"])
    monkeypatch.setattr(ace_handler.sys, "executable", "/venv/bin/python")
    monkeypatch.setattr(ace_handler.os, "execv", fake_exec)

    ace_handler._exec_ace_restart_if_requested(AceExitAction.RESTART_TUI_AND_AXE)

    assert calls == [
        (
            "/venv/bin/python",
            [
                "/venv/bin/python",
                "-m",
                "sase",
                "ace",
                "--restart-axe",
            ],
        )
    ]


def test_exec_ace_restart_if_requested_exits_on_exec_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_exec(_executable: str, _args: list[str]) -> None:
        raise OSError("boom")

    monkeypatch.setattr(ace_handler.os, "execv", fail_exec)

    with pytest.raises(SystemExit) as exc_info:
        ace_handler._exec_ace_restart_if_requested(AceExitAction.RESTART_TUI)

    assert exc_info.value.code == 1
    assert "sase ace restart failed: boom" in capsys.readouterr().err
