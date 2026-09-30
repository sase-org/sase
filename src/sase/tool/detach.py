"""Agent-only ``sase tool run -d/--detach`` over a plain durable proc.

A detached run is a normal hand-off run that also carries a ``starter``
record naming the agent runner that started it. It stays behind the
``tool_run_escalation`` beta flag; the later ``--join``, bounded-wait, and
automatic phases gate on :func:`escalation_enabled` too.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from sase.tool.argv import ToolRunUsageError, resolve_run_argv
from sase.tool.executor import ToolRunCliRequest
from sase.tool.routing import monitor_start_form
from sase.tool.starter import (
    IDENTITY_UNREADABLE,
    META_UNREADABLE,
    NO_AGENT_NAME,
    NO_ARTIFACTS_DIR,
    PID_MISSING,
    resolve_starter,
)

_STARTER_FAILURE_DETAILS = {
    NO_AGENT_NAME: "SASE_AGENT_NAME is not set",
    NO_ARTIFACTS_DIR: "SASE_ARTIFACTS_DIR is not set",
    META_UNREADABLE: "agent_meta.json is unreadable",
    PID_MISSING: "the agent runner pid is missing",
    IDENTITY_UNREADABLE: "the agent runner identity is unreadable",
}


def escalation_enabled() -> bool:
    """Return whether the ``tool_run_escalation`` beta flag is on."""

    try:
        from sase.feature_flags import FeatureFlag, current_flags

        return current_flags().enabled(FeatureFlag.tool_run_escalation)
    except Exception:  # noqa: BLE001 - an unreadable flag state fails closed.
        return False


def enclosing_owner() -> tuple[str, str] | None:
    """Return ``(kind, id)`` for a live enclosing owner, else ``None``.

    Agents are a new ownership root, so this reads the raw environment
    instead of ``resolve_ownership`` (which clears inherited ids in agents).
    Only a proven-settled owner is ignored; unknown liveness still refuses.
    """

    monitor_id = (os.environ.get("SASE_MONITOR_ID") or "").strip()
    if monitor_id and not _monitor_has_settled():
        return "monitor", monitor_id
    proc_id = (os.environ.get("SASE_PROC_ID") or "").strip()
    if proc_id and not _proc_has_settled(proc_id):
        return "proc", proc_id
    return None


def _monitor_has_settled() -> bool:
    """Mirror the ownership settled proof: terminal marker in artifacts dir."""

    root = (os.environ.get("SASE_MONITOR_ARTIFACTS_DIR") or "").strip()
    if not root:
        return False
    try:
        return (Path(root) / "done.json").is_file()
    except OSError:
        return False


def _proc_has_settled(proc_id: str) -> bool:
    """Mirror the ownership settled proof from the proc store."""

    try:
        from sase.procs.models import TERMINAL_PROC_STATUSES
        from sase.procs.store import get_proc

        proc = get_proc(proc_id)
    except Exception:  # noqa: BLE001 - unknown liveness never clears ownership.
        return False
    return proc is not None and proc.status in TERMINAL_PROC_STATUSES


def parent_run() -> str | None:
    """Return the enclosing parent run id, or ``None`` when there is none."""

    from sase.core.tool_run import tool_run_show

    parent_id = (os.environ.get("SASE_TOOL_RUN_ID") or "").strip()
    if not parent_id:
        return None
    try:
        shown = tool_run_show(parent_id)
    except Exception:  # noqa: BLE001 - a missing parent must not block execution.
        return None
    run = shown.get("run")
    if isinstance(run, dict) and str(run.get("run_id") or "") == parent_id:
        return parent_id
    return None


def execute_detached(
    request: ToolRunCliRequest, *, cwd: Path | str | None = None
) -> int:
    """Reserve a starter-scoped detached run and submit its adopting proc.

    Fail-closed: any reservation, starter, or launch failure exits ``1``
    having started nothing. Usage and refusal exits ``2``.
    """

    if not escalation_enabled():
        print(
            "sase tool run -d/--detach is not enabled "
            "(tool_run_escalation beta flag is off)",
            file=sys.stderr,
        )
        return 2
    if request.keep_going and request.fail_fast:
        print(
            "-k/--keep-going and -x/--fail-fast cannot be used together",
            file=sys.stderr,
        )
        return 2
    if request.verbose:
        print(
            "sase tool run -d cannot be used with -v/--verbose",
            file=sys.stderr,
        )
        return 2
    if request.tail_lines_explicit:
        print(
            "sase tool run -d cannot be used with -T/--tail-lines",
            file=sys.stderr,
        )
        return 2

    words = tuple(request.words)
    quoted = " ".join(shlex.quote(part) for part in words)
    monitor_form = monitor_start_form(words, reason="hand off tool run")
    if not os.environ.get("SASE_AGENT"):
        foreground = f"sase tool run -H {quoted}".strip()
        print(
            "sase tool run -d is only available inside an agent; "
            f"use {foreground} instead",
            file=sys.stderr,
        )
        return 2
    owner = enclosing_owner()
    if owner is not None:
        kind, owner_id = owner
        if kind == "proc":
            try:
                from sase.procs.store import get_proc

                proc = get_proc(owner_id)
            except Exception:  # noqa: BLE001 - unknown owner is still an owner.
                proc = None
            if proc is not None and proc.origin == "ace":
                print(
                    f"sase tool run -d cannot be used inside proc "
                    f"{owner_id}: it is already a detached proc "
                    "(TUI ! command); drop -d and run in the foreground",
                    file=sys.stderr,
                )
                return 2
        print(
            f"sase tool run -d cannot be used inside {kind} {owner_id}; {monitor_form}",
            file=sys.stderr,
        )
        return 2
    parent_id = parent_run()
    if parent_id is not None:
        print(
            f"sase tool run -d cannot be used inside parent tool run "
            f"{parent_id}; {monitor_form}",
            file=sys.stderr,
        )
        return 2

    launch_root = Path(cwd).expanduser() if cwd is not None else Path.cwd()
    try:
        resolved = resolve_run_argv(words, cwd=launch_root)
    except ToolRunUsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Detached runs skip the inline duration-class refusal: a join can finish
    # a `long` tool that an inline run could never fit.
    resolution = resolve_starter()
    if not resolution.resolved or resolution.starter is None:
        detail = _STARTER_FAILURE_DETAILS.get(
            resolution.reason or "", resolution.reason or "unknown reason"
        )
        print(
            "sase tool run -d: cannot identify the starting agent runner; "
            f"nothing was started ({detail})",
            file=sys.stderr,
        )
        return 1
    starter = resolution.starter

    if request.keep_going:
        continuation_mode: str | None = "always"
    elif request.fail_fast:
        continuation_mode = "never"
    else:
        continuation_mode = None

    from sase.tool.handoff_launch import describe_handoff_command, submit_handoff_run

    submitted = submit_handoff_run(
        resolved,
        launch_root=launch_root,
        agent=str(starter.get("agent") or ""),
        starter=starter,
        continuation_mode=continuation_mode,
        detached=True,
    )
    reservation = submitted.reservation
    proc_id = submitted.proc_id
    if not reservation.reserved:
        reason = reservation.error or "reservation failed"
        foreground = f"sase tool run {quoted}".strip()
        print(
            f"sase tool run -d: nothing was started ({reason}); try {foreground}",
            file=sys.stderr,
        )
        return 1

    run_id = reservation.run_id
    _, _, tool_display = describe_handoff_command(resolved)

    if submitted.submit_error is not None:
        print(
            f"sase tool run -d: could not start proc for {run_id} "
            f"({submitted.submit_error}); "
            "command was not run",
            file=sys.stderr,
        )
        return 1

    if request.quiet:
        print(run_id)
        return 0
    next_text = f"finish {tool_display} (detached run)"
    print(f"sase tool run {run_id}")
    print(f"tool: {tool_display}")
    print(f"proc: {proc_id}")
    print("the run may still be starting")
    print(f"monitor with: sase tool show {run_id} -F")
    print(f"wait with: sase tool wait {run_id}")
    print(f"stop with: sase tool stop {run_id}")
    print(f"proc log with: sase proc show {proc_id} --follow")
    print("detached: stopped when this agent's turn ends unless a monitor joins it")
    print(
        "join with: "
        f"sase monitor start -J {run_id} -p verify -n {shlex.quote(next_text)}"
    )
    return 0


__all__ = [
    "enclosing_owner",
    "escalation_enabled",
    "execute_detached",
    "parent_run",
]
