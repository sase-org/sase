"""Claimed tmux window reservation, creation, and fixed-size setup."""

from __future__ import annotations

import os
from pathlib import Path
import uuid

from sase.ace.tui.screenshot_export import SASE_TUI_SCREENSHOT_DIR_ENV
from sase.main.ace_tmux_support import (
    _MAX_WINDOW_ATTEMPTS,
    _PROFILING_ENV_DEFAULTS,
    _SCREENSHOT_DIR_OPTION,
    _WINDOW_CLAIM_FILE,
    _WINDOW_PREFIX,
    _RunCommand,
    _TimeoutValue,
    _TmuxLaunchError,
    _TmuxWindow,
    kill_window_best_effort,
)


def release_window_claim(screenshot_dir: str | Path) -> None:
    try:
        Path(screenshot_dir).expanduser().joinpath(_WINDOW_CLAIM_FILE).unlink()
    except (FileNotFoundError, OSError):
        pass


def reserve_window_claim(session: str, window_name: str, *, request_dir) -> str | None:
    screenshot_dir = request_dir(session, window_name)
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


def tmux_env_args(
    session: str,
    window_name: str,
    *,
    request_dir,
    screenshot_dir: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> list[str]:
    args: list[str] = []
    for key, default in _PROFILING_ENV_DEFAULTS.items():
        args.extend(["-e", f"{key}={os.environ.get(key, default)}"])
    args.extend(
        [
            "-e",
            f"{SASE_TUI_SCREENSHOT_DIR_ENV}={screenshot_dir or request_dir(session, window_name)}",
        ]
    )
    for key, value in (extra_env or {}).items():
        args.extend(["-e", f"{key}={value}"])
    return args


def claim_window(
    session: str,
    relaunch_cmd: str,
    *,
    request_dir,
    run_command,
    runner: _RunCommand,
    timeout: _TimeoutValue,
    extra_env: dict[str, str] | None = None,
) -> _TmuxWindow:
    for n in range(1, _MAX_WINDOW_ATTEMPTS + 1):
        window_name = f"{_WINDOW_PREFIX}{n}"
        screenshot_dir = reserve_window_claim(
            session, window_name, request_dir=request_dir
        )
        if screenshot_dir is None:
            continue
        temporary_name: str | None = None
        window_id: str | None = None
        creation_attempted = False
        try:
            listed = run_command(
                ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
                runner=runner,
                timeout=timeout,
                action=f"list tmux windows in session {session!r}",
            )
            if listed.returncode == 0 and window_name in listed.stdout.splitlines():
                release_window_claim(screenshot_dir)
                continue
            temporary_name = f"{window_name}_{uuid.uuid4().hex[:12]}"
            creation_attempted = True
            result = run_command(
                [
                    "tmux",
                    "new-window",
                    "-d",
                    *tmux_env_args(
                        session,
                        window_name,
                        request_dir=request_dir,
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
                runner=runner,
                timeout=timeout,
                action=f"create tmux window {window_name!r} in session {session!r}",
            )
            if result.returncode != 0:
                raise _TmuxLaunchError(
                    "tmux new-window failed: "
                    + (result.stderr.strip() or result.stdout.strip())
                )
            fields = (
                result.stdout.strip().splitlines()[-1] if result.stdout else ""
            ).split("\t")
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
            set_window_metadata(
                window_id,
                screenshot_dir=screenshot_dir,
                run_command=run_command,
                runner=runner,
                timeout=timeout,
            )
            rename_window(
                window_id,
                window_name,
                run_command=run_command,
                runner=runner,
                timeout=timeout,
            )
            return _TmuxWindow(
                reported_session or session,
                window_name,
                window_id,
                pane_pid,
                screenshot_dir,
            )
        except Exception:
            kill_window_best_effort(
                window_id
                or (
                    f"{session}:{temporary_name}"
                    if creation_attempted and temporary_name
                    else None
                ),
                runner=runner,
            )
            release_window_claim(screenshot_dir)
            raise
    raise _TmuxLaunchError(
        f"exhausted {_MAX_WINDOW_ATTEMPTS} window-name attempts in session '{session}'"
    )


def set_session_default_size(
    session: str,
    cols: int,
    rows: int,
    *,
    run_command,
    runner: _RunCommand,
    timeout: _TimeoutValue,
) -> None:
    result = run_command(
        ["tmux", "set-option", "-t", session, "default-size", f"{cols}x{rows}"],
        runner=runner,
        timeout=timeout,
        action=f"set tmux default-size for session {session!r}",
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise _TmuxLaunchError(
            "failed to set tmux default-size "
            f"to {cols}x{rows}; tmux 2.9 or newer is required"
            + (f": {detail}" if detail else "")
        )


def set_window_metadata(
    target: str,
    *,
    screenshot_dir: str,
    run_command,
    runner: _RunCommand,
    timeout: _TimeoutValue,
) -> None:
    result = run_command(
        [
            "tmux",
            "set-option",
            "-w",
            "-t",
            target,
            _SCREENSHOT_DIR_OPTION,
            screenshot_dir,
        ],
        runner=runner,
        timeout=timeout,
        action=f"record screenshot request dir for tmux window {target}",
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise _TmuxLaunchError(
            f"failed to record screenshot request dir for tmux window {target}"
            + (f": {detail}" if detail else "")
        )


def rename_window(
    target: str,
    window_name: str,
    *,
    run_command,
    runner: _RunCommand,
    timeout: _TimeoutValue,
) -> None:
    result = run_command(
        ["tmux", "rename-window", "-t", target, window_name],
        runner=runner,
        timeout=timeout,
        action=f"rename tmux window {target} to {window_name}",
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise _TmuxLaunchError(
            f"failed to rename tmux window {target} to {window_name}"
            + (f": {detail}" if detail else "")
        )


def resize_and_verify_window(
    target: str,
    cols: int,
    rows: int,
    *,
    run_command,
    runner: _RunCommand,
    timeout: _TimeoutValue,
) -> None:
    resized = run_command(
        ["tmux", "resize-window", "-t", target, "-x", str(cols), "-y", str(rows)],
        runner=runner,
        timeout=timeout,
        action=f"resize tmux window {target} to {cols}x{rows}",
    )
    if resized.returncode != 0:
        detail = resized.stderr.strip() or resized.stdout.strip()
        raise _TmuxLaunchError(
            f"failed to resize tmux window {target} to {cols}x{rows}"
            + (f": {detail}" if detail else "")
        )
    displayed = run_command(
        [
            "tmux",
            "display-message",
            "-p",
            "-t",
            target,
            "#{window_width}x#{window_height}",
        ],
        runner=runner,
        timeout=timeout,
        action=f"read tmux window size for {target}",
    )
    if displayed.returncode != 0:
        detail = displayed.stderr.strip() or displayed.stdout.strip()
        raise _TmuxLaunchError(
            f"failed to read tmux window size for {target}"
            + (f": {detail}" if detail else "")
        )
    actual, expected = displayed.stdout.strip(), f"{cols}x{rows}"
    if actual != expected:
        raise _TmuxLaunchError(
            f"tmux window geometry mismatch for {target}: expected {expected}, got {actual or 'empty'}; tmux 2.9 or newer is required for detached fixed-size captures"
        )
