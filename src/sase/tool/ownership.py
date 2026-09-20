"""Parent ToolRun and enclosing monitor/proc ownership for foreground runs."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from sase.core.tool_run import tool_run_show


_MONITOR_ENV = "SASE_MONITOR_ID"
_MONITOR_ARTIFACTS_ENV = "SASE_MONITOR_ARTIFACTS_DIR"
_PROC_ENV = "SASE_PROC_ID"
_PARENT_ENV = "SASE_TOOL_RUN_ID"


class ToolRunOwnerConflict(ValueError):
    """``-q`` was used while an enclosing owner controls presentation."""


@dataclass(frozen=True)
class ToolRunOwnership:
    """Resolved attribution and output-ownership for one invocation."""

    owner_kind: str | None
    owner_id: str | None
    parent_run_id: str | None
    other_owner_kind: str | None
    other_owner_id: str | None
    owns_output: bool
    enclosing_label: str | None


def resolve_ownership(*, quiet: bool) -> ToolRunOwnership:
    """Resolve monitor/proc/parent ownership without mutating those executors."""

    monitor_id = (os.environ.get(_MONITOR_ENV) or "").strip() or None
    proc_id = (os.environ.get(_PROC_ENV) or "").strip() or None
    # Agents launched by a monitored command (an epic launch) inherit that monitor's
    # id long after it settled. A settled owner captures nothing, so it must neither
    # own the output nor be recorded as the owner.
    if monitor_id and _monitor_has_settled():
        monitor_id = None
    if proc_id and _proc_has_settled(proc_id):
        proc_id = None
    parent_id = (os.environ.get(_PARENT_ENV) or "").strip() or None
    if parent_id and not _parent_exists(parent_id):
        parent_id = None

    owner_kind: str | None = None
    owner_id: str | None = None
    other_kind: str | None = None
    other_id: str | None = None
    if monitor_id:
        owner_kind = "monitor"
        owner_id = monitor_id
        if proc_id:
            other_kind = "proc"
            other_id = proc_id
    elif proc_id:
        owner_kind = "proc"
        owner_id = proc_id

    owns_output = parent_id is None and owner_kind is None
    enclosing: str | None = None
    if parent_id is not None:
        enclosing = f"parent tool run {parent_id}"
    elif owner_kind is not None and owner_id is not None:
        enclosing = f"{owner_kind} {owner_id}"
    if quiet and not owns_output:
        label = enclosing or "the enclosing owner"
        raise ToolRunOwnerConflict(
            f"-q/--quiet cannot be used; {label} controls presentation"
        )
    return ToolRunOwnership(
        owner_kind=owner_kind,
        owner_id=owner_id,
        parent_run_id=parent_id,
        other_owner_kind=other_kind,
        other_owner_id=other_id,
        owns_output=owns_output,
        enclosing_label=enclosing,
    )


def compact_requested(*, quiet: bool, verbose: bool, owns_output: bool) -> bool:
    """Return whether this invocation should use compact agent output."""

    if not owns_output:
        return False
    if verbose:
        return False
    if quiet:
        return True
    return bool((os.environ.get("SASE_AGENT_NAME") or "").strip())


def _monitor_has_settled() -> bool:
    """True only on proof: the monitor's artifacts dir carries its terminal marker."""

    root = (os.environ.get(_MONITOR_ARTIFACTS_ENV) or "").strip()
    if not root:
        return False
    try:
        return (Path(root) / "done.json").is_file()
    except OSError:
        return False


def _proc_has_settled(proc_id: str) -> bool:
    """True only when the proc store reports a terminal status; unknown is not proof."""

    try:
        from sase.procs.models import TERMINAL_PROC_STATUSES
        from sase.procs.store import get_proc

        proc = get_proc(proc_id)
    except Exception:  # noqa: BLE001 - unknown liveness never changes ownership.
        return False
    return proc is not None and proc.status in TERMINAL_PROC_STATUSES


def _parent_exists(run_id: str) -> bool:
    try:
        shown = tool_run_show(run_id)
    except Exception:  # noqa: BLE001 - missing parent must not block execution.
        return False
    run = shown.get("run")
    return isinstance(run, dict) and str(run.get("run_id") or "") == run_id


__all__ = [
    "ToolRunOwnerConflict",
    "ToolRunOwnership",
    "compact_requested",
    "resolve_ownership",
]
