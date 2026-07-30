"""Copy targets for the non-PR Artifacts sub-tabs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Literal

from ...keymaps import key_display_name
from ...tab_order import ARTIFACTS_TAB
from ...util.pump_tasks import spawn_pump_free_task
from ._artifact_references import (
    ArtifactReferenceItem as _ArtifactReferenceItem,
    ArtifactReferenceSelection as _ArtifactReferenceSelection,
    ClipboardArtifactReferencesMixin,
)
from ._artifact_reference_resolution import (
    resolve_artifact_selection as _resolve_artifact_selection,
)
from ._artifact_targets import ClipboardArtifactTargetsMixin
from ._delivery import deliver_copy
from ._representations import (
    ResolvedArtifactItem as _ResolvedArtifactItem,
    ResolvedArtifactSelection as _ResolvedArtifactSelection,
    artifact_representation_label as _artifact_representation_label,
    format_artifact_representation as _format_artifact_representation,
)


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

        if key == subtab_keys.get("snapshot"):
            self._copy_snapshot()  # type: ignore[attr-defined]
            return True
        if key == subtab_keys.get("reference"):
            self._run_artifact_reference_action(handoff=False)
            return True
        if key == subtab_keys.get("handoff"):
            self._run_artifact_reference_action(handoff=True)
            return True
        if key == subtab_keys.get("link"):
            self._run_artifact_representation_action("link")
            return True
        if key == subtab_keys.get("json"):
            self._run_artifact_representation_action("json")
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
        self._run_artifact_representation_action("reference", handoff=handoff)

    def _run_artifact_representation_action(
        self,
        representation: Literal["reference", "link", "json"],
        *,
        handoff: bool = False,
    ) -> None:
        selection = self._capture_artifact_reference_selection()
        if selection is None:
            return

        async def act() -> None:
            try:
                resolved = await asyncio.to_thread(
                    _resolve_artifact_selection,
                    selection,
                    include_metadata=representation == "json",
                )
            except Exception as exc:
                self.notify(  # type: ignore[attr-defined]
                    str(exc),
                    severity="warning",
                )
                return

            if not resolved.items:
                message = (
                    resolved.failures[0]
                    if resolved.failures
                    else f"No {selection.subtab} entries have a reference"
                )
                self.notify(message, severity="warning")  # type: ignore[attr-defined]
                return

            references = tuple(f"@{item.reference}" for item in resolved.items)
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
                if resolved.failures:
                    count = len(resolved.failures)
                    noun = "entry" if count == 1 else "entries"
                    self.notify(  # type: ignore[attr-defined]
                        f"Prepared {len(resolved.items)} references — "
                        f"{count} {noun} have no reference",
                        severity="warning",
                    )
                return

            content = _format_artifact_representation(
                representation,
                resolved.items,
                marked=selection.marked,
            )
            copied_label = _artifact_representation_label(
                representation,
                resolved.items,
                marked=selection.marked,
                failure_count=len(resolved.failures),
            )
            await deliver_copy(
                self,
                content,
                copied_label=copied_label,
            )

        spawn_pump_free_task(
            self,
            act(),
            name=(
                "sase-artifact-reference-handoff"
                if handoff
                else f"sase-artifact-{representation}-copy"
            ),
            registry_attr="_pump_free_async_tasks",
        )


__all__ = ["ClipboardArtifactsMixin"]
