"""Value resolvers shared by selected and marked artifact copy targets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.artifact_refs import design_reference_for_plan_row
from sase.core.commit_footer_facade import parse_commit_footer

from ...models.artifact_file_clipboard import (
    artifact_file_materialized_stored_path,
)


def commit_plan_reference(message: str) -> str | None:
    """Return the same terminal SASE_PLAN label used by the commit modal."""
    try:
        footer = parse_commit_footer(message)
    except Exception:
        return None
    tag = next(
        (tag for tag in reversed(footer.tags) if tag.raw_key == "SASE_PLAN"),
        None,
    )
    return None if tag is None else tag.label


def artifact_file_contents(entry: Any) -> str:
    path = artifact_file_materialized_stored_path(entry)
    if path is None:
        raise ValueError(f"{entry.label} has no stored path")
    return path.read_text(encoding="utf-8", errors="replace")


def plan_copy_value(pane: Any, row: Any, target: str) -> str:
    del pane
    if target == "bead_id":
        value = None if row.bead_link is None else row.bead_link.bead_id
        if value is None:
            raise ValueError(f"{row.row_id} has no owning bead id")
        return value
    if target == "design":
        value = design_reference_for_plan_row(row)
        if value is None:
            raise ValueError(f"{row.row_id} has no design plan reference")
        return value
    if row.proposal is not None:
        values = {
            "path": row.proposal.plan_path,
            "title": row.proposal.title,
            "body": row.proposal.body,
        }
    elif row.active is not None:
        document = row.active.document
        values = {
            "path": document.path,
            "title": document.frontmatter.get("title") or Path(document.path).stem,
            "body": document.body,
        }
    elif row.archive is not None:
        plan = row.archive.plan
        values = {
            "path": plan.path,
            "title": plan.title or plan.name,
            "body": plan.body,
        }
    else:  # pragma: no cover - PlanRow always has a document payload.
        values = {"path": None, "title": None, "body": None}
    value = values[target]
    if not value:
        raise ValueError(f"{row.row_id} has no {target}")
    return value


def bead_copy_value(pane: Any, row: Any, target: str) -> str:
    issue = row.issue
    if target == "id":
        return str(issue.id)
    if target == "title":
        return str(issue.title)
    if target == "design":
        if not issue.design.strip():
            raise ValueError(f"{row.row_id} has no design plan reference")
        return str(issue.design)
    preview = pane.preview_for_row(row)
    if target == "body":
        return str(preview.content)
    raise ValueError(f"unknown bead copy target: {target}")


def plural(value: str) -> str:
    return "bodies" if value == "body" else f"{value}s"
