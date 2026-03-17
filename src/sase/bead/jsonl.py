"""JSONL import/export for git-portable issue storage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sase.bead import db as db_mod
from sase.bead.model import Dependency, Issue, IssueType, Status


def _issue_to_dict(issue: Issue) -> dict[str, object]:
    return {
        "id": issue.id,
        "title": issue.title,
        "status": issue.status.value,
        "issue_type": issue.issue_type.value,
        "parent_id": issue.parent_id,
        "owner": issue.owner,
        "assignee": issue.assignee,
        "created_at": issue.created_at,
        "created_by": issue.created_by,
        "updated_at": issue.updated_at,
        "closed_at": issue.closed_at,
        "close_reason": issue.close_reason,
        "description": issue.description,
        "notes": issue.notes,
        "design": issue.design,
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
    return Issue(
        id=str(data["id"]),
        title=str(data["title"]),
        status=Status(str(data["status"])),
        issue_type=IssueType(str(data["issue_type"])),
        parent_id=str(data["parent_id"]) if data.get("parent_id") else None,
        owner=str(data.get("owner", "")),
        assignee=str(data.get("assignee", "")),
        created_at=str(data.get("created_at", "")),
        created_by=str(data.get("created_by", "")),
        updated_at=str(data.get("updated_at", "")),
        closed_at=str(data["closed_at"]) if data.get("closed_at") else None,
        close_reason=(str(data["close_reason"]) if data.get("close_reason") else None),
        description=str(data.get("description", "")),
        notes=str(data.get("notes", "")),
        design=str(data.get("design", "")),
        dependencies=deps,
    )


def export_to_jsonl(conn: sqlite3.Connection, path: Path) -> None:
    """Export all issues to a JSONL file, sorted by ID."""
    issues = db_mod.list_issues(conn)
    issues.sort(key=lambda i: i.id)
    with open(path, "w") as f:
        for issue in issues:
            f.write(json.dumps(_issue_to_dict(issue), separators=(",", ":")) + "\n")


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

    # Sort: plans first, then phases (so parent FK is satisfied)
    issues.sort(key=lambda i: (0 if i.issue_type == IssueType.PLAN else 1, i.id))

    # Upsert into database
    for issue in issues:
        existing = db_mod.get_issue(conn, issue.id)
        if existing is None:
            db_mod.create_issue(conn, issue)
        else:
            db_mod.update_issue(
                conn,
                issue.id,
                title=issue.title,
                status=issue.status.value,
                assignee=issue.assignee,
                updated_at=issue.updated_at,
                closed_at=issue.closed_at,
                close_reason=issue.close_reason,
                description=issue.description,
                notes=issue.notes,
                design=issue.design,
            )

        # Sync dependencies
        for dep in issue.dependencies:
            try:
                db_mod.add_dependency(
                    conn,
                    dep.issue_id,
                    dep.depends_on_id,
                    dep.created_at,
                    dep.created_by,
                )
            except Exception:
                pass  # Already exists or FK violation

    return issues
