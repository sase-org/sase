"""Tests for ``sase tui --tmux`` window launching."""

from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid
from typing import Any
from unittest.mock import patch

import pytest

from sase.main import ace_tmux


def _completed(
    cmd: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


class _FakeTmux:
    """Stand-in for ``subprocess.run`` that records calls and scripts tmux."""

    def __init__(
        self,
        *,
        in_tmux: bool,
        session_name: str = "agent-session-7",
        existing_windows: tuple[str, ...] = (),
        pane_pid_base: int = 82316,
    ) -> None:
        self.in_tmux = in_tmux
        self.session_name = session_name
        self.windows = [
            {
                "id": f"@{index}",
                "name": name,
                "metadata": {},
                "pane_pid": pane_pid_base + index,
            }
            for index, name in enumerate(existing_windows, start=1)
        ]
        self.pane_pid_base = pane_pid_base
        self.calls: list[list[str]] = []

    def __call__(
        self, cmd: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        assert cmd[0] == "tmux"

        sub = cmd[1]
        if sub == "display-message":
            return _completed(cmd, stdout=self.session_name + "\n")
        if sub == "has-session":
            return _completed(cmd, returncode=0 if not self.in_tmux else 1)
        if sub == "list-windows":
            return _completed(
                cmd,
                stdout="\n".join(str(window["name"]) for window in self.windows) + "\n",
            )
        if sub == "new-session":
            return _completed(cmd)
        if sub == "set-option":
            if "-w" not in cmd:
                return _completed(cmd)
            target = cmd[cmd.index("-t") + 1]
            window = self._window_by_target(target)
            option = cmd[-2]
            value = cmd[-1]
            window["metadata"][option] = value
            return _completed(cmd)
        if sub == "rename-window":
            target = cmd[cmd.index("-t") + 1]
            window = self._window_by_target(target)
            window["name"] = cmd[-1]
            return _completed(cmd)
        if sub == "kill-window":
            target = cmd[cmd.index("-t") + 1]
            window = self._window_by_target(target)
            self.windows.remove(window)
            return _completed(cmd)
        if sub == "new-window":
            assert "-n" in cmd
            window_name = cmd[cmd.index("-n") + 1]
            session = self.session_name if self.in_tmux else ace_tmux._AGENTS_SESSION
            n = len(self.windows) + 1
            window_id = f"@{n}"
            pane_pid = self.pane_pid_base + n
            self.windows.append(
                {
                    "id": window_id,
                    "name": window_name,
                    "metadata": {},
                    "pane_pid": pane_pid,
                }
            )
            return _completed(
                cmd, stdout=f"{session}\t{window_id}\t{window_name}\t{pane_pid}\n"
            )
        raise AssertionError(f"unexpected tmux subcommand: {cmd}")

    def _window_by_target(self, target: str) -> dict[str, Any]:
        if target.startswith("@"):
            for window in self.windows:
                if window["id"] == target:
                    return window
        if ":" in target:
            _session, _, name = target.partition(":")
            for window in self.windows:
                if window["name"] == name:
                    return window
        raise AssertionError(f"unknown tmux target: {target}")


def _args() -> argparse.Namespace:
    return argparse.Namespace(tmux=True)


class _SocketTmuxRunner:
    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path
        self.calls: list[list[str]] = []

    def run(
        self,
        cmd: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        assert cmd[0] == "tmux"
        return subprocess.run(
            ["tmux", "-S", str(self.socket_path), *cmd[1:]],
            **kwargs,
        )


@pytest.fixture(autouse=True)
def _sandbox_screenshot_request_dirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        ace_tmux,
        "screenshot_request_dir",
        lambda session, window_name: tmp_path / session / window_name,
    )


def test_returns_sase_tmux_1_on_fresh_session(capsys, monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui", "my-query"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    out = capsys.readouterr().out
    assert "sase_tmux_window=sase_tmux_1" in out
    assert "sase_tmux_session=agent-session-7" in out
    assert "sase_tmux_target=@1" in out
    assert "sase_tmux_window_id=@1" in out
    assert "sase_screenshot_dir=" in out
    # The PID reported must be the fake pane pid (first window → base + 1),
    # not the parent process's PID. This locks in that we surface the child.
    assert f"sase_tmux_pid={fake.pane_pid_base + 1}" in out


def test_skips_occupied_window_numbers(capsys, monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True, existing_windows=("sase_tmux_1",))
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    out = capsys.readouterr().out
    assert "sase_tmux_window=sase_tmux_2" in out
    new_window_calls = [c for c in fake.calls if c[1] == "new-window"]
    assert len(new_window_calls) == 1
    assert (new_window_calls[0][new_window_calls[0].index("-n") + 1]).startswith(
        "sase_tmux_2_"
    )


def test_claim_window_uses_local_claim_when_tmux_allows_duplicate_names(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True)

    first = ace_tmux._claim_window("agent-session-7", "sleep 60", runner=fake)
    second = ace_tmux._claim_window("agent-session-7", "sleep 60", runner=fake)

    assert first.window_name == "sase_tmux_1"
    assert second.window_name == "sase_tmux_2"
    assert first.target == "@1"
    assert second.target == "@2"
    assert first.screenshot_dir != second.screenshot_dir


def test_create_agent_tmux_window_uses_real_window_ids_on_isolated_socket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")
    monkeypatch.setattr(
        ace_tmux,
        "screenshot_request_dir",
        lambda session, window_name: tmp_path / "requests" / session / window_name,
    )
    socket_path = Path("/tmp") / f"sase-test-tmux-{uuid.uuid4().hex}.sock"
    runner = _SocketTmuxRunner(socket_path)
    first: Any = None
    second: Any = None
    try:
        first = ace_tmux.create_agent_tmux_window(
            "sleep 60",
            cols=40,
            rows=10,
            runner=runner.run,
            timeout=5,
        )
        second = ace_tmux.create_agent_tmux_window(
            "sleep 60",
            cols=40,
            rows=10,
            runner=runner.run,
            timeout=5,
        )

        assert first.window_name == "sase_tmux_1"
        assert second.window_name == "sase_tmux_2"
        assert first.target.startswith("@")
        assert second.target.startswith("@")
        assert first.target != second.target
        assert first.screenshot_dir != second.screenshot_dir

        first_dir = runner.run(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                first.target,
                "#{@sase_screenshot_dir}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        second_dir = runner.run(
            [
                "tmux",
                "display-message",
                "-p",
                "-t",
                second.target,
                "#{@sase_screenshot_dir}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert first_dir.stdout.strip() == first.screenshot_dir
        assert second_dir.stdout.strip() == second.screenshot_dir
    finally:
        for window in (first, second):
            if window is not None:
                ace_tmux.release_tmux_window_claim(window.screenshot_dir)
        runner.run(
            ["tmux", "kill-server"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass


def test_claim_window_cleans_real_window_after_post_create_timeout(
    tmp_path: Path,
) -> None:
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")

    class _PostCreateTimeoutRunner(_SocketTmuxRunner):
        def run(
            self,
            cmd: list[str],
            **kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            if cmd[:2] == ["tmux", "new-window"]:
                super().run(cmd, **kwargs)
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
            return super().run(cmd, **kwargs)

    socket_path = Path("/tmp") / f"sase-test-tmux-{uuid.uuid4().hex}.sock"
    runner = _PostCreateTimeoutRunner(socket_path)
    session = "sase-test-post-create"
    try:
        runner.run(
            ["tmux", "new-session", "-d", "-s", session, "-n", "placeholder"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

        with pytest.raises(ace_tmux.TmuxLaunchError) as excinfo:
            ace_tmux._claim_window(
                session,
                "sleep 60",
                runner=runner.run,
                timeout=5,
            )

        assert "timed out while trying to create tmux window 'sase_tmux_1'" in str(
            excinfo.value
        )
        windows = runner.run(
            ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert "sase_tmux_1_" not in windows.stdout
        claim = tmp_path / session / "sase_tmux_1" / ace_tmux._WINDOW_CLAIM_FILE
        assert not claim.exists()
    finally:
        runner.run(
            ["tmux", "kill-server"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass


def test_strips_tmux_flags_from_relaunch_argv(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True)
    argv = [
        "sase",
        "tui",
        "--tmux",
        "-T",
        "my-query",
        "--tab",
        "agents",
        "--profile",
    ]
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", argv),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    # The relaunch is now a single shell command string at the end of argv,
    # prefixed with 'exec ' so tmux's #{pane_pid} reports the Python PID.
    relaunch_cmd = new_window_call[-1]
    assert relaunch_cmd.startswith("exec ")
    parsed = shlex.split(relaunch_cmd[len("exec ") :])
    assert parsed == [
        sys.executable,
        "-m",
        "sase",
        "tui",
        "my-query",
        "--tab",
        "agents",
        "--profile",
    ]
    assert "--tmux" not in parsed
    assert "-T" not in parsed


def test_inside_tmux_uses_current_session(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True, session_name="my-session")
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    target_arg = new_window_call[new_window_call.index("-t") + 1]
    assert target_arg == "my-session:"
    # We should NOT have created or checked for the agents session.
    assert not any(c[1] == "has-session" for c in fake.calls)
    assert not any(c[1] == "new-session" for c in fake.calls)


def test_outside_tmux_creates_agents_session(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    fake = _FakeTmux(in_tmux=False)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    assert any(
        c[1] == "has-session" and ace_tmux._AGENTS_SESSION in c for c in fake.calls
    )
    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    target_arg = new_window_call[new_window_call.index("-t") + 1]
    assert target_arg == f"{ace_tmux._AGENTS_SESSION}:"


def test_outside_tmux_creates_session_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)

    class _FakeNoSession(_FakeTmux):
        def __call__(
            self, cmd: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            self.calls.append(list(cmd))
            if cmd[1] == "has-session":
                return _completed(cmd, returncode=1, stderr="no such session\n")
            return super().__call__(cmd, **kwargs)

    fake = _FakeNoSession(in_tmux=False)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    assert any(c[1] == "new-session" for c in fake.calls)


def test_relaunch_replaces_legacy_ace_subcommand(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "ace", "--tmux", "my-query"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    relaunch_cmd = new_window_call[-1]
    parsed = shlex.split(relaunch_cmd[len("exec ") :])
    assert parsed == [sys.executable, "-m", "sase", "tui", "my-query"]


def test_relaunch_preserves_global_options_before_tui(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(
            sys,
            "argv",
            ["sase", "-p", "-f", "provider_drain", "tui", "--tmux", "my query"],
        ),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    relaunch_cmd = new_window_call[-1]
    parsed = shlex.split(relaunch_cmd[len("exec ") :])
    assert parsed == [
        sys.executable,
        "-m",
        "sase",
        "-p",
        "-f",
        "provider_drain",
        "tui",
        "my query",
    ]


def test_relaunch_preserves_separator_query_flags(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(
            sys,
            "argv",
            ["sase", "tui", "--tmux", "ready", "--", "--tmux", "-T"],
        ),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    relaunch_cmd = new_window_call[-1]
    parsed = shlex.split(relaunch_cmd[len("exec ") :])
    assert parsed == [
        sys.executable,
        "-m",
        "sase",
        "tui",
        "ready",
        "--",
        "--tmux",
        "-T",
    ]


def test_sets_profiling_env_vars_by_default(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    monkeypatch.delenv("SASE_TUI_TRACE", raising=False)
    monkeypatch.delenv("SASE_TUI_PERF", raising=False)
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    # tmux's `-e KEY=VAL` is repeated per env var.
    e_values = [
        new_window_call[i + 1] for i, tok in enumerate(new_window_call) if tok == "-e"
    ]
    assert "SASE_TUI_TRACE=1" in e_values
    assert "SASE_TUI_PERF=1" in e_values
    assert any(value.startswith("SASE_TUI_SCREENSHOT_DIR=") for value in e_values)


def test_sets_screenshot_env_to_printed_request_dir(capsys, monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    out = capsys.readouterr().out
    screenshot_dir = next(
        line.partition("=")[2]
        for line in out.splitlines()
        if line.startswith("sase_screenshot_dir=")
    )
    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    e_values = [
        new_window_call[i + 1] for i, tok in enumerate(new_window_call) if tok == "-e"
    ]
    assert f"SASE_TUI_SCREENSHOT_DIR={screenshot_dir}" in e_values
    assert screenshot_dir


def test_respects_explicit_profiling_env_var(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    monkeypatch.setenv("SASE_TUI_TRACE", "0")
    monkeypatch.delenv("SASE_TUI_PERF", raising=False)
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    e_values = [
        new_window_call[i + 1] for i, tok in enumerate(new_window_call) if tok == "-e"
    ]
    assert "SASE_TUI_TRACE=0" in e_values
    assert "SASE_TUI_PERF=1" in e_values


def test_profiling_env_args_precede_window_name(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    monkeypatch.delenv("SASE_TUI_TRACE", raising=False)
    monkeypatch.delenv("SASE_TUI_PERF", raising=False)
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    name_idx = new_window_call.index("-n")
    e_indices = [i for i, tok in enumerate(new_window_call) if tok == "-e"]
    assert e_indices, "expected at least one -e KEY=VAL pair"
    # Every -e must precede -n so it applies to the new window, not the
    # relaunch command's operands.
    assert max(e_indices) < name_idx


def test_exits_with_message_when_tmux_missing(capsys) -> None:
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value=None),
        pytest.raises(SystemExit) as excinfo,
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "tmux executable not found" in err
