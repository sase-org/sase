"""Shared hand-off launch module for ``-H`` and monitor starts."""

from __future__ import annotations

import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.tool_run import tool_run_begin
from sase.tool.argv import ResolvedToolArgv
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


def envelope_from_resolved(resolved: ResolvedToolArgv) -> dict[str, Any]:
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
    resolved: ResolvedToolArgv, *, owner_kind: str, owner_id: str
) -> HandoffReservation:
    """Reserve a ``created`` hand-off run; never raises."""

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
    request["commit_running"] = False
    request["launch_mode"] = "handoff"
    request["launch"] = envelope_from_resolved(resolved)
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
    return HandoffReservation(
        run_id=run_id,
        owner_kind=owner_kind,
        owner_id=owner_id,
        events_path=events_path,
    )


def worker_argv(run_id: str) -> list[str]:
    """Return the durable worker argv that claims and runs *run_id*."""

    return [sys.executable, "-m", "sase", "tool", "_adopt", run_id]


def worker_env_overlay() -> dict[str, str]:
    """Clear inherited parent-run markers inside the owner env."""

    return {"SASE_TOOL_RUN_ID": "", "SASE_TOOL_RUN_EVENTS": ""}


def owner_tags(run_id: str) -> list[str]:
    """Return the proc tags linking one ToolRun to its owner proc."""

    return ["tool-run", f"tool-run:{run_id}"]


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
    "envelope_from_resolved",
    "owner_request_fingerprint",
    "owner_tags",
    "reserve_handoff_run",
    "resolved_from_envelope",
    "settle_launch_failure",
    "worker_argv",
    "worker_env_overlay",
]
