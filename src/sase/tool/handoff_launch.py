"""Fail-closed hand-off launches over a plain durable proc.

``execute_handoff`` is the ``sase tool run -H`` leg. ``submit_handoff_run``
is the shared proc-submission half used by ``-H``, ``-d/--detach``, and the
later automatic path: reservation plus owner submission, with presentation
left to the caller so ``-H`` output stays byte-identical.
"""

from __future__ import annotations

import os
import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.tool.argv import ResolvedToolArgv, ToolRunUsageError, resolve_run_argv
from sase.tool.executor import ToolRunCliRequest
from sase.tool.handoff import HandoffReservation
from sase.tool.routing import monitor_start_form


@dataclass(frozen=True)
class _HandoffSubmitResult:
    """Outcome of the shared reserve-and-submit half of a hand-off launch."""

    reservation: HandoffReservation
    proc_id: str
    submit_error: str | None = None


def describe_handoff_command(
    resolved: ResolvedToolArgv,
) -> tuple[str, list[str], str]:
    """Return ``(label, command, tool_display)`` for a resolved hand-off."""

    if resolved.tool_name:
        label = f"tool:{resolved.tool_name}"
        base_len = len(list(resolved.definition.get("argv") or ()))
        redacted_extra = list(resolved.display_argv[base_len:])
        command: list[str] = [
            "sase",
            "tool",
            "run",
            resolved.tool_name,
            *redacted_extra,
        ]
        tool_display = resolved.tool_name
    else:
        label = "tool:ad-hoc"
        command = ["sase", "tool", "run", "--", *list(resolved.display_argv)]
        tool_display = "ad-hoc"
    return label, command, tool_display


def submit_handoff_run(
    resolved: ResolvedToolArgv,
    *,
    launch_root: Path,
    agent: str | None = None,
    starter: Mapping[str, Any] | None = None,
    continuation_mode: str | None = None,
    detached: bool = False,
) -> _HandoffSubmitResult:
    """Reserve a hand-off run and submit its adopting proc; never raises."""

    from sase.procs import new_proc_id

    from sase.tool.handoff import (
        owner_request_fingerprint,
        owner_tags,
        reserve_handoff_run,
        settle_launch_failure,
        worker_argv,
        worker_env_overlay,
    )

    proc_id = new_proc_id()
    reservation = reserve_handoff_run(
        resolved,
        owner_kind="proc",
        owner_id=proc_id,
        agent=agent,
        starter=starter,
        continuation_mode=continuation_mode,
    )
    if not reservation.reserved:
        return _HandoffSubmitResult(reservation=reservation, proc_id=proc_id)
    run_id = reservation.run_id
    label, command, _ = describe_handoff_command(resolved)

    from sase.procs import submit_proc_request
    from sase.procs.request import ProcSubmitRequest
    from sase.procs import infer_proc_attribution
    from sase.sessions import own_live_session_id

    project, workspace_num = infer_proc_attribution(launch_root, None)
    try:
        session_id = own_live_session_id()
    except Exception:  # noqa: BLE001 - session stamping is fail-open.
        session_id = None

    try:
        submit_proc_request(
            ProcSubmitRequest(
                argv=worker_argv(run_id),
                command=command,
                label=label,
                cwd=launch_root,
                origin="tool-run",
                proc_id=proc_id,
                project=project,
                workspace_num=workspace_num,
                session_id=session_id,
                tags=owner_tags(run_id, detached=detached),
                env=worker_env_overlay(),
                request_fingerprint=owner_request_fingerprint(run_id),
                followup={"kind": "tool-run", "run_id": run_id},
            )
        )
    except Exception as exc:  # noqa: BLE001 - submit failure settles launch_failed.
        settle_launch_failure(run_id, str(exc))
        return _HandoffSubmitResult(
            reservation=reservation,
            proc_id=proc_id,
            submit_error=str(exc),
        )
    return _HandoffSubmitResult(reservation=reservation, proc_id=proc_id)


def execute_handoff(
    request: ToolRunCliRequest, *, cwd: Path | str | None = None
) -> int:
    """Reserve a hand-off run and submit its adopting proc.

    *cwd* overrides the process working directory for catalog resolution
    and proc attribution, so the TUI can hand off at a project's primary
    checkout root without mutating its own cwd or env.
    """

    if request.keep_going or request.fail_fast:
        print(
            "sase tool run -H cannot be used with -k/--keep-going or -x/--fail-fast",
            file=sys.stderr,
        )
        return 2
    if request.verbose:
        print(
            "sase tool run -H cannot be used with -v/--verbose",
            file=sys.stderr,
        )
        return 2
    if request.tail_lines_explicit:
        print(
            "sase tool run -H cannot be used with -T/--tail-lines",
            file=sys.stderr,
        )
        return 2

    words = tuple(request.words)
    quoted = " ".join(shlex.quote(part) for part in words)
    monitor_form = monitor_start_form(words, reason="hand off tool run")
    if os.environ.get("SASE_AGENT"):
        print(monitor_form, file=sys.stderr)
        return 2

    from sase.tool.ownership import resolve_ownership

    try:
        ownership = resolve_ownership(quiet=False)
    except Exception as exc:  # noqa: BLE001 - refusal must not reserve.
        print(str(exc), file=sys.stderr)
        return 2
    if ownership.owner_kind is not None and ownership.owner_id is not None:
        if ownership.owner_kind == "proc":
            try:
                from sase.procs.store import get_proc

                proc = get_proc(ownership.owner_id)
            except Exception:  # noqa: BLE001 - unknown owner is still an owner.
                proc = None
            if proc is not None and proc.origin == "ace":
                print(
                    f"sase tool run -H cannot be used inside proc "
                    f"{ownership.owner_id}: it is already a detached proc "
                    "(TUI ! command); drop -H and run in the foreground",
                    file=sys.stderr,
                )
                return 2
        print(
            f"sase tool run -H cannot be used inside {ownership.owner_kind} "
            f"{ownership.owner_id}; {monitor_form}",
            file=sys.stderr,
        )
        return 2

    launch_root = Path(cwd).expanduser() if cwd is not None else Path.cwd()
    try:
        resolved = resolve_run_argv(words, cwd=launch_root)
    except ToolRunUsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    submitted = submit_handoff_run(resolved, launch_root=launch_root)
    reservation = submitted.reservation
    proc_id = submitted.proc_id
    if not reservation.reserved:
        reason = reservation.error or "reservation failed"
        foreground = f"sase tool run {quoted}".strip()
        print(
            f"sase tool run -H: nothing was started ({reason}); try {foreground}",
            file=sys.stderr,
        )
        return 1

    run_id = reservation.run_id
    _, _, tool_display = describe_handoff_command(resolved)

    if submitted.submit_error is not None:
        print(
            f"sase tool run -H: could not start proc for {run_id} "
            f"({submitted.submit_error}); "
            "command was not run",
            file=sys.stderr,
        )
        return 1

    if request.quiet:
        print(run_id)
        return 0
    print(f"sase tool run {run_id}")
    print(f"tool: {tool_display}")
    print(f"proc: {proc_id}")
    print("the run may still be starting")
    print(f"monitor with: sase tool show {run_id} -F")
    print(f"wait with: sase tool wait {run_id}")
    print(f"stop with: sase tool stop {run_id}")
    print(f"proc log with: sase proc show {proc_id} --follow")
    return 0


__all__ = [
    "describe_handoff_command",
    "execute_handoff",
    "submit_handoff_run",
]
