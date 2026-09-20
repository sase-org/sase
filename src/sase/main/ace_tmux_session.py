"""tmux session resolution and bootstrap ownership."""

from __future__ import annotations

import os
import uuid

from sase.main.ace_tmux_support import (
    _AGENTS_SESSION,
    _BOOTSTRAP_WINDOW_PREFIX,
    OwnedBootstrapWindow,
    ResolvedSession,
    _RunCommand,
    _TimeoutValue,
    TmuxLaunchError,
    kill_window_best_effort,
)


def resolve_or_create_session(
    *, runner: _RunCommand, timeout: _TimeoutValue, run_command
) -> ResolvedSession:
    if os.environ.get("TMUX"):
        result = run_command(
            ["tmux", "display-message", "-p", "#{session_name}"],
            runner=runner,
            timeout=timeout,
            action="read current tmux session name",
        )
        if result.returncode != 0:
            raise TmuxLaunchError(
                f"failed to read current tmux session name: {result.stderr.strip()}"
            )
        name = result.stdout.strip()
        if not name:
            raise TmuxLaunchError("tmux returned an empty session name")
        return ResolvedSession(name)
    return resolve_or_create_agent_session(
        runner=runner, timeout=timeout, run_command=run_command
    )


def resolve_or_create_agent_session(
    *, runner: _RunCommand, timeout: _TimeoutValue, run_command
) -> ResolvedSession:
    has_session = run_command(
        ["tmux", "has-session", "-t", _AGENTS_SESSION],
        runner=runner,
        timeout=timeout,
        action=f"check for tmux session '{_AGENTS_SESSION}'",
    )
    if has_session.returncode == 0:
        return ResolvedSession(_AGENTS_SESSION)
    return _create_agent_session_with_bootstrap(
        runner=runner, timeout=timeout, run_command=run_command
    )


def _create_agent_session_with_bootstrap(
    *, runner: _RunCommand, timeout: _TimeoutValue, run_command
) -> ResolvedSession:
    bootstrap_name = f"{_BOOTSTRAP_WINDOW_PREFIX}{uuid.uuid4().hex[:12]}"
    try:
        created = run_command(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                _AGENTS_SESSION,
                "-n",
                bootstrap_name,
                "-P",
                "-F",
                "#{session_name}\t#{window_id}\t#{window_name}",
            ],
            runner=runner,
            timeout=timeout,
            action=f"create tmux session '{_AGENTS_SESSION}'",
        )
    except Exception:
        kill_window_best_effort(f"{_AGENTS_SESSION}:{bootstrap_name}", runner=runner)
        raise
    if created.returncode != 0:
        raced = run_command(
            ["tmux", "has-session", "-t", _AGENTS_SESSION],
            runner=runner,
            timeout=timeout,
            action=f"re-check tmux session '{_AGENTS_SESSION}'",
        )
        if raced.returncode == 0:
            return ResolvedSession(_AGENTS_SESSION)
        raise TmuxLaunchError(
            f"failed to create '{_AGENTS_SESSION}' session: {created.stderr.strip() or created.stdout.strip()}"
        )
    fields = (created.stdout.strip().splitlines()[-1] if created.stdout else "").split(
        "\t"
    )
    if len(fields) != 3:
        kill_window_best_effort(f"{_AGENTS_SESSION}:{bootstrap_name}", runner=runner)
        raise TmuxLaunchError("tmux did not report the bootstrap window's target")
    session, window_id, reported_name = fields
    if reported_name != bootstrap_name:
        kill_window_best_effort(
            window_id
            if window_id.startswith("@")
            else f"{_AGENTS_SESSION}:{bootstrap_name}",
            runner=runner,
        )
        raise TmuxLaunchError(
            f"tmux reported unexpected bootstrap window name {reported_name!r}"
        )
    if not window_id.startswith("@"):
        kill_window_best_effort(f"{_AGENTS_SESSION}:{bootstrap_name}", runner=runner)
        raise TmuxLaunchError(f"tmux returned invalid window id: {window_id!r}")
    actual_session = session or _AGENTS_SESSION
    return ResolvedSession(
        actual_session, OwnedBootstrapWindow(actual_session, bootstrap_name, window_id)
    )
