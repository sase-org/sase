"""Launch ``sase ace`` in a new tmux window for agent automation."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys

_AGENTS_SESSION = "sase_ace_agents"
_WINDOW_PREFIX = "sase_tmux_"
_MAX_WINDOW_ATTEMPTS = 1000


class _TmuxLaunchError(Exception):
    """Raised when launching the TUI in tmux fails."""


def launch_ace_in_tmux(args: argparse.Namespace) -> None:
    """Launch the ace TUI inside a new tmux window named ``sase_tmux_<N>``.

    Prints ``key=value`` lines on stdout describing the spawned window so
    callers (typically scripting agents) can drive it via
    ``tmux send-keys`` and ``tmux capture-pane``.
    """
    del args  # we forward sys.argv, not the parsed namespace
    try:
        _require_tmux_binary()
        session = _resolve_or_create_session()
        relaunch_cmd = _build_relaunch_cmd()
        window_name, pane_pid = _claim_window(session, relaunch_cmd)
    except _TmuxLaunchError as exc:
        print(f"sase ace --tmux: {exc}", file=sys.stderr)
        sys.exit(2)

    _print_target(session, window_name, pane_pid)


def _require_tmux_binary() -> None:
    if shutil.which("tmux") is None:
        raise _TmuxLaunchError("tmux executable not found on PATH")


def _resolve_or_create_session() -> str:
    if os.environ.get("TMUX"):
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise _TmuxLaunchError(
                f"failed to read current tmux session name: {result.stderr.strip()}"
            )
        name = result.stdout.strip()
        if not name:
            raise _TmuxLaunchError("tmux returned an empty session name")
        return name

    # Outside of tmux: ensure the dedicated agents session exists.
    has_session = subprocess.run(
        ["tmux", "has-session", "-t", _AGENTS_SESSION],
        capture_output=True,
        text=True,
        check=False,
    )
    if has_session.returncode != 0:
        created = subprocess.run(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                _AGENTS_SESSION,
                "-n",
                "placeholder",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            raise _TmuxLaunchError(
                f"failed to create '{_AGENTS_SESSION}' session: "
                f"{created.stderr.strip()}"
            )
    return _AGENTS_SESSION


def _build_relaunch_cmd() -> str:
    """Return the shell command string to run inside the new tmux window.

    Strips ``--tmux``/``-T`` from ``sys.argv`` so we don't recurse, and
    re-invokes the same Python interpreter (preserving the active venv) via
    ``python -m sase ace ...``.

    Returns a single ``/bin/sh -c``-compatible string prefixed with ``exec``
    so the shell replaces itself with the Python interpreter — that way
    tmux's ``#{pane_pid}`` reports the live Python PID, not the shell's.
    """
    forwarded: list[str] = []
    for arg in sys.argv[1:]:
        if arg in ("--tmux", "-T"):
            continue
        forwarded.append(arg)

    # sys.argv[1:] starts with the "ace" subcommand. If for any reason it
    # doesn't (e.g. invoked via a different entrypoint), prepend it.
    if not forwarded or forwarded[0] != "ace":
        forwarded = ["ace", *forwarded]

    return "exec " + shlex.join([sys.executable, "-m", "sase", *forwarded])


def _claim_window(session: str, relaunch_cmd: str) -> tuple[str, int]:
    """Create a uniquely-named ``sase_tmux_<N>`` window in ``session``.

    Uses tmux's own refusal to create duplicate window names as the
    arbiter, avoiding any TOCTOU race against parallel ``--tmux`` invocations.

    Returns ``(window_name, pane_pid)`` where ``pane_pid`` is the PID of the
    process tmux launched in the new window's pane.
    """
    for n in range(1, _MAX_WINDOW_ATTEMPTS + 1):
        window_name = f"{_WINDOW_PREFIX}{n}"
        result = subprocess.run(
            [
                "tmux",
                "new-window",
                "-d",
                "-n",
                window_name,
                "-t",
                f"{session}:",
                "-P",
                "-F",
                "#{session_name}:#{window_id} #{pane_pid}",
                relaunch_cmd,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            line = result.stdout.strip().splitlines()[-1] if result.stdout else ""
            fields = line.split()
            if len(fields) != 2:
                raise _TmuxLaunchError(
                    "tmux did not report the new window's target and pane pid"
                )
            pid_str = fields[1]
            try:
                pane_pid = int(pid_str)
            except ValueError as exc:
                raise _TmuxLaunchError(
                    f"tmux returned non-integer pane pid: {pid_str!r}"
                ) from exc
            return window_name, pane_pid

        if _window_name_in_use(session, window_name):
            continue

        raise _TmuxLaunchError(
            f"tmux new-window failed: {result.stderr.strip() or result.stdout.strip()}"
        )

    raise _TmuxLaunchError(
        f"exhausted {_MAX_WINDOW_ATTEMPTS} window-name attempts in session '{session}'"
    )


def _window_name_in_use(session: str, window_name: str) -> bool:
    result = subprocess.run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return window_name in result.stdout.splitlines()


def _print_target(session: str, window_name: str, pane_pid: int) -> None:
    print(f"sase_tmux_window={window_name}")
    print(f"sase_tmux_session={session}")
    print(f"sase_tmux_pid={pane_pid}")
