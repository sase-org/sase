"""Resolve bead relationships for CLI and hosted detail views."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from sase.bead.model import BeadTier, Issue, IssueType
from sase.bead.project import BeadProject


@dataclass(frozen=True)
class IssueRef:
    issue_id: str
    issue: Issue | None


@dataclass(frozen=True)
class PlanLink:
    section: str
    source: Literal["self", "parent"]
    path: str
    from_ref: IssueRef | None


@dataclass(frozen=True)
class IssueDetail:
    """One bead plus its resolved relationship and plan graph."""

    issue: Issue
    ancestors: tuple[IssueRef, ...]
    phases: tuple[IssueRef, ...]
    child_epics: tuple[IssueRef, ...]
    depends_on: tuple[IssueRef, ...]
    blocks: tuple[IssueRef, ...]
    plan: PlanLink | None


@dataclass(frozen=True)
class IssueDetailIndex:
    """Resolve bead details from one already-loaded issue snapshot."""

    _issues_by_id: Mapping[str, Issue]
    _children_by_parent: Mapping[str, tuple[Issue, ...]]
    _blocks_by_target: Mapping[str, tuple[Issue, ...]]

    @classmethod
    def from_issues(cls, issues: Iterable[Issue]) -> IssueDetailIndex:
        issue_tuple = tuple(issues)
        issues_by_id = {issue.id: issue for issue in issue_tuple}
        children_by_parent: dict[str, list[Issue]] = defaultdict(list)
        blocks_by_target: dict[str, list[Issue]] = defaultdict(list)
        for issue in issue_tuple:
            if issue.parent_id:
                children_by_parent[issue.parent_id].append(issue)
            for dependency in issue.dependencies:
                blocks_by_target[dependency.depends_on_id].append(issue)
        return cls(
            issues_by_id,
            {
                parent_id: tuple(children)
                for parent_id, children in children_by_parent.items()
            },
            {
                target_id: tuple(blocks)
                for target_id, blocks in blocks_by_target.items()
            },
        )

    def resolve(self, issue: Issue) -> IssueDetail:
        ancestors = _parent_lineage_from_index(self._issues_by_id, issue)
        children = self._children_by_parent.get(issue.id, ())
        phases = tuple(
            _issue_ref(child)
            for child in children
            if child.issue_type == IssueType.PHASE
        )
        child_epics = tuple(
            _issue_ref(child)
            for child in children
            if child.issue_type == IssueType.PLAN
        )
        dependencies = tuple(
            _issue_ref(dependency_issue)
            if (dependency_issue := self._issues_by_id.get(dependency.depends_on_id))
            is not None
            else _unresolved_ref(dependency.depends_on_id)
            for dependency in issue.dependencies
        )
        blocks = tuple(
            _issue_ref(blocked) for blocked in self._blocks_by_target.get(issue.id, ())
        )
        return IssueDetail(
            issue=issue,
            ancestors=ancestors,
            phases=phases,
            child_epics=child_epics,
            depends_on=dependencies,
            blocks=blocks,
            plan=_resolve_plan_link(issue, ancestors),
        )


def resolve_issue_detail(view: BeadProject, issue: Issue | str) -> IssueDetail:
    """Resolve every relationship needed by the text and JSON detail views."""
    if hasattr(view, "show_issue_detail"):
        issue_id = issue if isinstance(issue, str) else issue.id
        snapshot = view.show_issue_detail(issue_id)
        resolved_issue = snapshot.issue
        ancestors = _ancestor_refs_from_snapshot(resolved_issue, snapshot.ancestors)
        phases = tuple(
            _issue_ref(child)
            for child in snapshot.children
            if child.issue_type == IssueType.PHASE
        )
        child_epics = tuple(
            _issue_ref(child)
            for child in snapshot.children
            if child.issue_type == IssueType.PLAN
        )
        dependencies = tuple(
            _issue_ref(resolved)
            if resolved is not None
            else _unresolved_ref(dependency.depends_on_id)
            for dependency, resolved in zip(
                resolved_issue.dependencies,
                snapshot.depends_on,
                strict=True,
            )
        )
        blocks = tuple(_issue_ref(blocked) for blocked in snapshot.blocks)
        return IssueDetail(
            issue=resolved_issue,
            ancestors=ancestors,
            phases=phases,
            child_epics=child_epics,
            depends_on=dependencies,
            blocks=blocks,
            plan=_resolve_plan_link(resolved_issue, ancestors),
        )

    if isinstance(issue, str):
        issue = view.show(issue)
    return _resolve_issue_detail_legacy(view, issue)


def _resolve_issue_detail_legacy(view: BeadProject, issue: Issue) -> IssueDetail:
    ancestors = _parent_lineage(view, issue)
    children = view.get_epic_children(issue.id)
    phases = tuple(
        _issue_ref(child) for child in children if child.issue_type == IssueType.PHASE
    )
    child_epics = tuple(
        _issue_ref(child) for child in children if child.issue_type == IssueType.PLAN
    )

    dependencies: list[IssueRef] = []
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
    blocks: list[IssueRef] = []
    for blocked_id in block_ids:
        try:
            blocks.append(_issue_ref(view.show(blocked_id)))
        except KeyError:
            blocks.append(_unresolved_ref(blocked_id))

    return IssueDetail(
        issue=issue,
        ancestors=ancestors,
        phases=phases,
        child_epics=child_epics,
        depends_on=tuple(dependencies),
        blocks=tuple(blocks),
        plan=_resolve_plan_link(issue, ancestors),
    )


def _ancestor_refs_from_snapshot(
    issue: Issue,
    ancestors: tuple[Issue | None, ...],
) -> tuple[IssueRef, ...]:
    refs: list[IssueRef] = []
    parent_id = issue.parent_id
    for ancestor in ancestors:
        if ancestor is None:
            if parent_id is not None:
                refs.append(_unresolved_ref(parent_id))
            break
        refs.append(_issue_ref(ancestor))
        parent_id = ancestor.parent_id
    return tuple(refs)


def _parent_lineage(view: BeadProject, issue: Issue) -> tuple[IssueRef, ...]:
    ancestors: list[IssueRef] = []
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


def _parent_lineage_from_index(
    issues_by_id: Mapping[str, Issue],
    issue: Issue,
) -> tuple[IssueRef, ...]:
    ancestors: list[IssueRef] = []
    parent_id = issue.parent_id
    seen = {issue.id}
    while parent_id is not None:
        if parent_id in seen:
            ancestors.append(_unresolved_ref(parent_id))
            return tuple(ancestors)
        seen.add(parent_id)
        parent = issues_by_id.get(parent_id)
        if parent is None:
            ancestors.append(_unresolved_ref(parent_id))
            return tuple(ancestors)
        ancestors.append(_issue_ref(parent))
        parent_id = parent.parent_id
    return tuple(ancestors)


def _resolve_plan_link(
    issue: Issue,
    ancestors: tuple[IssueRef, ...],
) -> PlanLink | None:
    if issue.design:
        section = (
            "EPIC PLAN" if issue.parent_id and issue.tier == BeadTier.EPIC else "PLAN"
        )
        return PlanLink(
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
    return PlanLink(
        section=section,
        source="parent",
        path=resolved_parent.design,
        from_ref=ancestors[0],
    )


def _issue_ref(issue: Issue) -> IssueRef:
    return IssueRef(issue_id=issue.id, issue=issue)


def _unresolved_ref(issue_id: str) -> IssueRef:
    return IssueRef(issue_id=issue_id, issue=None)


__all__ = ["IssueDetail", "IssueDetailIndex", "IssueRef", "resolve_issue_detail"]
