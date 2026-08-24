"""Agent completion detection for chop action lifecycle finalization."""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.dismissed_agents import load_dismissed_bundle_summaries
from sase.ace.hooks.processes import is_process_running
from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path

from ._chop_lifecycle_types import _AgentCompletion

_SUCCESS_DONE_OUTCOMES = {
    "completed",
    "epic_approved",
    "noop",
    "plan_committed",
    "plan_rejected",
}


def _record_artifacts_dir(record: object) -> Path | None:
    project_name = str(getattr(record, "project_name", ""))
    timestamp = str(getattr(record, "artifacts_timestamp", ""))
    if not project_name or not timestamp:
        return None
    return resolve_agent_artifact_timestamp_path(
        project_name,
        "ace-run",
        timestamp,
    )


def _dismissed_bundle_completion(
    record: object,
    *,
    pid: int,
) -> _AgentCompletion | None:
    raw_suffix = str(getattr(record, "artifacts_timestamp", "") or "").strip()
    if not raw_suffix:
        return None

    summaries = load_dismissed_bundle_summaries(
        suffixes={raw_suffix},
        top_level_only=True,
        limit=None,
    )
    summary = next(
        (
            candidate
            for candidate in summaries
            if getattr(candidate, "raw_suffix", None) == raw_suffix
            and not bool(getattr(candidate, "is_workflow_child", False))
        ),
        None,
    )
    if summary is None:
        return None

    status = str(getattr(summary, "status", "") or "unknown").strip().upper()
    bundle_path = str(getattr(summary, "bundle_path", "") or "archive")
    return _AgentCompletion(
        terminal=True,
        succeeded=status == "DONE",
        detail=(
            f"agent pid {pid} dismissed bundle {bundle_path} reports status {status}"
        ),
    )


def _agent_completion(record: object) -> _AgentCompletion:
    pid = int(getattr(record, "pid", 0) or 0)
    artifacts_dir = _record_artifacts_dir(record)
    done_path = artifacts_dir / "done.json" if artifacts_dir is not None else None
    if done_path is not None and done_path.is_file():
        try:
            raw = json.loads(done_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _AgentCompletion(
                terminal=True,
                succeeded=False,
                detail=f"agent pid {pid} has unreadable done.json: {exc}",
            )
        if not isinstance(raw, dict):
            return _AgentCompletion(
                terminal=True,
                succeeded=False,
                detail=f"agent pid {pid} done.json is not an object",
            )
        outcome = str(raw.get("outcome") or "")
        if outcome in _SUCCESS_DONE_OUTCOMES or (
            outcome == "failed" and raw.get("retried_as_timestamp")
        ):
            return _AgentCompletion(
                terminal=True,
                succeeded=True,
                detail=f"agent pid {pid} finished with outcome {outcome}",
            )
        return _AgentCompletion(
            terminal=True,
            succeeded=False,
            detail=f"agent pid {pid} finished with outcome {outcome or 'unknown'}",
        )

    if pid > 0 and is_process_running(pid):
        return _AgentCompletion(
            terminal=False,
            succeeded=False,
            detail=f"agent pid {pid} is still running",
        )
    dismissed_completion = _dismissed_bundle_completion(record, pid=pid)
    if dismissed_completion is not None:
        return dismissed_completion
    location = str(done_path) if done_path is not None else "an unknown artifact path"
    return _AgentCompletion(
        terminal=True,
        succeeded=False,
        detail=f"agent pid {pid} exited without completion artifact {location}",
    )
