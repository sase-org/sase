"""Artifact selection context for the ACE Copy as palette."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from ...commands import CommandContext
from ._palette_artifact_previews import artifact_target_state
from ._palette_helpers import notify_copy_warning
from ._palette_registry import context_from_registry

if TYPE_CHECKING:
    from ...modals.copy_as_types import CopyAsContext


def build_artifacts_context(app: Any, subtab: str) -> CopyAsContext | None:
    pane = _artifact_pane(app, subtab)
    if pane is None:
        notify_copy_warning(app, f"No {subtab} entry to copy")
        return None

    visible_targets = _entry_targets(pane)
    all_marks = getattr(app, "_artifacts_marked_targets", {})
    marks = all_marks.get(subtab, set()) if isinstance(all_marks, dict) else set()
    marked_targets = tuple(target for target in visible_targets if target in marks)
    marked = bool(marks)
    if marked and not marked_targets:
        notify_copy_warning(app, f"No marked {subtab} entries are visible")
        return None

    selected_target = _selected_entry_target(pane)
    selected_objects = _artifact_objects(
        pane,
        subtab,
        marked_targets
        if marked
        else (() if selected_target is None else (selected_target,)),
    )
    if not marked:
        selected = _selected_artifact_object(pane, subtab)
        if selected is not None and not selected_objects:
            selected_objects = (selected,)
        if selected_target is None and not selected_objects:
            notify_copy_warning(app, f"No {subtab} entry to copy")
            return None

    count = len(marked_targets) if marked else 1
    available, previews = artifact_target_state(
        group=f"artifacts_{subtab}",
        subtab=subtab,
        pane=pane,
        objects=selected_objects,
        marked=marked,
        count=count,
    )
    ctx = CommandContext(
        tab="artifacts",
        artifacts_subtab=subtab,  # type: ignore[arg-type]
        artifact_selection_present=True,
        artifact_available_targets=frozenset(available),
    )
    display_name = _artifact_display_name(pane, selected_objects)
    if marked:
        subtitle = f"{count} marked {subtab}"
        if display_name:
            subtitle += f" · {display_name}"
    else:
        identity = _artifact_identity(
            subtab, selected_objects[0] if selected_objects else None
        )
        subtitle = " · ".join(part for part in (display_name, identity) if part)
        if not subtitle:
            subtitle = f"Selected {subtab[:-1] if subtab.endswith('s') else subtab}"

    return context_from_registry(
        app,
        group=f"artifacts_{subtab}",
        command_context=ctx,
        subtitle=subtitle,
        unknown_context=subtab.title(),
        previews=previews,
        marked=marked,
    )


def _artifact_pane(app: Any, subtab: str) -> Any | None:
    resolver_name = "_files_pane" if subtab == "other" else f"_{subtab}_pane"
    resolver = getattr(app, resolver_name, None)
    if not callable(resolver):
        return getattr(app, f"{subtab}_pane", None)
    try:
        return resolver()
    except Exception:
        return None


def _entry_targets(pane: Any) -> tuple[tuple[str, ...], ...]:
    resolver = getattr(pane, "entry_targets", None)
    if not callable(resolver):
        return ()
    try:
        return tuple(resolver())
    except Exception:
        return ()


def _selected_entry_target(pane: Any) -> tuple[str, ...] | None:
    resolver = getattr(pane, "selected_entry_target", None)
    if not callable(resolver):
        return None
    try:
        return resolver()
    except Exception:
        return None


def _selected_artifact_object(pane: Any, subtab: str) -> Any | None:
    if subtab == "commits":
        resolver = getattr(pane, "_selected_entry", None)
        return resolver() if callable(resolver) else None
    if subtab == "plans":
        resolver = getattr(pane, "selected_row", None)
        return resolver() if callable(resolver) else None
    if subtab in {"chats", "other"}:
        return getattr(pane, "selected_entry", None)
    if subtab == "beads":
        resolver = getattr(pane, "selected_row", None)
        return resolver() if callable(resolver) else None
    return getattr(pane, "selected_issue", None)


def _artifact_objects(
    pane: Any,
    subtab: str,
    targets: Iterable[tuple[str, ...]],
) -> tuple[Any, ...]:
    ordered_targets = tuple(targets)
    if not ordered_targets:
        return ()
    if subtab == "commits":
        result = getattr(pane, "result", None)
        candidates = () if result is None else getattr(result, "commits", ())
        commit_by_target: dict[tuple[str, ...], Any] = {
            ("commit", entry.repo, entry.commit.full_id): entry for entry in candidates
        }
        return tuple(
            commit_by_target[target]
            for target in ordered_targets
            if target in commit_by_target
        )
    if subtab in {"beads", "plans", "chats", "other"}:
        rows = getattr(pane, "_rows", {}).values()
        row_by_target: dict[tuple[str, ...], Any] = {}
        for row in rows:
            if subtab == "beads":
                from ...widgets.artifacts.beads_list import bead_row_target

                target = bead_row_target(row)
                value = row
            elif subtab == "plans":
                from ...widgets.artifacts.plans_list import plan_row_target

                target = plan_row_target(row)
                value = row
            elif subtab == "chats":
                from ...widgets.artifacts.chats_list import chat_row_target

                target = chat_row_target(row)
                value = row.entry
            else:
                from ...widgets.artifacts.files_list import file_row_target

                target = file_row_target(row)
                value = row.entry
            row_by_target[target] = value
        return tuple(
            row_by_target[target]
            for target in ordered_targets
            if target in row_by_target
        )
    issues = getattr(pane, "issues", ())
    target_for = getattr(pane, "_issue_target", None)
    if not callable(target_for):
        return ()
    issue_by_target: dict[tuple[str, ...], Any] = {
        target_for(issue): issue for issue in issues
    }
    return tuple(
        issue_by_target[target]
        for target in ordered_targets
        if target in issue_by_target
    )


def _artifact_display_name(pane: Any, objects: tuple[Any, ...]) -> str:
    direct = getattr(pane, "_project_display_name", None)
    if isinstance(direct, str) and direct:
        return direct
    snapshot = getattr(pane, "snapshot", None) or getattr(pane, "_snapshot", None)
    display = getattr(snapshot, "display_name", None)
    if isinstance(display, str) and display:
        return display
    display_names = getattr(snapshot, "display_names", None)
    project = getattr(objects[0], "project", None) if objects else None
    if isinstance(display_names, Mapping) and isinstance(project, str):
        return str(display_names.get(project, project))
    filters = getattr(pane, "filters", None)
    scope = (
        getattr(filters, "project", None)
        or getattr(pane, "project_scope", None)
        or project
    )
    return str(scope or "")


def _artifact_identity(subtab: str, value: Any | None) -> str:
    if value is None:
        return ""
    if subtab == "commits":
        commit = getattr(value, "commit", None)
        return f"{getattr(value, 'repo', '')}@{getattr(commit, 'short_id', '')}"
    if subtab == "plans":
        if getattr(value, "proposal", None) is not None:
            return str(value.proposal.title)
        if getattr(value, "active", None) is not None:
            document = value.active.document
            return str(
                document.frontmatter.get("title") or getattr(value, "row_id", "")
            )
        if getattr(value, "archive", None) is not None:
            plan = value.archive.plan
            return str(plan.title or plan.name)
        return str(getattr(value, "row_id", ""))
    if subtab == "beads":
        issue = getattr(value, "issue", None)
        if issue is None:
            return ""
        return f"{getattr(issue, 'id', '')} · {getattr(issue, 'title', '')}"
    if subtab == "chats":
        return str(getattr(value, "basename", ""))
    if subtab == "bugs":
        return f"#{getattr(value, 'number', '')} · {getattr(value, 'title', '')}"
    return str(getattr(value, "label", "") or getattr(value, "path", ""))
