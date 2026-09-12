"""Shared helpers for ``sase monitor`` command handlers."""

from __future__ import annotations

import argparse
from pathlib import Path

from sase.monitor import (
    MonitorLaneError,
    MonitorRecord,
    MonitorRefError,
    active_monitor_for_lane,
    caller_artifacts_dir,
    default_caller,
    durable_lane_for_record,
    list_monitors,
    resolve_caller_agent,
    resolve_lane,
    resolve_monitor_ref,
)


def resolve_ref(raw_ref: str) -> MonitorRecord:
    records = list_monitors(project=None)
    return resolve_monitor_ref(raw_ref, records)


def resolve_ref_or_active(raw_ref: str | None) -> MonitorRecord:
    if raw_ref:
        return resolve_ref(raw_ref)
    caller = default_caller()
    if not caller:
        raise MonitorRefError(
            "no monitor id given and SASE_AGENT_NAME is unset; pass an explicit id"
        )
    project_name = infer_project_name(str(Path.cwd()))
    if not project_name:
        raise MonitorRefError(f"agent {caller!r} has no active monitor")
    try:
        ctx = resolve_caller_agent(
            project_name, caller, artifacts_dir=caller_artifacts_dir()
        )
    except MonitorLaneError as exc:
        raise MonitorRefError(str(exc)) from exc
    lane = durable_lane_for_record(ctx.record, fallback=caller)
    active = active_monitor_for_lane(project_name, lane)
    if active is None:
        raise MonitorRefError(f"agent {lane!r} has no active monitor")
    return MonitorRecord.from_record(active)


def resolve_cwd(explicit_cwd: str | None, agent: str, *, exact: bool) -> Path:
    if explicit_cwd:
        return Path(explicit_cwd).expanduser().resolve(strict=False)
    workspace = _agent_workspace_dir(agent, exact=exact)
    if workspace is not None:
        return workspace
    return Path.cwd()


def _agent_workspace_dir(agent: str, *, exact: bool) -> Path | None:
    guess_project = infer_project_name(str(Path.cwd()))
    if not guess_project:
        return None
    try:
        ctx = (
            resolve_caller_agent(
                guess_project, agent, artifacts_dir=caller_artifacts_dir()
            )
            if exact
            else resolve_lane(guess_project, agent)
        )
    except MonitorLaneError:
        return None
    meta = ctx.record.agent_meta
    if meta is None or not meta.workspace_dir:
        return None
    return Path(meta.workspace_dir).expanduser()


def infer_project_name(cwd: str) -> str | None:
    from sase.bead.project_name import infer_project_name_from_cwd

    return infer_project_name_from_cwd(cwd)


def optional_text(value: object) -> str | None:
    """Return a stripped string, or ``None`` when *value* is blank."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def start_command(args: argparse.Namespace) -> str:
    """Resolve the command remainder, falling back to the hidden `-c` alias."""
    words = [str(part) for part in (getattr(args, "monitor_command_words", None) or [])]
    if words and words[0] == "--":
        words = words[1:]
    remainder = " ".join(words).strip()
    if remainder:
        return remainder
    return (getattr(args, "monitor_command", None) or "").strip()


__all__ = [
    "infer_project_name",
    "optional_text",
    "resolve_cwd",
    "resolve_ref",
    "resolve_ref_or_active",
    "start_command",
]
