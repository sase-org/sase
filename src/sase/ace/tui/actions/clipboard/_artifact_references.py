"""Selection and resolution helpers for Artifacts copy-mode references."""

from __future__ import annotations

from typing import Any

from ._artifact_reference_resolution import reference_items_for_targets
from ._base import ClipboardBase
from ._representations import ArtifactReferenceItem, ArtifactReferenceSelection


def _is_document_pane_key(subtab: str) -> bool:
    from ...artifact_tabs import is_document_artifacts_pane

    return is_document_artifacts_pane(subtab)


class ClipboardArtifactReferencesMixin(ClipboardBase):
    """Capture the visible Artifacts entries used by reference actions."""

    def _capture_artifact_reference_selection(
        self,
    ) -> ArtifactReferenceSelection | None:
        subtab = self.current_artifacts_pane_key
        if subtab == "stitches":
            resolver_name = "_commits_pane"
        elif subtab == "beads":
            resolver_name = "_beads_pane"
        elif subtab == "files":
            resolver_name = "_files_pane"
        elif _is_document_pane_key(str(subtab)):
            resolver_name = "_active_documents_pane"
        else:
            self.notify(f"No {subtab} entry selected", severity="warning")  # type: ignore[attr-defined]
            return None
        resolver = getattr(self, resolver_name, None)
        pane = resolver() if callable(resolver) else None
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

        items = reference_items_for_targets(subtab, pane, targets)
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
