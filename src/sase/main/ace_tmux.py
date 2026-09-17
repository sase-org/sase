"""Launch ``sase tui`` in a new tmux window for agent automation."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable

from sase.ace.tui.screenshot_export import (
    SASE_TUI_SCREENSHOT_DIR_ENV,
    screenshot_request_dir,
)

_AGENTS_SESSION = "sase_ace_agents"
_WINDOW_PREFIX = "sase_tmux_"
_MAX_WINDOW_ATTEMPTS = 1000

# Env vars injected into agent-spawned TUI windows so trace/perf JSONL files
# get populated without the caller having to remember to export them. Caller-
# provided values (including ``0`` to opt out) are passed through unchanged.
_PROFILING_ENV_DEFAULTS = {
    "SASE_TUI_TRACE": "1",
    "SASE_TUI_PERF": "1",
}
_TUI_COMMAND = "tui"
_LEGACY_ACE_COMMAND = "ace"


class _TmuxLaunchError(Exception):
    """Raised when launching the TUI in tmux fails."""


TmuxLaunchError = _TmuxLaunchError
_RunCommand = Callable[..., subprocess.CompletedProcess[str]]


def _default_runner(runner: _RunCommand | None) -> _RunCommand:
    return subprocess.run if runner is None else runner


def launch_ace_in_tmux(args: argparse.Namespace) -> None:
    """Launch sase's TUI inside a new tmux window named ``sase_tmux_<N>``.

    Prints ``key=value`` lines on stdout describing the spawned window so
    callers (typically scripting agents) can drive it via
    ``tmux send-keys`` and ``tmux capture-pane``.
    """
    del args  # we forward sys.argv, not the parsed namespace
    try:
        _require_tmux_binary()
        session = _resolve_or_create_session()
        relaunch_cmd = _build_relaunch_cmd()
        window_name, pane_pid, screenshot_dir = _claim_window(session, relaunch_cmd)
    except _TmuxLaunchError as exc:
        print(f"sase tui --tmux: {exc}", file=sys.stderr)
        sys.exit(2)

    _print_target(session, window_name, pane_pid, screenshot_dir)


def _require_tmux_binary() -> None:
    if shutil.which("tmux") is None:
        raise _TmuxLaunchError("tmux executable not found on PATH")


def create_agent_tmux_window(
    relaunch_cmd: str,
    *,
    cols: int | None = None,
    rows: int | None = None,
    extra_env: dict[str, str] | None = None,
    runner: _RunCommand | None = None,
) -> tuple[str, int, str]:
    """Create an automation TUI window in the detached agents tmux session."""
    run = _default_runner(runner)
    _require_tmux_binary()
    session = _resolve_or_create_agent_session(runner=run)
    if cols is not None and rows is not None:
        _set_session_default_size(session, cols, rows, runner=run)
    window_name, pane_pid, screenshot_dir = _claim_window(
        session,
        relaunch_cmd,
        extra_env=extra_env,
        runner=run,
    )
    if cols is not None and rows is not None:
        _resize_and_verify_window(session, window_name, cols, rows, runner=run)
    return window_name, pane_pid, screenshot_dir


def _resolve_or_create_session(
    *,
    runner: _RunCommand | None = None,
) -> str:
    run = _default_runner(runner)
    if os.environ.get("TMUX"):
        result = run(
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

    return _resolve_or_create_agent_session(runner=run)


def _resolve_or_create_agent_session(
    *,
    runner: _RunCommand | None = None,
) -> str:
    run = _default_runner(runner)
    # Outside of tmux: ensure the dedicated agents session exists.
    has_session = run(
        ["tmux", "has-session", "-t", _AGENTS_SESSION],
        capture_output=True,
        text=True,
        check=False,
    )
    if has_session.returncode != 0:
        created = run(
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
    ``python -m sase tui ...``.

    Returns a single ``/bin/sh -c``-compatible string prefixed with ``exec``
    so the shell replaces itself with the Python interpreter — that way
    tmux's ``#{pane_pid}`` reports the live Python PID, not the shell's.
    """
    from sase.main.parser_root_args import root_command_index

    forwarded: list[str] = []
    after_separator = False
    for arg in sys.argv[1:]:
        if arg == "--":
            after_separator = True
            forwarded.append(arg)
            continue
        if not after_separator and arg in ("--tmux", "-T"):
            continue
        forwarded.append(arg)

    # sys.argv[1:] starts with the "tui" subcommand. If for any reason it
    # doesn't (e.g. invoked via a different entrypoint), add it without
    # duplicating global options or query tokens.
    command_index = root_command_index(forwarded)
    if command_index is None:
        forwarded = [_TUI_COMMAND, *forwarded]
    elif forwarded[command_index] == _LEGACY_ACE_COMMAND:
        forwarded = [
            *forwarded[:command_index],
            _TUI_COMMAND,
            *forwarded[command_index + 1 :],
        ]
    elif forwarded[command_index] != _TUI_COMMAND:
        forwarded = [
            *forwarded[:command_index],
            _TUI_COMMAND,
            *forwarded[command_index:],
        ]

    return "exec " + shlex.join([sys.executable, "-m", "sase", *forwarded])


def _tmux_env_args(
    session: str,
    window_name: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> list[str]:
    """Return ``-e KEY=VAL`` args for ``tmux new-window``.

    Profiling env vars pass through caller-provided values so
    ``SASE_TUI_TRACE=0 sase tui --tmux ...`` opts out cleanly. The screenshot
    request dir is always derived from the claimed tmux session/window so
    later automation can reconstruct it without inspecting process env.
    """
    args: list[str] = []
    for key, default in _PROFILING_ENV_DEFAULTS.items():
        value = os.environ.get(key, default)
        args.extend(["-e", f"{key}={value}"])
    args.extend(
        [
            "-e",
            f"{SASE_TUI_SCREENSHOT_DIR_ENV}={screenshot_request_dir(session, window_name)}",
        ]
    )
    for key, value in (extra_env or {}).items():
        args.extend(["-e", f"{key}={value}"])
    return args


def _claim_window(
    session: str,
    relaunch_cmd: str,
    *,
    extra_env: dict[str, str] | None = None,
    runner: _RunCommand | None = None,
) -> tuple[str, int, str]:
    """Create a uniquely-named ``sase_tmux_<N>`` window in ``session``.

    Uses tmux's own refusal to create duplicate window names as the
    arbiter, avoiding any TOCTOU race against parallel ``--tmux`` invocations.

    Returns ``(window_name, pane_pid, screenshot_dir)`` where ``pane_pid`` is
    the PID of the process tmux launched in the new window's pane.
    """
    run = _default_runner(runner)
    for n in range(1, _MAX_WINDOW_ATTEMPTS + 1):
        window_name = f"{_WINDOW_PREFIX}{n}"
        result = run(
            [
                "tmux",
                "new-window",
                "-d",
                *_tmux_env_args(session, window_name, extra_env=extra_env),
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
            screenshot_dir = str(screenshot_request_dir(session, window_name))
            return window_name, pane_pid, screenshot_dir

        if _window_name_in_use(session, window_name, runner=run):
            continue

        raise _TmuxLaunchError(
            f"tmux new-window failed: {result.stderr.strip() or result.stdout.strip()}"
        )

    raise _TmuxLaunchError(
        f"exhausted {_MAX_WINDOW_ATTEMPTS} window-name attempts in session '{session}'"
    )


def _window_name_in_use(
    session: str,
    window_name: str,
    *,
    runner: _RunCommand | None = None,
) -> bool:
    run = _default_runner(runner)
    result = run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return window_name in result.stdout.splitlines()


def _set_session_default_size(
    session: str,
    cols: int,
    rows: int,
    *,
    runner: _RunCommand | None = None,
) -> None:
    run = _default_runner(runner)
    result = run(
        ["tmux", "set-option", "-t", session, "default-size", f"{cols}x{rows}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise _TmuxLaunchError(
            "failed to set tmux default-size "
            f"to {cols}x{rows}; tmux 2.9 or newer is required"
            + (f": {detail}" if detail else "")
        )


def _resize_and_verify_window(
    session: str,
    window_name: str,
    cols: int,
    rows: int,
    *,
    runner: _RunCommand | None = None,
) -> None:
    run = _default_runner(runner)
    target = f"{session}:{window_name}"
    resized = run(
        ["tmux", "resize-window", "-t", target, "-x", str(cols), "-y", str(rows)],
        capture_output=True,
        text=True,
        check=False,
    )
    if resized.returncode != 0:
        detail = resized.stderr.strip() or resized.stdout.strip()
        raise _TmuxLaunchError(
            f"failed to resize tmux window {target} to {cols}x{rows}"
            + (f": {detail}" if detail else "")
        )

    displayed = run(
        [
            "tmux",
            "display-message",
            "-p",
            "-t",
            target,
            "#{window_width}x#{window_height}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if displayed.returncode != 0:
        detail = displayed.stderr.strip() or displayed.stdout.strip()
        raise _TmuxLaunchError(
            f"failed to read tmux window size for {target}"
            + (f": {detail}" if detail else "")
        )
    actual = displayed.stdout.strip()
    expected = f"{cols}x{rows}"
    if actual != expected:
        raise _TmuxLaunchError(
            f"tmux window geometry mismatch for {target}: expected {expected}, "
            f"got {actual or 'empty'}; tmux 2.9 or newer is required for "
            "detached fixed-size captures"
        )


def _print_target(
    session: str,
    window_name: str,
    pane_pid: int,
    screenshot_dir: str,
) -> None:
    print(f"sase_tmux_window={window_name}")
    print(f"sase_tmux_session={session}")
    print(f"sase_tmux_pid={pane_pid}")
    print(f"sase_screenshot_dir={screenshot_dir}")
