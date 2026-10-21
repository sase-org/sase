"""Requested-hood filtering for project inventory construction."""

from __future__ import annotations

from collections.abc import Mapping, Set as AbstractSet
import json
from pathlib import Path
from typing import Any

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.inventory_history import HistoricalAssociations
from sase.agents_sync.inventory_io import (
    canonical_local_name,
    text as _text,
)
from sase.agents_sync.inventory_models import ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.agents_sync.v2_io import MAX_JSON_BYTES
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    agent_name_in_hood,
)
from sase.core.agent_scan_wire import AgentArtifactRecordWire

UNRELATED_CLASSIFY_LIMIT = 8


def empty_project_hood_inventory(
    owner: AgentOwnerIdentity,
    target: ProjectTarget,
) -> ProjectHoodInventory:
    """Return an inventory that performs no hydration or Git lookups."""

    return ProjectHoodInventory(
        owner=owner,
        project_key=target.project_key,
        runs=(),
        primary_repo_name=target.primary_repo_name,
    )


def _local_name_in_requested_hoods(
    local_name: str,
    requested_hoods: AbstractSet[str],
    identity: AgentIdentitySnapshot,
) -> bool:
    """Return whether *local_name* belongs to any requested hood."""

    for hood in requested_hoods:
        try:
            if agent_name_in_hood(local_name, hood, identity):
                return True
        except PublicationDrainTimedOut:
            raise
        except Exception:
            continue
    return False


def _raw_name_in_requested_hoods(
    raw_name: str,
    requested_hoods: AbstractSet[str],
    identity: AgentIdentitySnapshot,
) -> bool | None:
    """Classify a raw identity string against *requested_hoods*.

    ``None`` means the name could not be normalized, so membership is unknown.
    """

    try:
        local_name = canonical_local_name(raw_name, identity)
    except PublicationDrainTimedOut:
        raise
    except (AgentsSyncFormatError, ValueError, RuntimeError, TypeError):
        return None
    return _local_name_in_requested_hoods(local_name, requested_hoods, identity)


def filter_historical_associations(
    history: HistoricalAssociations,
    requested_hoods: AbstractSet[str],
    identity: AgentIdentitySnapshot,
) -> HistoricalAssociations:
    """Keep historical run and session lanes that belong to requested hoods."""

    run_commits = {
        name: commits
        for name, commits in history.run_commits.items()
        if _local_name_in_requested_hoods(name, requested_hoods, identity)
    }
    lane_commits = tuple(
        lane
        for lane in history.lane_commits
        if _local_name_in_requested_hoods(lane.local_name, requested_hoods, identity)
    )
    return HistoricalAssociations(run_commits, lane_commits)


def history_commits_by_sha(
    history: HistoricalAssociations,
) -> dict[str, CommitRecord]:
    """Index batched primary-history commits by lowercase SHA."""

    by_sha: dict[str, CommitRecord] = {}
    for commits in history.run_commits.values():
        for commit in commits:
            by_sha.setdefault(commit.sha, commit)
    for lane in history.lane_commits:
        for commit in lane.commits:
            by_sha.setdefault(commit.sha, commit)
    return by_sha


def indexed_record_in_requested_hoods(
    record: AgentArtifactRecordWire,
    requested_hoods: AbstractSet[str],
    identity: AgentIdentitySnapshot,
) -> bool | None:
    """Classify an indexed artifact using identity metadata only."""

    raw_name = _indexed_record_raw_name(record)
    if raw_name is None:
        return None
    return _raw_name_in_requested_hoods(raw_name, requested_hoods, identity)


def dismissed_payload_in_requested_hoods(
    raw: Mapping[str, Any],
    requested_hoods: AbstractSet[str],
    identity: AgentIdentitySnapshot,
) -> bool | None:
    """Classify a dismissed bundle payload using its identity fields."""

    raw_name = (
        _text(raw.get("agent_name"))
        or _text(raw.get("patch_name"))
        or _text(raw.get("cl_name"))
    )
    if raw_name is None:
        return None
    return _raw_name_in_requested_hoods(raw_name, requested_hoods, identity)


def dismissed_summary_in_requested_hoods(
    summary: object,
    requested_hoods: AbstractSet[str],
    identity: AgentIdentitySnapshot,
) -> bool | None:
    """Classify a dismissed-bundle summary before reading its JSON payload."""

    known: bool | None = False
    for attr in ("agent_name", "cl_name", "agent_session"):
        raw_name = getattr(summary, attr, None)
        if not isinstance(raw_name, str) or not raw_name:
            continue
        decision = _raw_name_in_requested_hoods(raw_name, requested_hoods, identity)
        if decision is True:
            return True
        if decision is None:
            known = None
    return known


def _indexed_record_raw_name(record: AgentArtifactRecordWire) -> str | None:
    """Return the cheapest available identity name for an indexed artifact."""

    if record.agent_meta is not None and record.agent_meta.name:
        return record.agent_meta.name
    if record.done is not None and record.done.name:
        return record.done.name
    artifact = Path(record.artifact_dir)
    for filename in ("agent_meta.json", "done.json"):
        payload = _soft_json_object(artifact / filename)
        if payload is None:
            continue
        name = _text(payload.get("name"))
        if name is not None:
            return name
    return None


def append_unclassified_diagnostic(
    diagnostics: list[str],
    source: str,
    unclassified_count: int,
) -> int:
    """Record a bounded diagnostic for a record whose hood is unknown."""

    if unclassified_count >= UNRELATED_CLASSIFY_LIMIT:
        return unclassified_count
    diagnostics.append(f"{source}: skipped unclassified record in scoped inventory")
    return unclassified_count + 1


def _soft_json_object(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except PublicationDrainTimedOut:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None
