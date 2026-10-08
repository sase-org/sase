"""Shared hand-off launch module for ``-H`` and monitor starts."""

from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.tool_run import tool_run_begin
from sase.tool.argv import ResolvedToolArgv
from sase.tool.demand import demand_context as build_demand_context
from sase.tool.demand import record_run_demand
from sase.tool.executor_recording import build_begin_request, finish_tool_run
from sase.tool.logs import prepare_run_paths


@dataclass(frozen=True)
class HandoffReservation:
    """Result of reserving a ``created`` hand-off run."""

    run_id: str
    owner_kind: str
    owner_id: str
    events_path: Path | None
    error: str | None = None

    @property
    def reserved(self) -> bool:
        return self.error is None


def _envelope_from_resolved(resolved: ResolvedToolArgv) -> dict[str, Any]:
    """Freeze a resolved invocation into a private launch envelope."""

    return {
        "argv": list(resolved.argv),
        "cwd": resolved.cwd,
        "tool_name": resolved.tool_name,
        "extra_args": list(resolved.extra_args),
        "display_argv": list(resolved.display_argv),
        "private_argv": (
            list(resolved.private_argv) if resolved.private_argv is not None else None
        ),
        "definition": dict(resolved.definition),
        "digest": resolved.digest,
        "adhoc": resolved.adhoc,
    }


def resolved_from_envelope(envelope: dict[str, Any]) -> ResolvedToolArgv:
    """Rebuild the frozen invocation returned by a successful claim."""

    return ResolvedToolArgv(
        tool_name=envelope.get("tool_name"),
        argv=tuple(str(part) for part in envelope.get("argv") or ()),
        extra_args=tuple(str(part) for part in envelope.get("extra_args") or ()),
        display_argv=tuple(str(part) for part in envelope.get("display_argv") or ()),
        private_argv=(
            tuple(str(part) for part in envelope["private_argv"])
            if envelope.get("private_argv") is not None
            else None
        ),
        definition=dict(envelope.get("definition") or {}),
        digest=envelope.get("digest"),
        cwd=envelope.get("cwd"),
        adhoc=bool(envelope.get("adhoc", False)),
    )


def reserve_handoff_run(
    resolved: ResolvedToolArgv,
    *,
    owner_kind: str,
    owner_id: str,
    agent: str | None = None,
    starter: Mapping[str, Any] | None = None,
    continuation_mode: str | None = None,
) -> HandoffReservation:
    """Reserve a ``created`` hand-off run; never raises.

    *agent* overrides the environment-derived attribution, for a launcher
    that knows the durable agent name better than its own env does.
    *starter* scopes the run to its starting agent runner (detached runs);
    *continuation_mode* travels in the launch envelope for the worker.
    """

    run_id = secrets.token_hex(16)
    try:
        events_path, _, _ = prepare_run_paths(run_id, owns_output=False)
    except Exception as exc:  # noqa: BLE001 - reservation is fail-closed.
        return HandoffReservation(
            run_id=run_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            events_path=None,
            error=str(exc),
        )
    request = build_begin_request(
        run_id,
        resolved=resolved,
        owner_kind=owner_kind,
        owner_id=owner_id,
        parent_run_id=None,
        events_path=events_path,
        stdout_path=None,
        stderr_path=None,
    )
    if agent and agent.strip():
        request["agent"] = agent.strip()
    request["commit_running"] = False
    request["launch_mode"] = "handoff"
    envelope = _envelope_from_resolved(resolved)
    if continuation_mode in ("always", "never", "known"):
        envelope["continuation_mode"] = continuation_mode
    request["launch"] = envelope
    if starter is not None:
        request["starter"] = dict(starter)
    try:
        started = tool_run_begin(request)
    except Exception as exc:  # noqa: BLE001 - reservation is fail-closed.
        return HandoffReservation(
            run_id=run_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            events_path=events_path,
            error=str(exc),
        )
    run = started.get("run") if isinstance(started, dict) else None
    if not isinstance(run, dict) or str(run.get("state") or "") != "created":
        detail = ""
        try:
            diagnostics = (
                started.get("diagnostics") if isinstance(started, dict) else None
            )
            if diagnostics:
                detail = f": {diagnostics}"
        except Exception:  # noqa: BLE001 - error text is best effort.
            detail = ""
        return HandoffReservation(
            run_id=run_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            events_path=events_path,
            error=f"reservation did not create a run{detail}",
        )
    _record_reservation_demand(run_id, starter is not None)
    return HandoffReservation(
        run_id=run_id,
        owner_kind=owner_kind,
        owner_id=owner_id,
        events_path=events_path,
    )


def _record_reservation_demand(run_id: str, has_starter: bool) -> None:
    """Record the reserving side's provider and ceiling context; never raises.

    Ceilings ride along only for a starter-scoped (detached) reservation,
    which the caller's harness actually bounds; a plain hand-off reservation
    records the provider only. A failure never turns a reservation into a
    refusal.
    """

    try:
        context = build_demand_context(os.environ, include_ceilings=has_starter)
    except Exception:  # noqa: BLE001 - context capture is fail-open.
        context = None
    if context is not None:
        record_run_demand(run_id, context=context)


def worker_argv(run_id: str) -> list[str]:
    """Return the durable worker argv that claims and runs *run_id*."""

    return [sys.executable, "-m", "sase", "tool", "_adopt", run_id]


def worker_env_overlay() -> dict[str, str]:
    """Clear inherited parent-run markers inside the owner env."""

    return {"SASE_TOOL_RUN_ID": "", "SASE_TOOL_RUN_EVENTS": ""}


def owner_tags(run_id: str, *, detached: bool = False) -> list[str]:
    """Return the proc tags linking one ToolRun to its owner proc."""

    tags = ["tool-run", f"tool-run:{run_id}"]
    if detached:
        tags.append("tool-run-detached")
    return tags


TOOL_RUN_JOIN_TAG_PREFIX = "tool-run-join:"


def join_tags(run_id: str) -> list[str]:
    """Return the proc tags linking one ToolRun to its join monitor proc.

    The prefix is distinct so that ``tool-run:<id>`` keeps meaning
    "owner" everywhere tags are decoded.
    """

    return [f"{TOOL_RUN_JOIN_TAG_PREFIX}{run_id}"]


def owner_request_fingerprint(run_id: str) -> str:
    """Return the stable proc request fingerprint for one hand-off."""

    return f"tool-run:{run_id}"


def settle_launch_failure(run_id: str, message: str) -> bool:
    """Settle a reserved run whose owner could not start; never raises."""

    try:
        return finish_tool_run(
            run_id,
            state="failed",
            exit_code=None,
            duration_ms=0,
            terminal_cause="launch_failed",
            diagnostics=["command was not run", message],
        )
    except Exception:  # noqa: BLE001 - settlement is best effort.
        return False


__all__ = [
    "HandoffReservation",
    "TOOL_RUN_JOIN_TAG_PREFIX",
    "join_tags",
    "owner_request_fingerprint",
    "owner_tags",
    "reserve_handoff_run",
    "resolved_from_envelope",
    "settle_launch_failure",
    "worker_argv",
    "worker_env_overlay",
]
