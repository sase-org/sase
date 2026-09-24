"""Fail-closed ``sase tool run -H`` over a plain durable proc."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from sase.tool.argv import ToolRunUsageError, resolve_run_argv
from sase.tool.executor import ToolRunCliRequest


def execute_handoff(request: ToolRunCliRequest) -> int:
    """Reserve a hand-off run and submit its adopting proc."""

    from sase.feature_flags import FeatureFlag, current_flags

    if not current_flags().enabled(FeatureFlag.tool_handoff):
        print(
            "sase tool run -H requires the tool_handoff flag "
            "(sase flag enable tool_handoff)",
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
    monitor_form = (
        "sase monitor start -p verify --reason 'hand off tool run' "
        f"-- sase tool run {quoted}".strip()
    )
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

    try:
        resolved = resolve_run_argv(words, cwd=Path.cwd())
    except ToolRunUsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2

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
    reservation = reserve_handoff_run(resolved, owner_kind="proc", owner_id=proc_id)
    if not reservation.reserved:
        reason = reservation.error or "reservation failed"
        foreground = f"sase tool run {quoted}".strip()
        print(
            f"sase tool run -H: nothing was started ({reason}); try {foreground}",
            file=sys.stderr,
        )
        return 1

    run_id = reservation.run_id
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

    from sase.procs import submit_proc_request
    from sase.procs.request import ProcSubmitRequest
    from sase.procs import infer_proc_attribution
    from sase.sessions import SessionRefError, resolve_session_ref

    cwd = Path.cwd()
    project, workspace_num = infer_proc_attribution(cwd, None)
    try:
        identity = resolve_session_ref(None)
        session_id = identity.session_id if identity is not None else None
    except SessionRefError:
        session_id = None

    try:
        submit_proc_request(
            ProcSubmitRequest(
                argv=worker_argv(run_id),
                command=command,
                label=label,
                cwd=cwd,
                origin="tool-run",
                proc_id=proc_id,
                project=project,
                workspace_num=workspace_num,
                session_id=session_id,
                tags=owner_tags(run_id),
                env=worker_env_overlay(),
                request_fingerprint=owner_request_fingerprint(run_id),
                followup={"kind": "tool-run", "run_id": run_id},
            )
        )
    except Exception as exc:  # noqa: BLE001 - submit failure settles launch_failed.
        settle_launch_failure(run_id, str(exc))
        print(
            f"sase tool run -H: could not start proc for {run_id} ({exc}); "
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


__all__ = ["execute_handoff"]
