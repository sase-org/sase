#!/usr/bin/env python3
"""Reconcile bead claims for live and dead pre-launch agents."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.bead.claims import BEAD_CLAIM_MARKER, write_bead_claim_marker
from sase.bead.model import Issue, Status
from sase.bead.store_locator import open_bead_project_for_beads_dir
from sase.bead.sync import (
    bead_store_write_lock,
    commit_bead_claim_reconciliation,
    publish_bead_claim,
    refresh_bead_store,
)
from sase.bead.work_liveness import AGENT_BEAD_SCAN_OPTIONS as _SCAN_OPTIONS
from sase.bead.work_liveness import agent_record_is_alive
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopLogger, ChopResultBuilder
from sase.core import bead_read_facade as rust_beads
from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.paths import sase_projects_dir

#: Terminal marker written beside a dead owner's artifact record once its claim
#: has been reconciled. Without it the pre-pass would keep every dead record as
#: a release candidate forever and open bead stores on every tick.
BEAD_CLAIM_RECONCILED_MARKER = "bead_claim_reconciled.json"


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
    has_reconcile_tombstone: bool = False
    is_alive: bool = False


@dataclass(frozen=True)
class _ProjectClaimReconciliation:
    released: frozenset[tuple[str, str]]
    release_errors: frozenset[tuple[str, str]]
    held: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class _ProjectClaimTick:
    """One project's snapshot-plus-reconcile outcome for a single chop tick."""

    snapshot_ok: bool
    scanned: bool
    claimed_count: int
    reconciliation: _ProjectClaimReconciliation


_NO_RELEASE_ERRORS: frozenset[tuple[str, str]] = frozenset()


def _empty_reconciliation(
    release_errors: frozenset[tuple[str, str]] = _NO_RELEASE_ERRORS,
) -> _ProjectClaimReconciliation:
    return _ProjectClaimReconciliation(
        released=frozenset(),
        release_errors=release_errors,
        held=frozenset(),
    )


def _reconcile_project_claims(
    project_name: str,
    *,
    beads_dir: Path,
    operation_context: Any,
    releases: list[tuple[str, str]],
    acquisitions: list[tuple[str, str]],
    log: ChopLogger,
) -> _ProjectClaimReconciliation:
    """Apply one project's claim repairs under one lock and one commit."""
    released: set[tuple[str, str]] = set()
    release_errors: set[tuple[str, str]] = set()
    held: set[tuple[str, str]] = set()
    try:
        from sase.bead.background_store import schedule_beads_sidecar_convergence

        committed = False
        with bead_store_write_lock(beads_dir) as already_locked:
            changed = False
            with open_bead_project_for_beads_dir(beads_dir) as project:
                for bead_id, agent_name in releases:
                    try:
                        _issue, item_changed = project.release_agent_claim(
                            bead_id, agent_name
                        )
                    except Exception as exc:  # noqa: BLE001 - reconcile siblings.
                        release_errors.add((bead_id, agent_name))
                        log.warning(
                            f"[bead_claim_checks] Failed to release bead claim "
                            f"{bead_id} for {agent_name}: {exc}"
                        )
                        continue
                    if item_changed:
                        released.add((bead_id, agent_name))
                        changed = True

                for bead_id, agent_name in acquisitions:
                    try:
                        issue, item_changed = project.claim_for_agent_wait(
                            bead_id, agent_name
                        )
                    except Exception as exc:  # noqa: BLE001 - reconcile siblings.
                        log.warning(
                            f"[bead_claim_checks] Failed to acquire bead claim "
                            f"{bead_id} for {agent_name}: {exc}"
                        )
                        continue
                    if (
                        issue.status in {Status.CLAIMED, Status.IN_PROGRESS}
                        and issue.assignee == agent_name
                    ):
                        held.add((bead_id, agent_name))
                    changed |= item_changed

            if changed:
                committed = commit_bead_claim_reconciliation(
                    beads_dir,
                    already_locked=already_locked,
                    mutation_origin="machine",
                    operation_context=operation_context,
                )
        if committed:
            publish_bead_claim(beads_dir, "reconciliation", project_name)
            schedule_beads_sidecar_convergence(project_name)
    except Exception as exc:  # noqa: BLE001 - one project must not stop the chop.
        log.warning(
            f"[bead_claim_checks] Failed to reconcile bead claims for "
            f"{project_name}: {exc}"
        )
        release_errors.update(releases)
        return _empty_reconciliation(frozenset(release_errors))

    return _ProjectClaimReconciliation(
        released=frozenset(released),
        release_errors=frozenset(release_errors),
        held=frozenset(held),
    )


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
                has_reconcile_tombstone=(
                    artifact_dir / BEAD_CLAIM_RECONCILED_MARKER
                ).exists(),
                is_alive=agent_record_is_alive(record),
            )
        )
    return claims


def _write_reconcile_tombstone(record: _ClaimArtifact, log: ChopLogger) -> bool:
    """Mark a dead owner's record terminal so later ticks skip it entirely."""
    path = record.artifact_dir / BEAD_CLAIM_RECONCILED_MARKER
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = {
        "bead_id": record.bead_id,
        "agent_name": record.agent_name,
        "project_name": record.project_name,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.write("\n")
        tmp_path.replace(path)
    except OSError as exc:
        log.warning(
            f"[bead_claim_checks] Failed to write claim reconciliation "
            f"tombstone {path}: {exc}"
        )
        return False
    return True


def _claim_owner_is_alive(record: _ClaimArtifact) -> bool:
    return record.is_alive


def _read_claimed_issues(beads_dir: Path) -> list[Issue] | None:
    """List CLAIMED issues from an already-refreshed leased store.

    Tombstones treat an empty snapshot as proof there is nothing left to
    release. That is only safe after integrating the same remote the
    writers publish to; the canonical primary sidecar may still be stale
    until auto-sync consumes the post-publication hint.
    """
    return rust_beads.list_issues(beads_dir, statuses=[Status.CLAIMED])


def _release_targets_from_snapshot(
    project_name: str,
    issues: list[Issue],
    authoritative: dict[tuple[str, str], _ClaimArtifact],
) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for issue in issues:
        owner = authoritative.get((project_name, issue.assignee))
        if (
            owner is None
            or owner.bead_id != issue.id
            or owner.bead_claim_promoted is not False
            or _claim_owner_is_alive(owner)
        ):
            continue
        targets.append((issue.id, issue.assignee))
    return targets


def _process_project_claims(
    project_name: str,
    *,
    need_claimed_snapshot: bool,
    acquisitions: list[tuple[str, str]],
    projects_root: Path,
    log: ChopLogger,
) -> _ProjectClaimTick:
    """Refresh, snapshot, and reconcile one project under one operational lease.

    Periodic claim-check work must not churn leases: the authoritative
    CLAIMED snapshot and the repair batch share one
    ``writable_bead_store_for_machine`` block, one refresh, one write lock,
    and at most one publication.
    """
    snapshot_ok = False
    scanned = False
    claimed_count = 0
    snapshot_complete = not need_claimed_snapshot
    releases: list[tuple[str, str]] = []
    reconciliation = _empty_reconciliation()

    try:
        from sase.bead.background_store import writable_bead_store_for_machine

        with writable_bead_store_for_machine(
            project_name,
            workflow="chop:bead_claim_checks",
            holder=f"bead_claim_checks:{project_name}",
        ) as store:
            beads_dir = store.beads_dir
            try:
                refresh_bead_store(beads_dir)
            except Exception as exc:  # noqa: BLE001 - use the leased snapshot anyway.
                log.warning(
                    f"[bead_claim_checks] Failed to refresh writable bead store "
                    f"for {project_name}: {exc}"
                )

            if need_claimed_snapshot:
                try:
                    issues = _read_claimed_issues(beads_dir)
                except Exception as exc:  # noqa: BLE001 - still try acquisitions.
                    log.warning(
                        f"[bead_claim_checks] Failed to read bead store for "
                        f"{project_name}: {exc}"
                    )
                    snapshot_complete = True
                else:
                    snapshot_ok = True
                    if issues is not None:
                        scanned = True
                        claimed_count = len(issues)
                        # Ordering invariant: collect the authoritative bead
                        # snapshot before re-scanning artifacts. Agent metadata
                        # is written before the claim event, so this order
                        # cannot mistake a fresh live claim for an ownerless one.
                        authoritative = _latest_owner_records(
                            _scan_claim_artifacts(projects_root)
                        )
                        releases = _release_targets_from_snapshot(
                            project_name, issues, authoritative
                        )
                    snapshot_complete = True

            if releases or acquisitions:
                reconciliation = _reconcile_project_claims(
                    project_name,
                    beads_dir=beads_dir,
                    operation_context=store.context,
                    releases=releases,
                    acquisitions=acquisitions,
                    log=log,
                )
    except Exception as exc:  # noqa: BLE001 - one project must not stop the chop.
        if need_claimed_snapshot and not snapshot_complete:
            log.warning(
                f"[bead_claim_checks] Failed to read bead store for "
                f"{project_name}: {exc}"
            )
            return _ProjectClaimTick(
                snapshot_ok=False,
                scanned=False,
                claimed_count=0,
                reconciliation=_empty_reconciliation(),
            )
        log.warning(
            f"[bead_claim_checks] Failed to reconcile bead claims for "
            f"{project_name}: {exc}"
        )
        return _ProjectClaimTick(
            snapshot_ok=snapshot_ok,
            scanned=scanned,
            claimed_count=claimed_count,
            reconciliation=_empty_reconciliation(frozenset(releases)),
        )

    return _ProjectClaimTick(
        snapshot_ok=snapshot_ok,
        scanned=scanned,
        claimed_count=claimed_count,
        reconciliation=reconciliation,
    )


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
        if record.bead_claim_promoted is not False or record.has_reconcile_tombstone:
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

    release_projects = {record.project_name for record in release_candidates}
    acquisitions_by_project: dict[str, list[tuple[str, str]]] = {}
    acquisition_records: dict[tuple[str, str, str], _ClaimArtifact] = {}
    for record in acquire_candidates:
        acquisitions_by_project.setdefault(record.project_name, []).append(
            (record.bead_id, record.agent_name)
        )
        acquisition_records[
            (record.project_name, record.bead_id, record.agent_name)
        ] = record

    examined = len(acquire_candidates)
    released = 0
    acquired = 0
    release_errors: set[tuple[str, str]] = set()
    # Projects whose authoritative read succeeded; only their release candidates
    # can be declared terminal below.
    read_projects: set[str] = set()
    scanned_projects: set[str] = set(acquisitions_by_project)
    for project_name in sorted(release_projects.union(acquisitions_by_project)):
        tick = _process_project_claims(
            project_name,
            need_claimed_snapshot=project_name in release_projects,
            acquisitions=acquisitions_by_project.get(project_name, []),
            projects_root=projects_root,
            log=runtime.log,
        )
        if tick.snapshot_ok:
            read_projects.add(project_name)
        if tick.scanned:
            scanned_projects.add(project_name)
            examined += tick.claimed_count
        released += len(tick.reconciliation.released)
        release_errors.update(
            (project_name, agent_name)
            for _bead_id, agent_name in tick.reconciliation.release_errors
        )
        acquired += len(tick.reconciliation.held)
        for bead_id, agent_name in tick.reconciliation.held:
            record = acquisition_records[(project_name, bead_id, agent_name)]
            write_bead_claim_marker(
                record.artifact_dir,
                project_name=project_name,
                bead_id=bead_id,
                agent_name=agent_name,
            )

    # A dead owner whose project was read without error is reconciled for good:
    # either its claim was released, or the store proved there was nothing left
    # to release. Tombstone it so the pre-pass returns to zero store reads.
    for record in release_candidates:
        if record.project_name not in read_projects:
            continue
        if (record.project_name, record.agent_name) in release_errors:
            continue
        _write_reconcile_tombstone(record, runtime.log)

    reason = None if released or acquired else "no_claims_reconciled"
    return runtime.emit_summary(
        {
            "projects_scanned": len(scanned_projects),
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
