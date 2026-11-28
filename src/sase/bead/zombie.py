"""Read-only zombie-plan report for one project.

Callers wrap this on the UI thread's behalf: failures log a warning and
return a failed report instead of raising into the CLI, ACE, or doctor.
Nothing here arms, claims, launches, closes, or reopens any bead: the
collector reads one complete project tree snapshot plus the same batched
agent/session facts the stranded-work collector uses, and the shared Rust
predicate classifies them.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from time import time
from typing import Any

from sase.bead._stranded_facts_beads import attach_declared_bead_action
from sase.bead._stranded_facts_members import member_facts
from sase.bead._stranded_facts_snapshot import session_record_cache
from sase.bead.store_locator import canonical_beads_dir_for_project
from sase.core.zombie_facade import (
    ZOMBIE_PLAN_WIRE_SCHEMA_VERSION,
    ZombieEvaluationReport,
    ZombieVerdict,
    evaluate_zombie_plans,
    tree_snapshot_binding,
)

_LOG = logging.getLogger(__name__)


class _ZombieCollectionError(RuntimeError):
    """A collection failure that must surface as a failed report, not a crash."""


@dataclass(frozen=True, slots=True)
class ZombieReport:
    """Predicate output plus titles and the collection timestamp.

    ``collection_failed`` is set when the collector could not build an
    evaluation input (unknown project, unreadable store, or a core that
    predates the zombie-plan bindings); callers must not treat that empty
    report as a successful scan. ``failure_reason`` names the cause so the
    CLI can report it explicitly.
    """

    report: ZombieEvaluationReport
    project: str
    titles: Mapping[str, str]
    generated_at: float
    collection_failed: bool = False
    failure_reason: str | None = None
    latest_owner_terminal_at: Mapping[str, float] = field(default_factory=dict)

    @property
    def zombie_rows(self) -> tuple[ZombieVerdict, ...]:
        """Return rows the shared predicate confirmed as zombies."""
        return tuple(row for row in self.report.rows if row.state == "zombie")

    @property
    def unknown_rows(self) -> tuple[ZombieVerdict, ...]:
        """Return rows with unavailable or malformed evidence."""
        return tuple(row for row in self.report.rows if row.state == "unknown")


def _collect_zombie_report_input(
    project: str,
    *,
    now: float | None = None,  # noqa: ARG001 - reserved for future grace input
) -> dict[str, Any]:
    """Build the shared-predicate evaluation input for *project*.

    Reads one complete project tree snapshot through the
    ``bead_zombie_plan_tree_snapshot`` binding and gathers per-plan
    session-member facts through the same indexed artifact reads the
    stranded-work collector uses. Raises :class:`RuntimeError` when the
    store cannot be read or the installed core predates the bindings.
    """
    del now
    beads_dir = canonical_beads_dir_for_project(project)
    if beads_dir is None:
        raise _ZombieCollectionError(
            f"unknown project {project!r}: no readable bead store"
        )
    binding = tree_snapshot_binding()
    if binding is None:
        raise _ZombieCollectionError(
            "unsupported core: the installed sase_core_rs predates the "
            "bead_zombie_plan_tree_snapshot binding; rebuild the dev install "
            "or upgrade sase-core-rs"
        )
    try:
        snapshot_raw = binding(str(beads_dir))
    except Exception as exc:
        raise _ZombieCollectionError(
            f"zombie-plan tree snapshot failed for project {project!r}: {exc}"
        ) from exc
    if not isinstance(snapshot_raw, Mapping):
        raise _ZombieCollectionError(
            f"zombie-plan tree snapshot for project {project!r} is not a mapping"
        )
    beads_raw = snapshot_raw.get("beads")
    beads = list(beads_raw) if isinstance(beads_raw, list) else []
    snapshot = {
        "schema_version": snapshot_raw.get(
            "schema_version", ZOMBIE_PLAN_WIRE_SCHEMA_VERSION
        ),
        "complete": snapshot_raw.get("complete", True),
        "unknown_reason": snapshot_raw.get("unknown_reason"),
        "beads": beads,
    }
    owners = _owner_facts(project, beads)
    return {
        "schema_version": ZOMBIE_PLAN_WIRE_SCHEMA_VERSION,
        "snapshot": snapshot,
        "owners": owners,
        "latest_owner_terminal_at": _latest_owner_terminal_at(owners),
        "titles": _titles_for_beads(beads),
    }


def load_zombie_report(project: str, *, now: float | None = None) -> ZombieReport:
    """Collect facts and evaluate them. Failures yield a failed report."""
    moment = float(now) if now is not None else time()
    failed = ZombieReport(
        report=ZombieEvaluationReport(),
        project=project,
        titles={},
        generated_at=moment,
        collection_failed=True,
    )
    try:
        payload = _collect_zombie_report_input(project)
    except Exception as exc:  # noqa: BLE001 - callers must never see collector errors.
        _LOG.warning(
            "zombie-plan collector failed for project %s; returning failed report",
            project,
            exc_info=True,
        )
        return ZombieReport(
            report=failed.report,
            project=project,
            titles={},
            generated_at=moment,
            collection_failed=True,
            failure_reason=str(exc),
            latest_owner_terminal_at={},
        )
    titles = payload.pop("titles", {})
    latest_owner_terminal_at = payload.pop("latest_owner_terminal_at", {})
    try:
        report = evaluate_zombie_plans(payload)
    except Exception as exc:  # noqa: BLE001 - callers must never see evaluator errors.
        _LOG.warning(
            "zombie-plan evaluation failed for project %s; returning failed report",
            project,
            exc_info=True,
        )
        return ZombieReport(
            report=ZombieEvaluationReport(),
            project=project,
            titles=titles if isinstance(titles, Mapping) else {},
            generated_at=moment,
            collection_failed=True,
            failure_reason=str(exc),
            latest_owner_terminal_at=latest_owner_terminal_at,
        )
    return ZombieReport(
        report=report,
        project=project,
        titles=titles if isinstance(titles, Mapping) else {},
        generated_at=moment,
        latest_owner_terminal_at=latest_owner_terminal_at,
    )


def _latest_owner_terminal_at(owners: list[dict[str, Any]]) -> dict[str, float]:
    """Return terminal timestamps already collected for the shared predicate."""

    latest: dict[str, float] = {}
    for owner in owners:
        plan_id = owner.get("plan_id")
        members = owner.get("members")
        if not isinstance(plan_id, str) or not isinstance(members, list):
            continue
        timestamps = [
            float(value)
            for member in members
            if isinstance(member, Mapping)
            for value in [member.get("ended_at")]
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if timestamps:
            latest[plan_id] = max(timestamps)
    return latest


def _titles_for_beads(beads: list[Any]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for bead in beads:
        if not isinstance(bead, Mapping):
            continue
        bead_id = bead.get("id")
        title = bead.get("title")
        if isinstance(bead_id, str) and bead_id and isinstance(title, str):
            titles.setdefault(bead_id, title)
    return titles


def _in_progress_plans(beads: list[Any]) -> list[Mapping[str, Any]]:
    plans: list[Mapping[str, Any]] = []
    for bead in beads:
        if not isinstance(bead, Mapping):
            continue
        if bead.get("issue_type") != "plan":
            continue
        if bead.get("status") != "in_progress":
            continue
        plan_id = bead.get("id")
        if isinstance(plan_id, str) and plan_id:
            plans.append(bead)
    return plans


def _owner_facts(project: str, beads: list[Any]) -> list[dict[str, Any]]:
    """Build one owner-facts entry per in-progress plan bead.

    Session records come from the same batched artifact-index reads the
    stranded-work collector uses, so the predicate sees identical liveness
    evidence in both reports.
    """
    plans = _in_progress_plans(beads)
    assignees = {
        str(bead["assignee"]).strip()
        for bead in plans
        if isinstance(bead.get("assignee"), str) and str(bead["assignee"]).strip()
    }
    sessions = session_record_cache(project, assignees)
    owners: list[dict[str, Any]] = []
    for bead in plans:
        assignee = bead.get("assignee")
        key = str(assignee).strip() if isinstance(assignee, str) else ""
        if not key:
            records: list[Any] = []
            available = True
        else:
            cached = sessions.get(key, ([], False))
            records, available = list(cached[0]), bool(cached[1])
        seen: set[str] = set()
        members: list[dict[str, Any]] = []
        for record in records:
            artifact_dir = getattr(record, "artifact_dir", "")
            if artifact_dir in seen:
                continue
            seen.add(artifact_dir)
            members.append(member_facts(record))
        attach_declared_bead_action(members)
        owners.append(
            {
                "plan_id": bead["id"],
                "records_available": available,
                "unknown_reason": None,
                "members": members,
            }
        )
    return owners


__all__ = [
    "ZombieReport",
    "load_zombie_report",
]
