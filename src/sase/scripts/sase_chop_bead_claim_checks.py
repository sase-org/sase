#!/usr/bin/env python3
"""Reconcile bead claims for live and dead pre-launch agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.names import is_process_alive
from sase.bead.claims import (
    BEAD_CLAIM_MARKER,
    claim_bead_for_waiting_agent,
    release_bead_claim_for_agent,
    write_bead_claim_marker,
)
from sase.bead.model import Issue, Status
from sase.bead.store_locator import canonical_beads_dir_for_project
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core import bead_read_facade as rust_beads
from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
from sase.core.paths import sase_projects_dir

_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    only_workflow_dirs=("ace-run",),
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    include_done_markers=False,
    include_workflow_state=False,
    include_waiting=False,
)


@dataclass(frozen=True)
class _ClaimArtifact:
    project_name: str
    agent_name: str
    artifact_dir: Path
    timestamp: str
    pid: int | None
    stopped_at: str | None
    bead_id: str
    bead_claim_promoted: bool | None
    has_bead_claim_marker: bool


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _scan_claim_artifacts(projects_root: Path) -> list[_ClaimArtifact]:
    """Return claim-bearing agent records from the shared artifact scanner."""
    snapshot = scan_agent_artifacts(projects_root, _SCAN_OPTIONS)
    claims: list[_ClaimArtifact] = []
    for record in snapshot.records:
        meta = record.agent_meta
        if (
            record.workflow_dir_name != "ace-run"
            or meta is None
            or not meta.name
            or not meta.bead_id
        ):
            continue

        artifact_dir = Path(record.artifact_dir)
        raw_meta = _read_json_dict(artifact_dir / "agent_meta.json")
        promoted: bool | None
        if raw_meta is None:
            # An unreadable marker cannot prove that the claim was never promoted.
            promoted = None
        else:
            promoted = raw_meta.get("bead_claim_promoted") is True

        claims.append(
            _ClaimArtifact(
                project_name=record.project_name,
                agent_name=meta.name,
                artifact_dir=artifact_dir,
                timestamp=record.timestamp,
                pid=meta.pid,
                stopped_at=meta.stopped_at,
                bead_id=meta.bead_id,
                bead_claim_promoted=promoted,
                has_bead_claim_marker=(artifact_dir / BEAD_CLAIM_MARKER).exists(),
            )
        )
    return claims


def _claim_owner_is_alive(record: _ClaimArtifact) -> bool:
    meta: dict[str, object] = {}
    if record.pid is not None:
        meta["pid"] = record.pid
    if record.stopped_at is not None:
        meta["stopped_at"] = record.stopped_at
    return is_process_alive(meta, record.artifact_dir)


def _read_claimed_issues(project_name: str) -> list[Issue] | None:
    beads_dir = canonical_beads_dir_for_project(project_name)
    if beads_dir is None:
        return None
    return rust_beads.list_issues(beads_dir, statuses=[Status.CLAIMED])


def _latest_owner_records(
    records: list[_ClaimArtifact],
) -> dict[tuple[str, str], _ClaimArtifact]:
    latest: dict[tuple[str, str], _ClaimArtifact] = {}
    for record in records:
        key = (record.project_name, record.agent_name)
        previous = latest.get(key)
        if previous is None or record.timestamp > previous.timestamp:
            latest[key] = record
    return latest


@builtin_chop("bead_claim_checks")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    projects_root = sase_projects_dir()

    # Cheap pre-pass: do not touch bead stores unless an unpromoted record is
    # either a dead claim owner or a live agent that still lacks a claim marker.
    prepass = _latest_owner_records(_scan_claim_artifacts(projects_root))
    release_candidates: list[_ClaimArtifact] = []
    acquire_candidates: list[_ClaimArtifact] = []
    for record in prepass.values():
        if record.bead_claim_promoted is not False:
            continue
        if _claim_owner_is_alive(record):
            if not record.has_bead_claim_marker:
                acquire_candidates.append(record)
        else:
            release_candidates.append(record)

    if not release_candidates and not acquire_candidates:
        return runtime.emit_summary(
            {
                "projects_scanned": 0,
                "claims_examined": 0,
                "claims_released": 0,
                "claims_acquired": 0,
            },
            reason="no_claim_reconciliation_candidates",
        )

    # Ordering invariant: collect the authoritative bead snapshot before
    # re-scanning artifacts. Agent metadata is written before the claim event,
    # so this order cannot mistake a fresh live claim for an ownerless one.
    candidate_projects = {record.project_name for record in release_candidates}
    claimed_by_project: dict[str, list[Issue]] = {}
    for project_name in sorted(candidate_projects):
        try:
            issues = _read_claimed_issues(project_name)
        except Exception as exc:  # noqa: BLE001 - one bad store must not stop the chop.
            runtime.log.warning(
                f"[bead_claim_checks] Failed to read bead store for "
                f"{project_name}: {exc}"
            )
            continue
        if issues is not None:
            claimed_by_project[project_name] = issues

    examined = 0
    released = 0
    if claimed_by_project:
        authoritative = _latest_owner_records(_scan_claim_artifacts(projects_root))
        for project_name, issues in claimed_by_project.items():
            for issue in issues:
                examined += 1
                owner = authoritative.get((project_name, issue.assignee))
                if (
                    owner is None
                    or owner.bead_id != issue.id
                    or owner.bead_claim_promoted is not False
                    or _claim_owner_is_alive(owner)
                ):
                    continue
                if release_bead_claim_for_agent(
                    project_name=project_name,
                    bead_id=issue.id,
                    agent_name=issue.assignee,
                ):
                    released += 1

    acquired = 0
    acquisition_projects: set[str] = set()
    for record in acquire_candidates:
        examined += 1
        acquisition_projects.add(record.project_name)
        try:
            held = claim_bead_for_waiting_agent(
                project_name=record.project_name,
                bead_id=record.bead_id,
                agent_name=record.agent_name,
            )
        except Exception as exc:  # noqa: BLE001 - one agent must not stop the chop.
            runtime.log.warning(
                f"[bead_claim_checks] Failed to acquire bead claim for "
                f"{record.agent_name}: {exc}"
            )
            continue
        if not held:
            continue
        acquired += 1
        write_bead_claim_marker(
            record.artifact_dir,
            project_name=record.project_name,
            bead_id=record.bead_id,
            agent_name=record.agent_name,
        )

    reason = None if released or acquired else "no_claims_reconciled"
    return runtime.emit_summary(
        {
            "projects_scanned": len(
                set(claimed_by_project).union(acquisition_projects)
            ),
            "claims_examined": examined,
            "claims_released": released,
            "claims_acquired": acquired,
        },
        reason=reason,
    )


def main() -> None:
    run_builtin_chop("bead_claim_checks")


if __name__ == "__main__":
    main()
