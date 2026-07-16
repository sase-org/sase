"""Tests for the ``sase ace`` command handler."""

import argparse
from datetime import datetime
from pathlib import Path
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


def test_write_profile_output_shortens_home_and_copies_path(
    tmp_path: Path,
    capsys,
) -> None:
    home = tmp_path / "home"
    tmpdir = home / "tmp" / "sase"
    tmpdir.mkdir(parents=True)

    with (
        patch(
            "sase.main.ace_handler.local_now",
            return_value=datetime(2026, 5, 13, 12, 9, 57),
        ),
        patch("sase.main.ace_handler.get_sase_tmpdir", return_value=str(tmpdir)),
        patch("sase.core.paths.Path.home", return_value=home),
        patch(
            "sase.main.ace_handler.copy_to_system_clipboard", return_value=True
        ) as copy_to_clipboard,
    ):
        output_path = ace_handler._write_profile_output(_FakeProfiler(), "")

    expected_path = tmpdir / "ace_profile_20260513_120957.txt"
    assert output_path == str(expected_path)
    assert expected_path.read_text() == "profile text"
    copy_to_clipboard.assert_called_once_with(
        "~/tmp/sase/ace_profile_20260513_120957.txt"
    )
    assert (
        capsys.readouterr().err
        == "Profile written to: ~/tmp/sase/ace_profile_20260513_120957.txt\n"
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
