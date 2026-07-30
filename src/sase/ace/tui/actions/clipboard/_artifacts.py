"""Copy targets for the non-PR Artifacts sub-tabs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from sase.artifact_refs import artifact_ref_context

from ...keymaps import key_display_name
from ...tab_order import ARTIFACTS_TAB
from ...util.pump_tasks import spawn_pump_free_task
from ._artifact_references import (
    ArtifactReferenceItem as _ArtifactReferenceItem,
    ArtifactReferenceSelection as _ArtifactReferenceSelection,
    ClipboardArtifactReferencesMixin,
    resolve_artifact_references,
)
from ._artifact_targets import ClipboardArtifactTargetsMixin
from ._delivery import deliver_copy
from ._helpers import format_multi_copy_content


class ClipboardArtifactsMixin(
    ClipboardArtifactReferencesMixin,
    ClipboardArtifactTargetsMixin,
):
    """Dispatch copy-mode keys using the visible Artifacts entry."""

    def _non_pr_artifacts_copy_active(self) -> bool:
        return self.current_tab == ARTIFACTS_TAB and self.current_artifacts_subtab in {
            "commits",
            "plans",
            "chats",
            "bugs",
            "files",
        }

    def _handle_artifacts_copy_key(self, key: str) -> bool:
        subtab = self.current_artifacts_subtab
        group_name = f"artifacts_{subtab}"
        subtab_keys = self._keymap_registry.copy_mode.keys.get(group_name, {})
        assert isinstance(subtab_keys, dict)

        if key == subtab_keys["snapshot"]:
            self._copy_snapshot()  # type: ignore[attr-defined]
            return True
        if key == subtab_keys["reference"]:
            self._run_artifact_reference_action(handoff=False)
            return True
        if key == subtab_keys["handoff"]:
            self._run_artifact_reference_action(handoff=True)
            return True

        handlers: dict[str, Callable[[], None]]
        if subtab == "commits":
            handlers = {
                str(subtab_keys["sha"]): lambda: self._copy_commit_target("sha"),
                str(subtab_keys["message"]): lambda: self._copy_commit_target(
                    "message"
                ),
                str(subtab_keys["repo_sha"]): lambda: self._copy_commit_target(
                    "repo_sha"
                ),
                str(subtab_keys["plan"]): lambda: self._copy_commit_target("plan"),
            }
        elif subtab == "plans":
            handlers = {
                str(subtab_keys["path"]): lambda: self._copy_plan_target("path"),
                str(subtab_keys["title"]): lambda: self._copy_plan_target("title"),
                str(subtab_keys["body"]): lambda: self._copy_plan_target("body"),
            }
        elif subtab == "chats":
            handlers = {
                str(subtab_keys["path"]): lambda: self._copy_chat_target("path"),
                str(subtab_keys["agent"]): lambda: self._copy_chat_target("agent"),
                str(subtab_keys["transcript"]): lambda: self._copy_chat_target(
                    "transcript"
                ),
            }
        elif subtab == "files":
            handlers = {}
        else:
            handlers = {
                str(subtab_keys["number"]): lambda: self._copy_bug_target("number"),
                str(subtab_keys["url"]): lambda: self._copy_bug_target("url"),
                str(subtab_keys["title"]): lambda: self._copy_bug_target("title"),
                str(subtab_keys["prompt"]): lambda: self._copy_bug_target("prompt"),
            }

        handler = handlers.get(key)
        if handler is None:
            key_list = ", ".join(
                key_display_name(value)
                for value in subtab_keys.values()
                if isinstance(value, str)
            )
            self.notify(  # type: ignore[attr-defined]
                f"Unknown copy key ({subtab.title()}: {key_list})",
                severity="warning",
            )
            return False
        handler()
        return True

    def _run_artifact_reference_action(self, *, handoff: bool) -> None:
        selection = self._capture_artifact_reference_selection()
        if selection is None:
            return

        async def act() -> None:
            try:
                references = await asyncio.to_thread(
                    _resolve_artifact_references,
                    selection,
                )
            except Exception as exc:
                self.notify(  # type: ignore[attr-defined]
                    str(exc),
                    severity="warning",
                )
                return

            if handoff:
                project = selection.prompt_project
                display_name = selection.prompt_display_name
                project_file = selection.prompt_project_file
                if project is None or display_name is None:
                    self.notify(  # type: ignore[attr-defined]
                        "Pick one project before handing artifact references to an agent",
                        severity="warning",
                    )
                    return
                if not project_file:
                    self.notify(  # type: ignore[attr-defined]
                        f"{display_name} has no launchable ProjectSpec",
                        severity="warning",
                    )
                    return
                try:
                    from sase.workspace_provider import detect_workflow_type

                    workflow_type = await asyncio.to_thread(
                        detect_workflow_type,
                        project_file,
                    )
                except Exception as exc:
                    self.notify(  # type: ignore[attr-defined]
                        f"Cannot start an agent for {display_name}: {exc}",
                        severity="error",
                    )
                    return
                prompt = f"#{workflow_type}:{display_name} {' '.join(references)} "
                self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
                    initial_text=prompt,
                    display_name=f"{display_name} artifact reference",
                    history_sort_key=project,
                )
                return

            content = (
                references[0]
                if not selection.marked
                else format_multi_copy_content(
                    [
                        (item.label, reference)
                        for item, reference in zip(
                            selection.items,
                            references,
                            strict=True,
                        )
                    ]
                )
            )
            count = len(references)
            await deliver_copy(
                self,
                content,
                copied_label=(
                    "artifact reference"
                    if count == 1
                    else f"{count} artifact references"
                ),
            )

        spawn_pump_free_task(
            self,
            act(),
            name=(
                "sase-artifact-reference-handoff"
                if handoff
                else "sase-artifact-reference-copy"
            ),
            registry_attr="_pump_free_async_tasks",
        )


def _resolve_artifact_references(
    selection: _ArtifactReferenceSelection,
) -> tuple[str, ...]:
    """Compatibility wrapper around the extracted reference resolver."""
    return resolve_artifact_references(
        selection,
        context_factory=artifact_ref_context,
    )


__all__ = ["ClipboardArtifactsMixin"]
