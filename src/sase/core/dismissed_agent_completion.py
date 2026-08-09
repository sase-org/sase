"""Exact dismissed-bundle fallback for terminal agent state.

The live artifact markers remain authoritative.  Callers use this module only
after ``done.json`` has disappeared, batching all candidate suffixes into one
indexed archive query and then matching the preserved record against the live
artifact identity.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

SUCCESS_OUTCOME = "completed"
WAIT_SUCCESS_OUTCOMES = frozenset(
    {"completed", "noop", "epic_approved", "plan_committed"}
)
FAILURE_OUTCOMES = frozenset({"failed", "killed", "stopped", "epic_launch_failed"})
IDENTITY_SUCCESS_OUTCOMES = WAIT_SUCCESS_OUTCOMES | frozenset({"plan_rejected"})
KNOWN_DONE_OUTCOMES = (
    WAIT_SUCCESS_OUTCOMES | FAILURE_OUTCOMES | frozenset({"plan_rejected"})
)

_STATUS_OUTCOMES = {
    "DONE": SUCCESS_OUTCOME,
    "FEEDBACK": SUCCESS_OUTCOME,
    "PLAN DONE": SUCCESS_OUTCOME,
    "TALE DONE": SUCCESS_OUTCOME,
    "EPIC APPROVED": "epic_approved",
    "EPIC CREATED": "epic_approved",
    "PLAN COMMITTED": "plan_committed",
}


@dataclass(frozen=True)
class ArchivedAgentCompletion:
    """One exact top-level dismissed record projected as terminal state."""

    artifact_dir: str
    raw_suffix: str
    project_name: str
    changespec_name: str
    agent_name: str
    status: str
    outcome: str
    bundle_path: str

    @property
    def is_resolved(self) -> bool:
        return self.outcome in WAIT_SUCCESS_OUTCOMES

    @property
    def is_done(self) -> bool:
        return self.outcome in WAIT_SUCCESS_OUTCOMES

    @property
    def is_identity_success(self) -> bool:
        return self.outcome in IDENTITY_SUCCESS_OUTCOMES

    @property
    def is_failed(self) -> bool:
        return self.outcome in FAILURE_OUTCOMES


@dataclass(frozen=True)
class _ArtifactArchiveIdentity:
    artifact_dir: str
    raw_suffix: str
    project_name: str
    changespec_name: str
    agent_name: str

    @property
    def match_key(self) -> tuple[str, str, str, str]:
        return (
            self.raw_suffix,
            self.project_name,
            self.changespec_name,
            self.agent_name,
        )


def load_archived_agent_completions(
    artifacts: Iterable[tuple[Path, Mapping[str, Any], str]],
) -> dict[str, ArchivedAgentCompletion]:
    """Return exact dismissed completions keyed by artifact-directory string.

    ``artifacts`` contains ``(artifact_dir, agent_meta, project_name)`` rows.
    Rows without the full project, ChangeSpec, and agent-name identity are
    intentionally ineligible: archive fallback must fail closed.
    """

    identities = tuple(
        identity
        for artifact_dir, meta, project_name in artifacts
        if (
            identity := _artifact_archive_identity(
                artifact_dir,
                meta,
                project_name,
            )
        )
        is not None
    )
    if not identities:
        return {}

    try:
        from sase.ace.dismissed_agents import load_dismissed_bundle_summaries

        summaries = load_dismissed_bundle_summaries(
            suffixes={identity.raw_suffix for identity in identities},
            top_level_only=True,
            limit=None,
        )
    except Exception:
        return {}

    identities_by_key: dict[
        tuple[str, str, str, str], list[_ArtifactArchiveIdentity]
    ] = {}
    for identity in identities:
        identities_by_key.setdefault(identity.match_key, []).append(identity)

    matches: dict[str, list[ArchivedAgentCompletion]] = {}
    for summary in summaries:
        status = getattr(summary, "status", None)
        outcome = _archived_outcome_from_status(status)
        if outcome is None:
            continue
        bundle_path_value = getattr(summary, "bundle_path", None)
        if not isinstance(bundle_path_value, str) or not bundle_path_value:
            continue
        bundle_path = Path(bundle_path_value)
        if not bundle_path.is_file():
            continue

        raw_suffix = getattr(summary, "raw_suffix", None)
        changespec_name = getattr(summary, "cl_name", None)
        agent_name = getattr(summary, "agent_name", None)
        project_name = _project_name_from_project_file(
            getattr(summary, "project_file", None)
        )
        if not isinstance(status, str) or not status:
            continue
        if not isinstance(raw_suffix, str) or not raw_suffix:
            continue
        if not isinstance(changespec_name, str) or not changespec_name:
            continue
        if not isinstance(agent_name, str) or not agent_name:
            continue
        if project_name is None:
            continue
        key = (raw_suffix, project_name, changespec_name, agent_name)
        for identity in identities_by_key.get(key, ()):
            matches.setdefault(identity.artifact_dir, []).append(
                ArchivedAgentCompletion(
                    artifact_dir=identity.artifact_dir,
                    raw_suffix=identity.raw_suffix,
                    project_name=identity.project_name,
                    changespec_name=identity.changespec_name,
                    agent_name=identity.agent_name,
                    status=status,
                    outcome=outcome,
                    bundle_path=str(bundle_path),
                )
            )

    # Multiple exact archive rows are ambiguous.  A stale or duplicated record
    # must never make a dependency look complete.
    return {
        artifact_dir: candidates[0]
        for artifact_dir, candidates in matches.items()
        if len(candidates) == 1
    }


def _archived_outcome_from_status(status: object) -> str | None:
    """Translate one dismissed display status into canonical marker outcome."""

    if not isinstance(status, str) or not status.strip():
        return None
    normalized = status.strip().upper()
    if outcome := _STATUS_OUTCOMES.get(normalized):
        return outcome
    if normalized == "PLAN REJECTED":
        return "plan_rejected"
    if normalized == "STOPPED":
        return "stopped"
    if normalized == "KILLED":
        return "killed"
    if normalized == "FAILED" or normalized.startswith("FAILED ("):
        return "failed"
    return None


def archived_response_path(completion: ArchivedAgentCompletion) -> str | None:
    """Read and validate the archived transcript path for *completion*.

    Summary rows contain terminal state but not ``response_path``.  Payload I/O
    is therefore deferred until a fork actually requests the transcript.
    """

    try:
        with open(completion.bundle_path, encoding="utf-8") as handle:
            data: Any = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not _payload_matches(completion, data):
        return None
    response_path = data.get("response_path")
    return response_path if isinstance(response_path, str) and response_path else None


def _artifact_archive_identity(
    artifact_dir: Path,
    meta: Mapping[str, Any],
    project_name: str,
) -> _ArtifactArchiveIdentity | None:
    if not project_name:
        return None
    changespec_name = meta.get("patch_name")
    if not isinstance(changespec_name, str) or not changespec_name:
        changespec_name = meta.get("changespec_name")
    if not isinstance(changespec_name, str) or not changespec_name:
        changespec_name = meta.get("cl_name")
    agent_name = meta.get("name")
    if not isinstance(changespec_name, str) or not changespec_name:
        return None
    if not isinstance(agent_name, str) or not agent_name:
        return None
    raw_suffix = artifact_dir.name
    if not raw_suffix:
        return None
    return _ArtifactArchiveIdentity(
        artifact_dir=str(artifact_dir),
        raw_suffix=raw_suffix,
        project_name=project_name,
        changespec_name=changespec_name,
        agent_name=agent_name,
    )


def _project_name_from_project_file(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return Path(value).expanduser().parent.name or None
    except (OSError, RuntimeError, ValueError):
        return None


def _payload_matches(
    completion: ArchivedAgentCompletion,
    data: Mapping[str, Any],
) -> bool:
    if data.get("revived_at"):
        return False
    if data.get("raw_suffix") != completion.raw_suffix:
        return False
    if (data.get("patch_name") or data.get("cl_name")) != completion.changespec_name:
        return False
    if data.get("agent_name") != completion.agent_name:
        return False
    if _project_name_from_project_file(data.get("project_file")) != (
        completion.project_name
    ):
        return False
    if bool(
        data.get("is_workflow_child")
        or data.get("parent_workflow")
        or data.get("parent_timestamp")
    ):
        return False
    return _archived_outcome_from_status(data.get("status")) == completion.outcome


__all__ = [
    "ArchivedAgentCompletion",
    "FAILURE_OUTCOMES",
    "IDENTITY_SUCCESS_OUTCOMES",
    "KNOWN_DONE_OUTCOMES",
    "SUCCESS_OUTCOME",
    "WAIT_SUCCESS_OUTCOMES",
    "archived_response_path",
    "load_archived_agent_completions",
]
