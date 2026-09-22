"""Shared fakes for ``sase tui --tmux`` window-launch tests."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
from typing import Any

import pytest

from sase.main import ace_tmux


def completed_process(
    cmd: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


class FakeTmux:
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
            return completed_process(cmd, stdout=self.session_name + "\n")
        if sub == "has-session":
            return completed_process(cmd, returncode=0 if not self.in_tmux else 1)
        if sub == "list-windows":
            return completed_process(
                cmd,
                stdout="\n".join(str(window["name"]) for window in self.windows) + "\n",
            )
        if sub == "new-session":
            session = cmd[cmd.index("-s") + 1]
            window_name = cmd[cmd.index("-n") + 1]
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
            stdout = f"{session}\t{window_id}\t{window_name}\n" if "-P" in cmd else ""
            return completed_process(cmd, stdout=stdout)
        if sub == "set-option":
            if "-w" not in cmd:
                return completed_process(cmd)
            target = cmd[cmd.index("-t") + 1]
            window = self._window_by_target(target)
            option = cmd[-2]
            value = cmd[-1]
            window["metadata"][option] = value
            return completed_process(cmd)
        if sub == "rename-window":
            target = cmd[cmd.index("-t") + 1]
            window = self._window_by_target(target)
            window["name"] = cmd[-1]
            return completed_process(cmd)
        if sub == "kill-window":
            target = cmd[cmd.index("-t") + 1]
            window = self._window_by_target(target)
            self.windows.remove(window)
            return completed_process(cmd)
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
            return completed_process(
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


def launch_args() -> argparse.Namespace:
    return argparse.Namespace(tmux=True)


class SocketTmuxRunner:
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


def patch_screenshot_request_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        ace_tmux,
        "screenshot_request_dir",
        lambda session, window_name: tmp_path / session / window_name,
    )
