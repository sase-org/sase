"""Compatibility facade for launching ``sase tui`` in tmux."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from sase.ace.tui.screenshot_export import screenshot_request_dir
from sase.main import ace_tmux_session, ace_tmux_window
from sase.main.ace_tmux_support import (
    _AGENTS_SESSION,
    _BOOTSTRAP_WINDOW_PREFIX,
    _MAX_WINDOW_ATTEMPTS,
    _PROFILING_ENV_DEFAULTS,
    _SCREENSHOT_DIR_OPTION,
    _TimeoutValue,
    _TmuxLaunchError,
    _TmuxWindow,
    _WINDOW_CLAIM_FILE,
    _WINDOW_PREFIX,
    TmuxLaunchError,
    default_runner,
    kill_owned_bootstrap_window,
    kill_window_best_effort,
    run_tmux_command,
)

_TUI_COMMAND = "tui"
_LEGACY_ACE_COMMAND = "ace"


def _run_tmux_command(cmd, *, runner, timeout, action):
    """Run a tmux command through the facade's patchable subprocess seam."""
    if runner is subprocess.run:
        runner = subprocess.run
    return run_tmux_command(cmd, runner=runner, timeout=timeout, action=action)


def _default_runner(runner):
    # Keep the historical monkeypatch seam at ``ace_tmux.subprocess.run``.
    return subprocess.run if runner is None else runner


def _require_tmux_binary() -> None:
    if shutil.which("tmux") is None:
        raise _TmuxLaunchError("tmux executable not found on PATH")


def _resolve_or_create_session(*, runner=None, timeout=None):
    return ace_tmux_session.resolve_or_create_session(
        runner=_default_runner(runner), timeout=timeout, run_command=_run_tmux_command
    )


def _resolve_or_create_agent_session(*, runner=None, timeout=None):
    return ace_tmux_session.resolve_or_create_agent_session(
        runner=_default_runner(runner), timeout=timeout, run_command=_run_tmux_command
    )


def _claim_window(session, relaunch_cmd, *, extra_env=None, runner=None, timeout=None):
    return ace_tmux_window.claim_window(
        session,
        relaunch_cmd,
        request_dir=screenshot_request_dir,
        run_command=_run_tmux_command,
        runner=_default_runner(runner),
        timeout=timeout,
        extra_env=extra_env,
    )


def release_tmux_window_claim(screenshot_dir: str | Path) -> None:
    ace_tmux_window.release_window_claim(screenshot_dir)


def _set_session_default_size(session, cols, rows, *, runner=None, timeout=None):
    return ace_tmux_window.set_session_default_size(
        session,
        cols,
        rows,
        run_command=_run_tmux_command,
        runner=_default_runner(runner),
        timeout=timeout,
    )


def _resize_and_verify_window(target, cols, rows, *, runner=None, timeout=None):
    return ace_tmux_window.resize_and_verify_window(
        target,
        cols,
        rows,
        run_command=_run_tmux_command,
        runner=_default_runner(runner),
        timeout=timeout,
    )


def _kill_window_best_effort(target, *, runner=None):
    return kill_window_best_effort(target, runner=_default_runner(runner))


def _kill_owned_bootstrap_window(bootstrap, *, runner=None):
    return kill_owned_bootstrap_window(bootstrap, runner=_default_runner(runner))


def launch_ace_in_tmux(args: argparse.Namespace) -> None:
    """Launch the TUI in a claimed tmux window and print its identity."""
    del args
    resolved = None
    window = None
    try:
        _require_tmux_binary()
        resolved = _resolve_or_create_session()
        window = _claim_window(resolved.session, _build_relaunch_cmd())
        _kill_owned_bootstrap_window(resolved.bootstrap_window)
    except _TmuxLaunchError as exc:
        if window is not None:
            _kill_window_best_effort(window.target)
            release_tmux_window_claim(window.screenshot_dir)
        if resolved is not None:
            _kill_owned_bootstrap_window(resolved.bootstrap_window)
        print(f"sase tui --tmux: {exc}", file=sys.stderr)
        sys.exit(2)
    _print_target(window)


def create_agent_tmux_window(
    relaunch_cmd: str,
    *,
    cols: int | None = None,
    rows: int | None = None,
    extra_env: dict[str, str] | None = None,
    runner=None,
    timeout: _TimeoutValue = None,
) -> _TmuxWindow:
    """Create an automation window in the detached agents tmux session."""
    run = _default_runner(runner)
    _require_tmux_binary()
    resolved = _resolve_or_create_agent_session(runner=run, timeout=timeout)
    window = None
    if cols is not None and rows is not None:
        try:
            _set_session_default_size(
                resolved.session, cols, rows, runner=run, timeout=timeout
            )
        except Exception:
            _kill_owned_bootstrap_window(resolved.bootstrap_window, runner=run)
            raise
    try:
        window = _claim_window(
            resolved.session,
            relaunch_cmd,
            extra_env=extra_env,
            runner=run,
            timeout=timeout,
        )
        _kill_owned_bootstrap_window(resolved.bootstrap_window, runner=run)
        if cols is not None and rows is not None:
            _resize_and_verify_window(
                window.target, cols, rows, runner=run, timeout=timeout
            )
    except Exception:
        if window is not None:
            _kill_window_best_effort(window.target, runner=run)
            release_tmux_window_claim(window.screenshot_dir)
        _kill_owned_bootstrap_window(resolved.bootstrap_window, runner=run)
        raise
    return window


def _build_relaunch_cmd() -> str:
    from sase.main.parser_root_args import root_command_index

    forwarded = []
    after_separator = False
    for arg in sys.argv[1:]:
        if arg == "--":
            after_separator = True
        if not after_separator and arg in ("--tmux", "-T"):
            continue
        forwarded.append(arg)
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


def _print_target(window: _TmuxWindow) -> None:
    print(f"sase_tmux_window={window.window_name}")
    print(f"sase_tmux_session={window.session}")
    print(f"sase_tmux_target={window.target}")
    print(f"sase_tmux_window_id={window.window_id}")
    print(f"sase_tmux_pid={window.pane_pid}")
    print(f"sase_screenshot_dir={window.screenshot_dir}")
