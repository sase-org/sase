"""Read-only handler for ``sase bead zombies``.

Reports in-progress plan beads whose entire descendant tree is closed and
whose land session has no current owner, using the shared Rust zombie-plan
predicate. Never arms, claims, launches, closes, or reopens any bead.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from time import time

from sase.bead.cli_common import get_read_view
from sase.bead.cross_project import enabled_project_store_snapshots
from sase.bead.stranded_presentation import STRANDED_GLYPH, stranded_age_label
from sase.bead.zombie import ZombieReport, load_zombie_report
from sase.core.zombie_facade import ZombieEvaluationReport, ZombieVerdict

_UNKNOWN_GLYPH = "?"
_OWNED_GLYPH = "◐"
_NOT_ZOMBIE_GLYPH = "○"


def _project_targets(all_projects: bool) -> list[tuple[str, str]]:
    """Return ``(project_key, label)`` pairs to report on.

    The default is the enabled project owning the current readable store,
    matched by issue prefix; ``-a`` reports on every enabled project with a
    materialized store.
    """
    snapshots = enabled_project_store_snapshots()
    if all_projects:
        return [
            (snapshot.origin.project_key, snapshot.origin.project_label)
            for snapshot in snapshots
            if snapshot.origin.beads_dir is not None
            and snapshot.unavailable_reason is None
        ]
    view = get_read_view()
    prefix = str(view._config.get("issue_prefix", "beads"))
    for snapshot in snapshots:
        if snapshot.issue_prefix == prefix and snapshot.origin.beads_dir is not None:
            return [(snapshot.origin.project_key, snapshot.origin.project_label)]
    print(
        f"Error: no enabled project owns the current bead store "
        f"(issue prefix {prefix!r}). Run inside an enabled project or use -a.",
        file=sys.stderr,
    )
    sys.exit(2)


def _unavailable_targets(all_projects: bool) -> list[tuple[str, str, str]]:
    """Return ``(key, label, reason)`` for enabled projects without a store."""
    if not all_projects:
        return []
    return [
        (
            snapshot.origin.project_key,
            snapshot.origin.project_label,
            snapshot.unavailable_reason or "not materialized",
        )
        for snapshot in enabled_project_store_snapshots()
        if snapshot.origin.beads_dir is None or snapshot.unavailable_reason is not None
    ]


def _report_timestamp(generated_at: float) -> str:
    return (
        datetime.fromtimestamp(generated_at, tz=UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _close_age(latest_closed_at: str | None, now: float) -> str:
    from sase.bead._stranded_facts_members import epoch

    moment = epoch(latest_closed_at) if latest_closed_at else None
    if moment is None:
        return "unknown age"
    age = stranded_age_label(moment, now)
    return f"{age} ago" if age else "just now"


def _row_lines(row: ZombieVerdict, *, now: float) -> list[str]:
    title = f" · {row.title}" if row.title else ""
    if row.state == "zombie":
        lines = [f"{STRANDED_GLYPH} {row.plan_id}{title}"]
        descendants = (
            f"all {row.descendant_count} descendants closed"
            if row.all_descendants_closed
            else f"{row.descendant_count} descendants"
        )
        latest = row.latest_descendant_id or "unknown"
        lines.append(
            f"    descendants: {descendants} · latest {latest} at "
            f"{row.latest_descendant_closed_at or 'unknown'} "
            f"({_close_age(row.latest_descendant_closed_at, now)})"
        )
        ownership = row.ownership_reason or "no live owner"
        if row.recovery_eligible:
            lines.append(
                f"    ownership: {ownership} · recovery: eligible — "
                f"run `sase bead work {row.plan_id}`"
            )
        else:
            lines.append(
                f"    ownership: {ownership} · "
                f"recovery: {row.recovery_reason or 'unavailable'}"
            )
        return lines
    if row.state == "owned":
        owner = f" by {row.owner}" if row.owner else ""
        reason = f" ({row.ownership_reason})" if row.ownership_reason else ""
        return [f"{_OWNED_GLYPH} {row.plan_id}{title} — owned{owner}{reason}"]
    if row.state == "not_zombie":
        reason = f" ({row.reason})" if row.reason else ""
        return [f"{_NOT_ZOMBIE_GLYPH} {row.plan_id}{title} — not a zombie{reason}"]
    reason = row.unknown_reason or row.reason or "unknown evidence"
    return [f"{_UNKNOWN_GLYPH} {row.plan_id}{title} — unknown: {reason}"]


def _render_compact(
    projects: list[tuple[str, str, ZombieReport]], *, now: float
) -> str:
    chunks: list[str] = []
    total_zombies = 0
    total_unknown = 0
    total_owned = 0
    total_not_zombie = 0
    for key, label, loaded in projects:
        if loaded.collection_failed:
            chunks.append(f"project {label} ({key}) · {_report_timestamp(now)}")
            chunks.append(
                f"  report failed: {loaded.failure_reason or 'unknown error'}"
            )
            continue
        chunks.append(
            f"project {label} ({key}) · report at "
            f"{_report_timestamp(loaded.generated_at)}"
        )
        zombies = [row for row in loaded.report.rows if row.state == "zombie"]
        owned = [row for row in loaded.report.rows if row.state == "owned"]
        not_zombie = [row for row in loaded.report.rows if row.state == "not_zombie"]
        unknown = [row for row in loaded.report.rows if row.state == "unknown"]
        total_zombies += len(zombies)
        total_owned += len(owned)
        total_not_zombie += len(not_zombie)
        total_unknown += len(unknown)
        if not loaded.report.rows:
            chunks.append("  no in-progress plans")
            continue
        for row in (*zombies, *unknown, *owned, *not_zombie):
            for index, line in enumerate(_row_lines(row, now=now)):
                chunks.append(f"  {line}" if index else line)
    chunks.append(
        f"Summary: {total_zombies} zombie(s), {total_unknown} unknown, "
        f"{total_owned} owned, {total_not_zombie} not-zombie"
    )
    return "\n".join(chunks) + "\n"


def _row_json(row: ZombieVerdict) -> dict[str, object]:
    return {
        "plan_id": row.plan_id,
        "title": row.title,
        "tier": row.tier,
        "assignee": row.assignee,
        "state": row.state,
        "zombie": row.zombie,
        "recovery_eligible": row.recovery_eligible,
        "reason": row.reason,
        "unknown_reason": row.unknown_reason,
        "recovery_reason": row.recovery_reason,
        "owner": row.owner,
        "ownership_reason": row.ownership_reason,
        "tree_complete": row.tree_complete,
        "descendant_count": row.descendant_count,
        "all_descendants_closed": row.all_descendants_closed,
        "latest_descendant_closed_at": row.latest_descendant_closed_at,
        "latest_descendant_id": row.latest_descendant_id,
        "latest_descendant_close_event_id": row.latest_descendant_close_event_id,
        "close_token": row.close_token,
    }


def _render_json(
    projects: list[tuple[str, str, ZombieReport]],
) -> str:
    return (
        json.dumps(
            {
                "generated_at": _report_timestamp(time()),
                "projects": [
                    {
                        "project_key": key,
                        "project_label": label,
                        "collection_failed": loaded.collection_failed,
                        "failure_reason": loaded.failure_reason,
                        "report_at": _report_timestamp(loaded.generated_at),
                        "rows": [_row_json(row) for row in loaded.report.rows],
                    }
                    for key, label, loaded in projects
                ],
            },
            indent=2,
            sort_keys=False,
        )
        + "\n"
    )


def handle_bead_zombies(args: argparse.Namespace) -> None:
    """Render the read-only zombie-plan report."""
    all_projects = bool(getattr(args, "all_projects", False))
    targets = _project_targets(all_projects)
    projects = [(key, label, load_zombie_report(key)) for key, label in targets]
    for key, label, reason in _unavailable_targets(all_projects):
        projects.append(
            (
                key,
                label,
                ZombieReport(
                    report=ZombieEvaluationReport(),
                    project=key,
                    titles={},
                    generated_at=time(),
                    collection_failed=True,
                    failure_reason=reason,
                ),
            )
        )
    match getattr(args, "format", "compact"):
        case "json":
            sys.stdout.write(_render_json(projects))
        case "compact":
            sys.stdout.write(_render_compact(projects, now=time()))
        case _:
            raise AssertionError(f"unknown zombies format: {args.format}")


__all__ = ["handle_bead_zombies"]
