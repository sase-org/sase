"""Shared bead detail resolution and rendering."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Literal

from sase.bead.cli_common import status_icon
from sase.bead.model import BeadTier, Dependency, Issue, IssueType, Status
from sase.bead.project import BeadProject


@dataclass(frozen=True)
class _IssueRef:
    issue_id: str
    issue: Issue | None


@dataclass(frozen=True)
class _PlanLink:
    section: str
    source: Literal["self", "parent"]
    path: str
    from_ref: _IssueRef | None


@dataclass(frozen=True)
class _IssueDetail:
    """One bead plus its resolved relationship and plan graph."""

    issue: Issue
    ancestors: tuple[_IssueRef, ...]
    phases: tuple[_IssueRef, ...]
    child_epics: tuple[_IssueRef, ...]
    depends_on: tuple[_IssueRef, ...]
    blocks: tuple[_IssueRef, ...]
    plan: _PlanLink | None


def resolve_issue_detail(view: BeadProject, issue: Issue) -> _IssueDetail:
    """Resolve every relationship needed by the text and JSON detail views."""
    ancestors = _parent_lineage(view, issue)
    children = view.get_epic_children(issue.id)
    phases = tuple(
        _issue_ref(child) for child in children if child.issue_type == IssueType.PHASE
    )
    child_epics = tuple(
        _issue_ref(child) for child in children if child.issue_type == IssueType.PLAN
    )

    dependencies: list[_IssueRef] = []
    for dependency in issue.dependencies:
        try:
            dependencies.append(_issue_ref(view.show(dependency.depends_on_id)))
        except KeyError:
            dependencies.append(_unresolved_ref(dependency.depends_on_id))

    block_ids = [
        other.id
        for other in view.list_issues()
        for dependency in other.dependencies
        if dependency.depends_on_id == issue.id
    ]
    blocks: list[_IssueRef] = []
    for blocked_id in block_ids:
        try:
            blocks.append(_issue_ref(view.show(blocked_id)))
        except KeyError:
            blocks.append(_unresolved_ref(blocked_id))

    return _IssueDetail(
        issue=issue,
        ancestors=ancestors,
        phases=phases,
        child_epics=child_epics,
        depends_on=tuple(dependencies),
        blocks=tuple(blocks),
        plan=_resolve_plan_link(issue, ancestors),
    )


def render_issue_detail(
    detail: _IssueDetail,
    *,
    relativize_design: bool,
) -> str:
    """Render the established human-readable bead detail block."""
    issue = detail.issue
    lines = [
        (
            f"{status_icon(issue.status)} {issue.id} · {issue.title}"
            f"   [{issue.status.value.upper()}]"
        )
    ]
    tier = f" · Tier: {issue.tier.value}" if issue.tier else ""
    lines.append(
        f"Type: {issue.issue_type.value}{tier} · Owner: {issue.owner or '(none)'}"
    )
    if issue.assignee:
        lines.append(f"Assignee: {issue.assignee}")
    if issue.status == Status.CLAIMED:
        lines.append(
            f"Claimed by: {issue.assignee} (agent has not started working yet)"
        )
    if issue.model:
        lines.append(f"Model: {issue.model}")
    if issue.issue_type == IssueType.PHASE:
        lines.append(f"Size: {_phase_size_value(issue)}")

    if issue.parent_id:
        lineage = [issue.id]
        for ancestor in detail.ancestors:
            if ancestor.issue is None:
                lineage.append(f"{ancestor.issue_id} (not found)")
            else:
                lineage.append(f"{_lineage_kind(ancestor.issue)} {ancestor.issue.id}")
        lines.extend(["", "PARENT", f"  ↑ {' ← '.join(lineage)}"])

    if detail.phases or detail.child_epics:
        lines.extend(["", "CHILDREN"])
        if detail.phases:
            lines.append("  PHASES")
            for child_ref in detail.phases:
                child = child_ref.issue
                assert child is not None
                lines.append(
                    f"    {status_icon(child.status)} {child.id}: {child.title}"
                    f"   [{child.status.value.upper()}]"
                    f" · Size: {_phase_size_value(child)}"
                )
        if detail.child_epics:
            lines.append("  CHILD EPICS")
            for child_ref in detail.child_epics:
                child = child_ref.issue
                assert child is not None
                child_tier = child.tier.value if child.tier else "(none)"
                lines.append(
                    f"    {status_icon(child.status)} {child.id}: {child.title}"
                    f"   [{child.status.value.upper()}] · Tier: {child_tier}"
                )

    if detail.depends_on:
        lines.extend(["", "DEPENDS ON"])
        for dependency in detail.depends_on:
            dep_issue = dependency.issue
            if dep_issue is None:
                lines.append(f"  → {dependency.issue_id} (not found)")
            else:
                lines.append(
                    f"  → {status_icon(dep_issue.status)} {dep_issue.id}:"
                    f" {dep_issue.title}   [{dep_issue.status.value.upper()}]"
                )

    if detail.blocks:
        lines.extend(["", "BLOCKS"])
        for blocked_ref in detail.blocks:
            blocked = blocked_ref.issue
            if blocked is None:
                lines.append(f"  ← {blocked_ref.issue_id} (not found)")
            else:
                lines.append(
                    f"  ← {status_icon(blocked.status)} {blocked.id}:"
                    f" {blocked.title}   [{blocked.status.value.upper()}]"
                )

    if issue.description:
        lines.extend(["", "DESCRIPTION", f"  {issue.description}"])
    if issue.notes:
        lines.extend(["", "NOTES", f"  {issue.notes}"])
    if issue.issue_type == IssueType.PLAN and (
        issue.changespec_name or issue.changespec_bug_id
    ):
        lines.extend(["", "CHANGESPEC"])
        if issue.changespec_name:
            lines.append(f"  Name: {issue.changespec_name}")
        if issue.changespec_bug_id:
            lines.append(f"  Bug ID: {issue.changespec_bug_id}")

    if detail.plan is not None:
        plan = detail.plan
        lines.extend(["", plan.section])
        if plan.from_ref is not None:
            resolved_parent = plan.from_ref.issue
            assert resolved_parent is not None
            parent_kind = "epic" if resolved_parent.tier == BeadTier.EPIC else "plan"
            lines.append(
                f"  From parent {parent_kind} bead "
                f"{resolved_parent.id} · {resolved_parent.title}"
            )
        lines.append(
            f"  {_display_design_path(plan.path, relativize=relativize_design)}"
        )

    return "\n".join(lines) + "\n"


def render_issue_detail_json(detail: _IssueDetail) -> str:
    """Render a stable single-bead JSON envelope."""
    envelope = {
        "issue": issue_to_wire_dict(detail.issue),
        "ancestors": [_ref_to_wire_dict(ref) for ref in detail.ancestors],
        "children": {
            "phases": [_ref_to_wire_dict(ref) for ref in detail.phases],
            "epics": [_ref_to_wire_dict(ref) for ref in detail.child_epics],
        },
        "depends_on": [_ref_to_wire_dict(ref) for ref in detail.depends_on],
        "blocks": [_ref_to_wire_dict(ref) for ref in detail.blocks],
        "plan": _plan_to_wire_dict(detail.plan),
    }
    return json.dumps(envelope, indent=2) + "\n"


def issue_to_wire_dict(issue: Issue) -> dict[str, object]:
    """Return the shared flat issue schema used by read-command JSON."""
    payload: dict[str, object] = {
        "id": issue.id,
        "title": issue.title,
        "status": issue.status.value,
        "issue_type": issue.issue_type.value,
        "tier": issue.tier.value if issue.tier else None,
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
        "model": issue.model,
        "is_ready_to_work": issue.is_ready_to_work,
        "changespec_name": issue.changespec_name,
        "changespec_bug_id": issue.changespec_bug_id,
        "dependencies": [_dependency_to_wire_dict(dep) for dep in issue.dependencies],
    }
    if issue.size is not None:
        payload["size"] = issue.size.value
    return payload


def _dependency_to_wire_dict(dep: Dependency) -> dict[str, str]:
    return {
        "issue_id": dep.issue_id,
        "depends_on_id": dep.depends_on_id,
        "created_at": dep.created_at,
        "created_by": dep.created_by,
    }


def design_paths_are_relative() -> bool:
    """Return whether human-readable design paths should be cwd-relative."""
    from sase.sdd.store import resolve_sdd_store

    return resolve_sdd_store(Path.cwd(), 1).is_in_tree


def _parent_lineage(view: BeadProject, issue: Issue) -> tuple[_IssueRef, ...]:
    ancestors: list[_IssueRef] = []
    parent_id = issue.parent_id
    seen = {issue.id}
    while parent_id is not None:
        if parent_id in seen:
            ancestors.append(_unresolved_ref(parent_id))
            return tuple(ancestors)
        seen.add(parent_id)
        try:
            parent = view.show(parent_id)
        except KeyError:
            ancestors.append(_unresolved_ref(parent_id))
            return tuple(ancestors)
        ancestors.append(_issue_ref(parent))
        parent_id = parent.parent_id
    return tuple(ancestors)


def _resolve_plan_link(
    issue: Issue,
    ancestors: tuple[_IssueRef, ...],
) -> _PlanLink | None:
    if issue.design:
        section = (
            "EPIC PLAN" if issue.parent_id and issue.tier == BeadTier.EPIC else "PLAN"
        )
        return _PlanLink(
            section=section,
            source="self",
            path=issue.design,
            from_ref=None,
        )

    if issue.issue_type != IssueType.PHASE or not ancestors:
        return None
    resolved_parent = ancestors[0].issue
    if (
        resolved_parent is None
        or resolved_parent.issue_type != IssueType.PLAN
        or not resolved_parent.design
    ):
        return None
    section = "EPIC PLAN" if resolved_parent.tier == BeadTier.EPIC else "PARENT PLAN"
    return _PlanLink(
        section=section,
        source="parent",
        path=resolved_parent.design,
        from_ref=ancestors[0],
    )


def _issue_ref(issue: Issue) -> _IssueRef:
    return _IssueRef(issue_id=issue.id, issue=issue)


def _unresolved_ref(issue_id: str) -> _IssueRef:
    return _IssueRef(issue_id=issue_id, issue=None)


def _ref_to_wire_dict(ref: _IssueRef) -> dict[str, object]:
    issue = ref.issue
    return {
        "id": ref.issue_id,
        "resolved": issue is not None,
        "title": issue.title if issue else None,
        "status": issue.status.value if issue else None,
        "issue_type": issue.issue_type.value if issue else None,
        "tier": issue.tier.value if issue and issue.tier else None,
        "size": issue.size.value if issue and issue.size else None,
    }


def _plan_to_wire_dict(plan: _PlanLink | None) -> dict[str, object] | None:
    if plan is None:
        return None
    return {
        "section": plan.section,
        "source": plan.source,
        "path": plan.path,
        "from": _ref_to_wire_dict(plan.from_ref) if plan.from_ref else None,
    }


def _lineage_kind(issue: Issue) -> str:
    if issue.issue_type == IssueType.PHASE:
        return "phase"
    return "epic" if issue.tier == BeadTier.EPIC else "plan"


def _phase_size_value(issue: Issue) -> str:
    return issue.size.value if issue.size else "small"


def _display_design_path(design: str, *, relativize: bool) -> str:
    if relativize:
        return os.path.relpath(design)
    return design
