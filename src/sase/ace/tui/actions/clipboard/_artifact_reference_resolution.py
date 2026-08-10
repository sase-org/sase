"""Capture and resolve canonical references for Artifacts copy targets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.artifact_cli.references import artifact_file_json_dict, resolve_cli_reference
from sase.core.artifact_file_types import ArtifactFile
from sase.artifact_refs import (
    artifact_ref_context,
    reference_for_agent_name,
    reference_for_entry_target,
)

from ...widgets.artifacts.chats_list import chat_row_target
from ...widgets.artifacts.beads_list import bead_row_target
from ...widgets.artifacts.plans_list import plan_row_target
from ._representations import (
    ArtifactReferenceItem,
    ArtifactReferenceSelection,
    ResolvedArtifactItem,
    ResolvedArtifactSelection,
)


def reference_items_for_targets(
    subtab: str,
    pane: Any,
    targets: tuple[tuple[str, ...], ...],
) -> tuple[ArtifactReferenceItem, ...]:
    """Capture stable reference inputs and human labels for visible rows."""

    cwd = str(Path.cwd())
    items: list[ArtifactReferenceItem] = []
    if subtab == "stitches":
        result = getattr(pane, "result", None)
        entries = () if result is None else result.commits
        commits_by_target: dict[tuple[str, ...], Any] = {
            ("commit", entry.repo, entry.commit.full_id): entry for entry in entries
        }
        project = getattr(pane, "project_scope", None)
        for target in targets:
            entry = commits_by_target.get(target)
            label = (
                f"{target[1]}@{target[2][:7]}"
                if entry is None
                else f"{entry.repo}@{entry.commit.short_id}"
            )
            subject = (
                label
                if entry is None
                else str(getattr(entry.commit, "subject", "") or label)
            )
            items.append(
                ArtifactReferenceItem(
                    label,
                    target,
                    None,
                    project,
                    cwd,
                    markdown_label=subject,
                    kind_label="commit",
                )
            )
    elif subtab == "beads":
        beads_by_target: dict[tuple[str, ...], Any] = {
            bead_row_target(row): row for row in getattr(pane, "_rows", {}).values()
        }
        snapshot = getattr(pane, "_snapshot", None)
        workspace_dirs = getattr(snapshot, "workspace_dirs", {})
        for target in targets:
            row = beads_by_target.get(target)
            if row is None:
                continue
            project = row.project
            items.append(
                ArtifactReferenceItem(
                    row.row_id,
                    target,
                    row,
                    project,
                    workspace_dirs.get(project) or cwd,
                    markdown_label=str(row.issue.title or row.row_id),
                    kind_label="bead",
                )
            )
    elif subtab == "plans":
        plans_by_target: dict[tuple[str, ...], Any] = {
            plan_row_target(row): row for row in getattr(pane, "_rows", {}).values()
        }
        snapshot = getattr(pane, "_snapshot", None)
        workspace_dirs = getattr(snapshot, "workspace_dirs", {})
        for target in targets:
            row = plans_by_target.get(target)
            if row is None:
                continue
            project = row.project
            workspace_dir = workspace_dirs.get(project) or cwd
            items.append(
                ArtifactReferenceItem(
                    row.row_id,
                    target,
                    row,
                    project,
                    workspace_dir,
                    markdown_label=_plan_markdown_label(row),
                    kind_label="plan",
                )
            )
    elif subtab == "chats":
        chats_by_target: dict[tuple[str, ...], Any] = {
            chat_row_target(row): row.entry
            for row in getattr(pane, "_rows", {}).values()
        }
        selected = getattr(pane, "selected_entry", None)
        if selected is not None:
            chats_by_target.setdefault(("chat", selected.absolute_path), selected)
        project = getattr(pane, "project_scope", None)
        for target in targets:
            entry = chats_by_target.get(target)
            if entry is None:
                continue
            items.append(
                ArtifactReferenceItem(
                    entry.basename,
                    target,
                    None,
                    project,
                    cwd,
                    markdown_label=entry.basename,
                    kind_label="chat",
                )
            )
    elif subtab in {"other", "files"}:
        entries = pane.entries_for_targets(targets)
        entries_by_target: dict[tuple[str, ...], Any] = {
            ("file", entry.id): entry for entry in entries
        }
        for target in targets:
            entry = entries_by_target.get(target)
            if entry is None:
                continue
            items.append(
                ArtifactReferenceItem(
                    entry.label,
                    target,
                    entry,
                    entry.project,
                    entry.workspace_dir or cwd,
                    markdown_label=entry.label,
                    kind_label="artifact file",
                )
            )
    else:
        issues = getattr(pane, "issues", ())
        issues_by_target: dict[tuple[str, ...], Any] = {
            pane._issue_target(issue): issue for issue in issues
        }
        selected = getattr(pane, "selected_issue", None)
        if selected is not None:
            issues_by_target.setdefault(pane._issue_target(selected), selected)
        for target in targets:
            issue = issues_by_target.get(target)
            if issue is None:
                continue
            items.append(
                ArtifactReferenceItem(
                    f"#{issue.number}",
                    target,
                    None,
                    target[1],
                    cwd,
                    markdown_label=str(issue.title),
                    kind_label="bug",
                )
            )
    return tuple(items)


def reference_for_agent_row(agent: Any) -> str | None:
    """Return a durable reference for one concrete Agents-tab row."""

    name = getattr(agent, "agent_name", None)
    if not isinstance(name, str) or not name:
        return None
    return reference_for_agent_name(name)


def resolve_artifact_selection(
    selection: ArtifactReferenceSelection,
    *,
    include_metadata: bool,
) -> ResolvedArtifactSelection:
    """Resolve representable entries while retaining per-item failures."""

    contexts: dict[tuple[str, str | None], Any] = {}
    resolved_items: list[ResolvedArtifactItem] = []
    failures: list[str] = []
    for item in selection.items:
        if selection.subtab in {"other", "files"}:
            reference = reference_for_entry_target(
                "files",
                item.target,
                context=None,
                row=item.row,
            )
            if reference is None:
                failures.append(
                    _missing_reference_message(selection.subtab, item.label)
                )
                continue
            metadata = (
                artifact_file_json_dict(item.row)
                if include_metadata and isinstance(item.row, ArtifactFile)
                else None
            )
            resolved_items.append(ResolvedArtifactItem(item, reference, metadata))
            continue
        context_key = (item.workspace_dir, item.project)
        context = contexts.get(context_key)
        if context is None:
            context = artifact_ref_context(
                item.workspace_dir,
                _workspace_num(item.workspace_dir),
                item.project,
            )
            contexts[context_key] = context
        reference = reference_for_entry_target(
            selection.subtab,
            item.target,
            context=context,
            row=item.row,
        )
        if reference is None:
            failures.append(_missing_reference_message(selection.subtab, item.label))
            continue
        try:
            metadata = (
                resolve_cli_reference(reference, context=context).to_json_dict()
                if include_metadata
                else None
            )
        except Exception:
            failures.append(_missing_reference_message(selection.subtab, item.label))
            continue
        resolved_items.append(ResolvedArtifactItem(item, reference, metadata))
    return ResolvedArtifactSelection(tuple(resolved_items), tuple(failures))


def _workspace_num(workspace_dir: str) -> int:
    try:
        from sase.workspace_provider import find_marker_from_cwd

        found = find_marker_from_cwd(workspace_dir)
    except Exception:
        return 1
    if found is None:
        return 1
    workspace_num = found[1].workspace_num
    return workspace_num if isinstance(workspace_num, int) and workspace_num > 0 else 1


def _missing_reference_message(subtab: str, label: str) -> str:
    if subtab == "chats":
        reason = "it is an imported transcript outside the chats root"
    elif subtab == "plans":
        reason = "it has no canonical document reference"
    elif subtab == "other":
        reason = "it has no durable file id"
    else:
        reason = "its artifact identity is incomplete"
    return f"{label} cannot be referenced because {reason}"


def _plan_markdown_label(row: Any) -> str:
    if row.proposal is not None:
        return str(row.proposal.title or row.row_id)
    if row.active is not None:
        return str(row.active.document.frontmatter.get("title") or row.row_id)
    if row.archive is not None:
        plan = row.archive.plan
        return str(plan.title or plan.name or row.row_id)
    return str(row.row_id)


__all__ = ["reference_items_for_targets", "resolve_artifact_selection"]
