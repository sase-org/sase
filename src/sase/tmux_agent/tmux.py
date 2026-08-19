"""Injectable wrapper over ``tmux(1)`` for the tmux Agent launcher.

Every tmux invocation in this package goes through :class:`TmuxRunner` so
tests never need a live tmux server. Version parsing is the single copy
shared with ``sase doctor``'s passthrough check.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os
import re
import shlex
import shutil
import subprocess
import sys

_TMUX_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?")

_RunFn = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def parse_tmux_version(output: str) -> tuple[int, int] | None:
    """Parse ``tmux -V`` output into a ``(major, minor)`` pair.

    Accepts ``tmux 3.5a``, ``tmux 3.3``, or a bare ``3.4``. A missing minor
    component becomes ``0``. Returns ``None`` when no version digits appear.
    """
    match = _TMUX_VERSION_RE.search(output)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2) or "0"))


def tmux_available() -> bool:
    """Return whether a ``tmux`` executable is resolvable on ``PATH``."""
    return shutil.which("tmux") is not None


def inside_tmux(env: Mapping[str, str] | None = None) -> bool:
    """Return whether the process is running inside a tmux session.

    Matches :func:`sase.ace.tui.graphics._viewer_tmux_common.is_tmux_session`:
    either ``$TMUX`` or ``$TMUX_PANE`` is set.
    """
    source = os.environ if env is None else env
    return bool(source.get("TMUX") or source.get("TMUX_PANE"))


def tmux_agent_self_command() -> str:
    """Return the command prefix used to re-enter ``sase tmux-agent``.

    Prefers a PATH-resolvable ``sase`` so deployed installs match the user's
    shell; falls back to ``python -m sase`` for an editable checkout, the
    same strategy :mod:`sase.main.ace_tmux` uses for its relaunch command.
    """
    if shutil.which("sase"):
        return "sase tmux-agent"
    return shlex.join((sys.executable, "-m", "sase", "tmux-agent"))


def _default_run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    argv = [str(item) for item in args]
    try:
        return subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, 127, "", "tmux: command not found")
    except OSError as exc:
        return subprocess.CompletedProcess(
            argv, 127, "", f"{type(exc).__name__}: {exc}"
        )


class TmuxRunner:
    """Thin, typed wrapper over ``tmux(1)`` with an injectable ``run`` seam."""

    def __init__(self, run: _RunFn | None = None) -> None:
        self._run = run or _default_run

    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        """Run *args* (full argv, including the ``tmux`` program token)."""
        return self._run(args)

    def tmux_version(self) -> tuple[int, int] | None:
        """Return the parsed ``tmux -V`` pair, or ``None`` if unreadable."""
        result = self.run(("tmux", "-V"))
        if result.returncode != 0:
            return parse_tmux_version(result.stderr or result.stdout)
        return parse_tmux_version(result.stdout or result.stderr)

    def current_pane_directory(self) -> str | None:
        """Return ``#{pane_current_path}``, or ``None`` on failure."""
        result = self.run(("tmux", "display-message", "-p", "#{pane_current_path}"))
        if result.returncode != 0:
            return None
        path = result.stdout.strip()
        return path or None

    def list_windows(self) -> tuple[tuple[int, str], ...]:
        """Return ``(index, name)`` pairs from the current session."""
        result = self.run(
            ("tmux", "list-windows", "-F", "#{window_index}:#{window_name}")
        )
        if result.returncode != 0:
            return ()
        windows: list[tuple[int, str]] = []
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            index_str, separator, name = line.partition(":")
            if not separator or not index_str.isdigit():
                continue
            windows.append((int(index_str), name))
        return tuple(windows)

    def new_window(
        self,
        *,
        name: str,
        directory: str,
        command: str,
        env: Sequence[tuple[str, str]] = (),
    ) -> subprocess.CompletedProcess[str]:
        """Create a window named *name* in *directory* running *command*."""
        args: list[str] = ["tmux", "new-window", "-n", name, "-c", directory]
        for key, value in env:
            args.extend(("-e", f"{key}={value}"))
        args.append(command)
        return self.run(args)

    def rename_window(self, index: int, name: str) -> subprocess.CompletedProcess[str]:
        """Rename the window at *index* to *name*."""
        return self.run(("tmux", "rename-window", "-t", str(index), name))

    def run_shell_background(self, command: str) -> subprocess.CompletedProcess[str]:
        """Hand *command* to the tmux server with ``run-shell -b``."""
        return self.run(("tmux", "run-shell", "-b", command))

    def display_menu(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        """Run a previously built ``display-menu`` argv."""
        argv = [str(item) for item in args]
        if not argv or argv[0] != "tmux":
            argv = ["tmux", *argv]
        return self.run(argv)


__all__ = [
    "TmuxRunner",
    "inside_tmux",
    "parse_tmux_version",
    "tmux_agent_self_command",
    "tmux_available",
]
