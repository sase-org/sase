"""Compatibility JSONL import/export helpers for bead tests and sync mirrors.

Production bead codecs live in ``sase_core_rs``; these helpers remain for
legacy callers that operate on an existing SQLite connection.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sase.bead import db as db_mod
from sase.bead._db_codec import (
    close_history_json,
    plus_one_evidence_json,
    snooze_json,
)
from sase.bead.close_history_codec import (
    close_history_from_dicts,
    close_history_to_dicts,
)
from sase.bead.snooze_codec import snooze_from_dict, snooze_to_dict
from sase.bead.model import (
    BeadTier,
    Dependency,
    Issue,
    IssueType,
    PhaseSize,
    Resolution,
    Status,
    TaskPlusOneEvidence,
)


def _optional_str(value: object) -> str:
    return "" if value is None else str(value)


def _optional_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(entry) for entry in value if entry is not None]


def _plus_one_evidence_list(value: object) -> list[TaskPlusOneEvidence]:
    if not isinstance(value, list):
        return []
    return [
        TaskPlusOneEvidence(
            timestamp=_optional_str(evidence.get("timestamp", "")),
            reporter=_optional_str(evidence.get("reporter", "")),
            note=_optional_str(evidence.get("note", "")),
            refs=tuple(_optional_str_list(evidence.get("refs"))),
        )
        for evidence in value
        if isinstance(evidence, dict)
    ]


def _issue_to_dict(issue: Issue) -> dict[str, object]:
    return {
        "id": issue.id,
        "title": issue.title,
        "status": issue.status.value,
        "issue_type": issue.issue_type.value,
        **({"tier": issue.tier.value} if issue.tier else {}),
        "parent_id": issue.parent_id,
        "owner": issue.owner,
        "assignee": issue.assignee,
        "created_at": issue.created_at,
        "created_by": issue.created_by,
        "updated_at": issue.updated_at,
        "closed_at": issue.closed_at,
        "close_reason": issue.close_reason,
        **({"resolution": issue.resolution.value} if issue.resolution else {}),
        # Omitted when empty to match ``skip_serializing_if = "Vec::is_empty"``
        # on the Rust wire, so rows for beads that were never reopened stay
        # byte-identical to what they were before close history existed.
        **(
            {"close_history": close_history_to_dicts(issue.close_history)}
            if issue.close_history
            else {}
        ),
        "description": issue.description,
        "notes": issue.notes,
        "design": issue.design,
        **({"refs": issue.refs} if issue.refs else {}),
        **(
            {
                "plus_one_evidence": [
                    {
                        "timestamp": evidence.timestamp,
                        "reporter": evidence.reporter,
                        "note": evidence.note,
                        **({"refs": list(evidence.refs)} if evidence.refs else {}),
                    }
                    for evidence in issue.plus_one_evidence
                ]
            }
            if issue.plus_one_evidence
            else {}
        ),
        **({"snooze": snooze_to_dict(issue.snooze)} if issue.snooze else {}),
        "model": issue.model,
        **({"size": issue.size.value} if issue.size else {}),
        "is_ready_to_work": issue.is_ready_to_work,
        "changespec_name": issue.changespec_name,
        "changespec_bug_id": issue.changespec_bug_id,
        "dependencies": [
            {
                "issue_id": d.issue_id,
                "depends_on_id": d.depends_on_id,
                "created_at": d.created_at,
                "created_by": d.created_by,
            }
            for d in issue.dependencies
        ],
    }


def _dict_to_issue(data: dict[str, object]) -> Issue:
    deps_raw = data.get("dependencies", [])
    assert isinstance(deps_raw, list)
    deps = [
        Dependency(
            issue_id=str(d["issue_id"]),
            depends_on_id=str(d["depends_on_id"]),
            created_at=str(d.get("created_at", "")),
            created_by=str(d.get("created_by", "")),
        )
        for d in deps_raw
    ]
    issue = Issue(
        id=str(data["id"]),
        title=str(data["title"]),
        status=Status(str(data["status"])),
        issue_type=IssueType(str(data["issue_type"])),
        tier=BeadTier(str(data["tier"])) if data.get("tier") else None,
        parent_id=str(data["parent_id"]) if data.get("parent_id") else None,
        owner=_optional_str(data.get("owner", "")),
        assignee=_optional_str(data.get("assignee", "")),
        created_at=_optional_str(data.get("created_at", "")),
        created_by=_optional_str(data.get("created_by", "")),
        updated_at=str(data.get("updated_at", "")),
        closed_at=str(data["closed_at"]) if data.get("closed_at") else None,
        close_reason=(str(data["close_reason"]) if data.get("close_reason") else None),
        resolution=(
            Resolution(str(data["resolution"])) if data.get("resolution") else None
        ),
        description=_optional_str(data.get("description", "")),
        notes=_optional_str(data.get("notes", "")),
        design=_optional_str(data.get("design", "")),
        refs=_optional_str_list(data.get("refs")),
        plus_one_evidence=_plus_one_evidence_list(data.get("plus_one_evidence")),
        close_history=close_history_from_dicts(data.get("close_history")),
        snooze=snooze_from_dict(data.get("snooze")),
        model=_optional_str(data.get("model", "")),
        size=PhaseSize(str(data["size"])) if data.get("size") else None,
        is_ready_to_work=bool(data.get("is_ready_to_work", False)),
        changespec_name=_optional_str(data.get("changespec_name", "")),
        changespec_bug_id=_optional_str(data.get("changespec_bug_id", "")),
        dependencies=deps,
    )
    issue.validate()
    return issue


def export_to_jsonl(conn: sqlite3.Connection, path: Path) -> None:
    """Export all issues to a JSONL file, sorted by ID."""
    issues = db_mod.list_issues(conn)
    issues.sort(key=lambda i: i.id)
    # ensure_ascii=False keeps this byte-identical to the Rust ``serde_json``
    # writer of the same file; escaping non-ASCII here churns issues.jsonl.
    with open(path, "w", encoding="utf-8") as f:
        for issue in issues:
            f.write(
                json.dumps(
                    _issue_to_dict(issue), separators=(",", ":"), ensure_ascii=False
                )
                + "\n"
            )


def import_from_jsonl(path: Path, conn: sqlite3.Connection) -> list[Issue]:
    """Import issues from a JSONL file with upsert semantics.

    Returns the list of imported issues. Handles missing/empty files
    gracefully by returning an empty list. Skips corrupt lines.
    """
    if not path.exists():
        return []
    text = path.read_text().strip()
    if not text:
        return []

    # Parse all issues first (epics before children for FK ordering)
    issues: list[Issue] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            issues.append(_dict_to_issue(data))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue

    _apply_missing_tiers(issues)

    # Sort plans first, then top-level tasks and phases (for parent FK ordering).
    issues.sort(key=lambda i: (0 if i.issue_type == IssueType.PLAN else 1, i.id))

    # Upsert the entire mirror in one transaction. The SQLite database is
    # derived compatibility state, so partial imports are never useful.
    try:
        for issue in issues:
            existing = db_mod.get_issue(conn, issue.id)
            if existing is None:
                db_mod.create_issue(conn, issue, commit=False)
            else:
                db_mod.update_issue(
                    conn,
                    issue.id,
                    commit=False,
                    title=issue.title,
                    status=issue.status.value,
                    assignee=issue.assignee,
                    updated_at=issue.updated_at,
                    closed_at=issue.closed_at,
                    close_reason=issue.close_reason,
                    resolution=(
                        issue.resolution.value if issue.resolution is not None else None
                    ),
                    description=issue.description,
                    notes=issue.notes,
                    design=issue.design,
                    refs="\n".join(issue.refs),
                    plus_one_evidence=plus_one_evidence_json(issue.plus_one_evidence),
                    close_history=close_history_json(issue.close_history),
                    snooze=snooze_json(issue.snooze),
                    model=issue.model,
                    size=issue.size.value if issue.size else None,
                    tier=issue.tier.value if issue.tier else None,
                    is_ready_to_work=int(issue.is_ready_to_work),
                    changespec_name=issue.changespec_name,
                    changespec_bug_id=issue.changespec_bug_id,
                )

            # Sync dependencies. A duplicate or invalid legacy dependency is
            # skipped without aborting the surrounding transaction.
            for dep in issue.dependencies:
                try:
                    db_mod.add_dependency(
                        conn,
                        dep.issue_id,
                        dep.depends_on_id,
                        dep.created_at,
                        dep.created_by,
                        commit=False,
                    )
                except Exception:
                    pass  # Already exists or FK violation
            db_mod.delete_dependencies_not_in(
                conn,
                issue.id,
                [dep.depends_on_id for dep in issue.dependencies],
                commit=False,
            )
    except BaseException:
        conn.rollback()
        raise
    conn.commit()

    return issues


def _apply_missing_tiers(issues: list[Issue]) -> None:
    phase_parent_ids = {
        issue.parent_id
        for issue in issues
        if issue.issue_type == IssueType.PHASE and issue.parent_id
    }
    for issue in issues:
        if issue.issue_type == IssueType.PLAN and issue.tier is None:
            issue.tier = (
                BeadTier.EPIC if issue.id in phase_parent_ids else BeadTier.PLAN
            )
