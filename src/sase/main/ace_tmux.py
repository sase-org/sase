"""Launch ``sase tui`` in a new tmux window for agent automation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

from sase.ace.tui.screenshot_export import (
    SASE_TUI_SCREENSHOT_DIR_ENV,
    screenshot_request_dir,
)

_AGENTS_SESSION = "sase_ace_agents"
_WINDOW_PREFIX = "sase_tmux_"
_MAX_WINDOW_ATTEMPTS = 1000
_WINDOW_CLAIM_FILE = ".sase_tmux_window_claim"
_SCREENSHOT_DIR_OPTION = "@sase_screenshot_dir"

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
_TimeoutValue = float | Callable[[], float] | None


@dataclass(frozen=True)
class _TmuxWindow:
    """Details for a tmux window created for agent automation."""

    session: str
    window_name: str
    window_id: str
    pane_pid: int
    screenshot_dir: str

    @property
    def target(self) -> str:
        """Return the unique tmux target for this window."""
        return self.window_id

    def __iter__(self) -> Iterator[str | int]:
        """Preserve legacy tuple unpacking as ``(name, pid, screenshot_dir)``."""
        yield self.window_name
        yield self.pane_pid
        yield self.screenshot_dir


def _default_runner(runner: _RunCommand | None) -> _RunCommand:
    return subprocess.run if runner is None else runner


def _timeout_kwargs(timeout: _TimeoutValue) -> dict[str, float]:
    if timeout is None:
        return {}
    value = timeout() if callable(timeout) else timeout
    return {"timeout": max(0.001, value)}


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
        window = _claim_window(session, relaunch_cmd)
    except _TmuxLaunchError as exc:
        print(f"sase tui --tmux: {exc}", file=sys.stderr)
        sys.exit(2)

    _print_target(window)


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
    timeout: _TimeoutValue = None,
) -> _TmuxWindow:
    """Create an automation TUI window in the detached agents tmux session."""
    run = _default_runner(runner)
    _require_tmux_binary()
    session = _resolve_or_create_agent_session(runner=run, timeout=timeout)
    window: _TmuxWindow | None = None
    if cols is not None and rows is not None:
        _set_session_default_size(session, cols, rows, runner=run, timeout=timeout)
    try:
        window = _claim_window(
            session,
            relaunch_cmd,
            extra_env=extra_env,
            runner=run,
            timeout=timeout,
        )
        if cols is not None and rows is not None:
            _resize_and_verify_window(
                window.target,
                cols,
                rows,
                runner=run,
                timeout=timeout,
            )
    except Exception:
        if window is not None:
            _kill_window_best_effort(window.target, runner=run)
            release_tmux_window_claim(window.screenshot_dir)
        raise
    return window


def release_tmux_window_claim(screenshot_dir: str | Path) -> None:
    """Release the local reservation for a non-retained screenshot window."""
    try:
        Path(screenshot_dir).expanduser().joinpath(_WINDOW_CLAIM_FILE).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _reserve_tmux_window_claim(
    session: str,
    window_name: str,
) -> str | None:
    screenshot_dir = screenshot_request_dir(session, window_name)
    try:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            screenshot_dir / _WINDOW_CLAIM_FILE,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        return None
    except OSError as exc:
        raise _TmuxLaunchError(
            f"failed to reserve tmux window {window_name!r}: {exc}"
        ) from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"pid={os.getpid()}\n")
    return str(screenshot_dir)


def _resolve_or_create_session(
    *,
    runner: _RunCommand | None = None,
    timeout: _TimeoutValue = None,
) -> str:
    run = _default_runner(runner)
    if os.environ.get("TMUX"):
        result = run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True,
            text=True,
            check=False,
            **_timeout_kwargs(timeout),
        )
        if result.returncode != 0:
            raise _TmuxLaunchError(
                f"failed to read current tmux session name: {result.stderr.strip()}"
            )
        name = result.stdout.strip()
        if not name:
            raise _TmuxLaunchError("tmux returned an empty session name")
        return name

    return _resolve_or_create_agent_session(runner=run, timeout=timeout)


def _resolve_or_create_agent_session(
    *,
    runner: _RunCommand | None = None,
    timeout: _TimeoutValue = None,
) -> str:
    run = _default_runner(runner)
    # Outside of tmux: ensure the dedicated agents session exists.
    has_session = run(
        ["tmux", "has-session", "-t", _AGENTS_SESSION],
        capture_output=True,
        text=True,
        check=False,
        **_timeout_kwargs(timeout),
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
            **_timeout_kwargs(timeout),
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
    screenshot_dir: str | None = None,
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
            f"{SASE_TUI_SCREENSHOT_DIR_ENV}="
            f"{screenshot_dir or screenshot_request_dir(session, window_name)}",
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
    timeout: _TimeoutValue = None,
) -> _TmuxWindow:
    """Create a claimed ``sase_tmux_<N>`` window in ``session``."""
    run = _default_runner(runner)
    for n in range(1, _MAX_WINDOW_ATTEMPTS + 1):
        window_name = f"{_WINDOW_PREFIX}{n}"
        screenshot_dir = _reserve_tmux_window_claim(session, window_name)
        if screenshot_dir is None:
            continue
        if _window_name_in_use(session, window_name, runner=run, timeout=timeout):
            release_tmux_window_claim(screenshot_dir)
            continue

        temporary_name = f"{window_name}_{uuid.uuid4().hex[:12]}"
        window_id: str | None = None
        result = run(
            [
                "tmux",
                "new-window",
                "-d",
                *_tmux_env_args(
                    session,
                    window_name,
                    screenshot_dir=screenshot_dir,
                    extra_env=extra_env,
                ),
                "-n",
                temporary_name,
                "-t",
                f"{session}:",
                "-P",
                "-F",
                "#{session_name}\t#{window_id}\t#{window_name}\t#{pane_pid}",
                relaunch_cmd,
            ],
            capture_output=True,
            text=True,
            check=False,
            **_timeout_kwargs(timeout),
        )
        try:
            if result.returncode != 0:
                raise _TmuxLaunchError(
                    "tmux new-window failed: "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
            line = result.stdout.strip().splitlines()[-1] if result.stdout else ""
            fields = line.split("\t")
            if len(fields) != 4:
                raise _TmuxLaunchError(
                    "tmux did not report the new window's target and pane pid"
                )
            reported_session, window_id, reported_name, pid_str = fields
            if not window_id.startswith("@"):
                raise _TmuxLaunchError(
                    f"tmux returned invalid window id: {window_id!r}"
                )
            if reported_name != temporary_name:
                raise _TmuxLaunchError(
                    f"tmux reported unexpected temporary window name {reported_name!r}"
                )
            try:
                pane_pid = int(pid_str)
            except ValueError as exc:
                raise _TmuxLaunchError(
                    f"tmux returned non-integer pane pid: {pid_str!r}"
                ) from exc
            _set_window_metadata(
                window_id,
                screenshot_dir=screenshot_dir,
                runner=run,
                timeout=timeout,
            )
            _rename_window(
                window_id,
                window_name,
                runner=run,
                timeout=timeout,
            )
            return _TmuxWindow(
                session=reported_session or session,
                window_name=window_name,
                window_id=window_id,
                pane_pid=pane_pid,
                screenshot_dir=screenshot_dir,
            )
        except Exception:
            _kill_window_best_effort(
                window_id or f"{session}:{temporary_name}",
                runner=run,
            )
            release_tmux_window_claim(screenshot_dir)
            raise

    raise _TmuxLaunchError(
        f"exhausted {_MAX_WINDOW_ATTEMPTS} window-name attempts in session '{session}'"
    )


def _window_name_in_use(
    session: str,
    window_name: str,
    *,
    runner: _RunCommand | None = None,
    timeout: _TimeoutValue = None,
) -> bool:
    run = _default_runner(runner)
    result = run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
        capture_output=True,
        text=True,
        check=False,
        **_timeout_kwargs(timeout),
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
    timeout: _TimeoutValue = None,
) -> None:
    run = _default_runner(runner)
    result = run(
        ["tmux", "set-option", "-t", session, "default-size", f"{cols}x{rows}"],
        capture_output=True,
        text=True,
        check=False,
        **_timeout_kwargs(timeout),
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise _TmuxLaunchError(
            "failed to set tmux default-size "
            f"to {cols}x{rows}; tmux 2.9 or newer is required"
            + (f": {detail}" if detail else "")
        )


def _set_window_metadata(
    target: str,
    *,
    screenshot_dir: str,
    runner: _RunCommand | None = None,
    timeout: _TimeoutValue = None,
) -> None:
    run = _default_runner(runner)
    result = run(
        [
            "tmux",
            "set-option",
            "-w",
            "-t",
            target,
            _SCREENSHOT_DIR_OPTION,
            screenshot_dir,
        ],
        capture_output=True,
        text=True,
        check=False,
        **_timeout_kwargs(timeout),
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise _TmuxLaunchError(
            f"failed to record screenshot request dir for tmux window {target}"
            + (f": {detail}" if detail else "")
        )


def _rename_window(
    target: str,
    window_name: str,
    *,
    runner: _RunCommand | None = None,
    timeout: _TimeoutValue = None,
) -> None:
    run = _default_runner(runner)
    result = run(
        ["tmux", "rename-window", "-t", target, window_name],
        capture_output=True,
        text=True,
        check=False,
        **_timeout_kwargs(timeout),
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise _TmuxLaunchError(
            f"failed to rename tmux window {target} to {window_name}"
            + (f": {detail}" if detail else "")
        )


def _resize_and_verify_window(
    target: str,
    cols: int,
    rows: int,
    *,
    runner: _RunCommand | None = None,
    timeout: _TimeoutValue = None,
) -> None:
    run = _default_runner(runner)
    resized = run(
        ["tmux", "resize-window", "-t", target, "-x", str(cols), "-y", str(rows)],
        capture_output=True,
        text=True,
        check=False,
        **_timeout_kwargs(timeout),
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
        **_timeout_kwargs(timeout),
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


def _kill_window_best_effort(
    target: str | None,
    *,
    runner: _RunCommand | None = None,
) -> None:
    if not target:
        return
    run = _default_runner(runner)
    try:
        run(
            ["tmux", "kill-window", "-t", target],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return


def _print_target(window: _TmuxWindow) -> None:
    print(f"sase_tmux_window={window.window_name}")
    print(f"sase_tmux_session={window.session}")
    print(f"sase_tmux_target={window.target}")
    print(f"sase_tmux_window_id={window.window_id}")
    print(f"sase_tmux_pid={window.pane_pid}")
    print(f"sase_screenshot_dir={window.screenshot_dir}")
