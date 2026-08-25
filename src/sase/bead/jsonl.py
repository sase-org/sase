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
    notes_json,
    plus_one_evidence_json,
    snooze_json,
)
from sase.bead.close_history_codec import (
    close_history_from_dicts,
    close_history_to_dicts,
)
from sase.bead.note_codec import notes_from_data, notes_to_dicts
from sase.bead.snooze_codec import snooze_from_dict, snooze_to_dict
from sase.bead.model import (
    BeadLink,
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


def _task_type_fields_from_data(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): "" if item is None else str(item) for key, item in value.items()}


def _optional_aliased_str(
    data: dict[str, object],
    canonical_key: str,
    legacy_key: str,
) -> str:
    value = data.get(canonical_key)
    if value is None or value == "":
        value = data.get(legacy_key, "")
    return _optional_str(value)


def _links_from_data(value: object) -> list[BeadLink]:
    if not isinstance(value, list):
        return []
    links: list[BeadLink] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        target_ref = str(item.get("target_ref") or "")
        relation = str(item.get("relation") or "")
        if not target_ref or not relation:
            continue
        try:
            uses = int(item.get("uses", 1))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            uses = 1
        links.append(
            BeadLink(
                target_ref=target_ref,
                relation=relation,
                description=str(item.get("description") or ""),
                origin=str(item.get("origin") or "manual"),
                direction=str(item.get("direction") or "out"),
                uses=uses if uses > 0 else 1,
            )
        )
    return links


def _plus_one_evidence_list(value: object) -> list[TaskPlusOneEvidence]:
    if not isinstance(value, list):
        return []
    return [
        TaskPlusOneEvidence(
            timestamp=_optional_str(evidence.get("timestamp", "")),
            reporter=_optional_str(evidence.get("reporter", "")),
            note=_optional_str(evidence.get("note", "")),
            refs=tuple(_optional_str_list(evidence.get("refs"))),
            observed_since=(
                None
                if evidence.get("observed_since") is None
                else _optional_str(evidence.get("observed_since"))
            ),
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
        # Omitted when empty to match ``skip_serializing_if = "Vec::is_empty"``
        # on the Rust wire, so rows for beads with no notes stay
        # byte-identical to what they were before notes existed.
        **({"notes": notes_to_dicts(issue.notes)} if issue.notes else {}),
        "design": issue.design,
        **({"refs": issue.refs} if issue.refs else {}),
        **(
            {
                "links": [
                    {
                        "target_ref": link.target_ref,
                        "relation": link.relation,
                        "description": link.description,
                        "origin": link.origin,
                        "direction": link.direction,
                        "uses": link.uses,
                    }
                    for link in issue.links
                ]
            }
            if issue.links
            else {}
        ),
        **(
            {
                "plus_one_evidence": [
                    {
                        "timestamp": evidence.timestamp,
                        "reporter": evidence.reporter,
                        "note": evidence.note,
                        **({"refs": list(evidence.refs)} if evidence.refs else {}),
                        **(
                            {"observed_since": evidence.observed_since}
                            if evidence.observed_since
                            else {}
                        ),
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
        **({"external_ref": issue.external_ref} if issue.external_ref else {}),
        **({"task_type": issue.task_type} if issue.task_type else {}),
        **(
            {"task_type_fields": dict(issue.task_type_fields)}
            if issue.task_type_fields
            else {}
        ),
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
        notes=notes_from_data(
            data.get("notes"),
            fallback_timestamp=_optional_str(data.get("created_at", "")),
            fallback_author=_optional_str(data.get("created_by", "")),
        ),
        design=_optional_str(data.get("design", "")),
        refs=_optional_str_list(data.get("refs")),
        links=_links_from_data(data.get("links")),
        plus_one_evidence=_plus_one_evidence_list(data.get("plus_one_evidence")),
        close_history=close_history_from_dicts(data.get("close_history")),
        snooze=snooze_from_dict(data.get("snooze")),
        model=_optional_str(data.get("model", "")),
        size=PhaseSize(str(data["size"])) if data.get("size") else None,
        is_ready_to_work=bool(data.get("is_ready_to_work", False)),
        changespec_name=_optional_aliased_str(data, "patch_name", "changespec_name"),
        changespec_bug_id=_optional_aliased_str(
            data, "patch_bug_id", "changespec_bug_id"
        ),
        external_ref=_optional_str(data.get("external_ref", "")),
        task_type=_optional_str(data.get("task_type", "")),
        task_type_fields=_task_type_fields_from_data(data.get("task_type_fields")),
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
                    notes=notes_json(issue.notes),
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
                    external_ref=issue.external_ref,
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
