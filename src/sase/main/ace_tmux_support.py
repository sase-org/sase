"""Shared types and command helpers for :mod:`sase.main.ace_tmux`."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
import subprocess

_AGENTS_SESSION = "sase_ace_agents"
_WINDOW_PREFIX = "sase_tmux_"
_BOOTSTRAP_WINDOW_PREFIX = "sase_bootstrap_"
_MAX_WINDOW_ATTEMPTS = 1000
_WINDOW_CLAIM_FILE = ".sase_tmux_window_claim"
_SCREENSHOT_DIR_OPTION = "@sase_screenshot_dir"
_PROFILING_ENV_DEFAULTS = {"SASE_TUI_TRACE": "1", "SASE_TUI_PERF": "1"}


class TmuxLaunchError(Exception):
    """Raised when launching the TUI in tmux fails."""


_RunCommand = Callable[..., subprocess.CompletedProcess[str]]
_TimeoutValue = float | Callable[[], float] | None
_RunTmuxCommand = Callable[..., subprocess.CompletedProcess[str]]
_RequestDir = Callable[[str, str], Path]


@dataclass(frozen=True)
class TmuxWindow:
    """Details for a tmux window created for agent automation."""

    session: str
    window_name: str
    window_id: str
    pane_pid: int
    screenshot_dir: str

    @property
    def target(self) -> str:
        return self.window_id

    def __iter__(self) -> Iterator[str | int]:
        yield self.window_name
        yield self.pane_pid
        yield self.screenshot_dir


@dataclass(frozen=True)
class OwnedBootstrapWindow:
    session: str
    window_name: str
    window_id: str | None = None

    @property
    def target(self) -> str:
        return self.window_id or f"{self.session}:{self.window_name}"


@dataclass(frozen=True)
class ResolvedSession:
    session: str
    bootstrap_window: OwnedBootstrapWindow | None = None


def default_runner(runner: _RunCommand | None) -> _RunCommand:
    return subprocess.run if runner is None else runner


def _timeout_kwargs(timeout: _TimeoutValue) -> dict[str, float]:
    if timeout is None:
        return {}
    value = timeout() if callable(timeout) else timeout
    return {"timeout": max(0.001, value)}


def run_tmux_command(
    cmd: list[str], *, runner: _RunCommand, timeout: _TimeoutValue, action: str
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            cmd, capture_output=True, text=True, check=False, **_timeout_kwargs(timeout)
        )
    except subprocess.TimeoutExpired as exc:
        raise TmuxLaunchError(f"timed out while trying to {action}") from exc
    except OSError as exc:
        raise TmuxLaunchError(f"failed to {action}: {exc}") from exc


def kill_window_best_effort(target: str | None, *, runner: _RunCommand) -> None:
    if not target:
        return
    try:
        runner(
            ["tmux", "kill-window", "-t", target],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        pass


def kill_owned_bootstrap_window(
    bootstrap: OwnedBootstrapWindow | None, *, runner: _RunCommand
) -> None:
    if bootstrap is not None:
        kill_window_best_effort(bootstrap.target, runner=runner)
