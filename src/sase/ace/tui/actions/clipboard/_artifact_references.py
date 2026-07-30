"""Selection and resolution helpers for Artifacts copy-mode references."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.artifact_refs import reference_for_entry_target

from ...widgets.artifacts.chats_list import chat_row_target
from ...widgets.artifacts.plans_list import plan_row_target
from ._base import ClipboardBase


@dataclass(frozen=True, slots=True)
class ArtifactReferenceItem:
    label: str
    target: tuple[str, ...]
    row: object | None
    project: str | None
    workspace_dir: str


@dataclass(frozen=True, slots=True)
class ArtifactReferenceSelection:
    subtab: str
    items: tuple[ArtifactReferenceItem, ...]
    marked: bool
    prompt_project: str | None
    prompt_display_name: str | None
    prompt_project_file: str | None


class ClipboardArtifactReferencesMixin(ClipboardBase):
    """Capture the visible Artifacts entries used by reference actions."""

    def _capture_artifact_reference_selection(
        self,
    ) -> ArtifactReferenceSelection | None:
        subtab = self.current_artifacts_subtab
        pane = {
            "commits": self._commits_pane,  # type: ignore[attr-defined]
            "plans": self._plans_pane,  # type: ignore[attr-defined]
            "chats": self._chats_pane,  # type: ignore[attr-defined]
            "bugs": self._bugs_pane,  # type: ignore[attr-defined]
            "files": self._files_pane,  # type: ignore[attr-defined]
        }[subtab]()
        if pane is None:
            self.notify(f"No {subtab} entry selected", severity="warning")  # type: ignore[attr-defined]
            return None

        marked_targets = self._visible_marked_targets(pane)  # type: ignore[attr-defined]
        marked = marked_targets is not None
        if marked:
            targets = marked_targets
        else:
            target = pane.selected_entry_target()
            targets = () if target is None else (target,)
        if not targets:
            if not marked:
                self.notify(f"No {subtab} entry selected", severity="warning")  # type: ignore[attr-defined]
            return None

        items = _reference_items_for_targets(subtab, pane, targets)
        if not items:
            self.notify(  # type: ignore[attr-defined]
                f"No visible {subtab} entries are available",
                severity="warning",
            )
            return None

        projects = tuple(
            dict.fromkeys(item.project for item in items if item.project is not None)
        )
        prompt_project = projects[0] if len(projects) == 1 else None
        display_name, project_file = self._artifact_prompt_project_metadata(
            pane,
            prompt_project,
        )
        return ArtifactReferenceSelection(
            subtab=subtab,
            items=items,
            marked=marked,
            prompt_project=prompt_project,
            prompt_display_name=display_name,
            prompt_project_file=project_file,
        )

    def _artifact_prompt_project_metadata(
        self,
        pane: Any,
        project: str | None,
    ) -> tuple[str | None, str | None]:
        if project is None:
            return None, None
        display_name = project
        project_file: str | None = None

        snapshot = getattr(pane, "snapshot", None) or getattr(
            pane,
            "_snapshot",
            None,
        )
        snapshot_display = getattr(snapshot, "display_name", None)
        if isinstance(snapshot_display, str) and snapshot_display:
            display_name = snapshot_display
        display_names = getattr(snapshot, "display_names", None)
        if isinstance(display_names, dict):
            display_name = str(display_names.get(project, display_name))
        pane_display = getattr(pane, "_project_display_name", None)
        if isinstance(pane_display, str) and pane_display:
            display_name = pane_display
        pane_project_file = getattr(pane, "project_file", None)
        if isinstance(pane_project_file, str) and pane_project_file:
            project_file = pane_project_file

        choices = getattr(self, "_artifacts_project_choices", None)
        if choices is not None:
            for choice in getattr(choices, "choices", ()):
                if project not in {choice.project_key, choice.display_name}:
                    continue
                project = choice.project_key
                display_name = choice.display_name
                project_file = getattr(choices, "project_files", {}).get(project)
                break
            else:
                project_file = getattr(choices, "project_files", {}).get(project)
                display_name = getattr(choices, "display_names", {}).get(
                    project,
                    display_name,
                )
        return display_name, project_file


def _reference_items_for_targets(
    subtab: str,
    pane: Any,
    targets: tuple[tuple[str, ...], ...],
) -> tuple[ArtifactReferenceItem, ...]:
    cwd = str(Path.cwd())
    items: list[ArtifactReferenceItem] = []
    if subtab == "commits":
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
            items.append(ArtifactReferenceItem(label, target, None, project, cwd))
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
                )
            )
    return tuple(items)


def resolve_artifact_references(
    selection: ArtifactReferenceSelection,
    *,
    context_factory: Callable[[str, int, str | None], Any],
) -> tuple[str, ...]:
    """Resolve captured entries into their canonical artifact references."""
    contexts: dict[tuple[str, str | None], Any] = {}
    references: list[str] = []
    for item in selection.items:
        context_key = (item.workspace_dir, item.project)
        context = contexts.get(context_key)
        if context is None:
            context = context_factory(
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
            raise ValueError(_missing_reference_message(selection.subtab, item.label))
        references.append(f"@{reference}")
    return tuple(references)


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
    else:
        reason = "its artifact identity is incomplete"
    return f"{label} cannot be referenced because {reason}"
