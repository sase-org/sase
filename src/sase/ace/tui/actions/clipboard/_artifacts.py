"""Copy targets for the non-PR Artifacts sub-tabs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Literal

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


def _copy_group_for_artifacts_subtab(subtab: str) -> str:
    from ...artifact_tabs import copy_keymap_group_for_artifacts_pane

    return copy_keymap_group_for_artifacts_pane(subtab)


_ARTIFACTS_COPY_LABELS = {
    "stitches": "Stitch",
    "patches": "Patch",
    "beads": "Bead",
}


def _copy_label_for_artifacts_subtab(subtab: str) -> str:
    from ...artifact_tabs import artifacts_pane_contract

    contract = artifacts_pane_contract(subtab)
    if contract is not None:
        return contract.label
    if subtab == "files":
        return "File"
    if subtab == "ref:plan":
        return "Plan"
    return _ARTIFACTS_COPY_LABELS.get(subtab, subtab.title())


def _document_copy_handlers_enabled(subtab: str) -> bool:
    from ...artifact_tabs import is_document_artifacts_pane

    return is_document_artifacts_pane(subtab)


def _document_copy_handlers(
    owner: Any,
    subtab_keys: dict[str, Any],
    subtab: str,
) -> dict[str, Callable[[], None]]:
    from ...artifact_tabs import artifacts_pane_contract

    contract = artifacts_pane_contract(subtab)
    if contract is None and subtab == "ref:plan":
        from ...artifact_tabs import PLAN_COPY_TARGETS

        declared = set(PLAN_COPY_TARGETS)
    else:
        declared = set(() if contract is None else contract.copy_targets)
    handlers: dict[str, Callable[[], None]] = {}
    target_map = {
        "bead_id": lambda: owner._copy_plan_target("bead_id"),
        "design": lambda: owner._copy_plan_target("design"),
        "path": lambda: owner._copy_plan_target("path"),
        "title": lambda: owner._copy_plan_target("title"),
        "body": lambda: owner._copy_plan_target("body"),
    }
    for target, handler in target_map.items():
        if target in declared and target in subtab_keys:
            handlers[str(subtab_keys[target])] = handler
    return handlers


class ClipboardArtifactsMixin(
    ClipboardArtifactReferencesMixin,
    ClipboardArtifactTargetsMixin,
):
    """Dispatch copy-mode keys using the visible Artifacts entry."""

    def action_artifacts_copy_reference(self) -> None:
        """Copy the selected row's canonical ``@<kind>:...`` reference.

        The one contract-verb replacement for the per-pane ``y`` actions
        every Artifacts pane used to bind separately (``stitches_copy_sha``,
        ``beads_copy_bug``, ``files_copy_reference``): every pane now copies
        the same paste-ready ``@`` reference on ``y``. Sha/bug/id/etc.
        copies remain reachable through copy mode (``%``).
        """
        if self.current_tab != ARTIFACTS_TAB:  # type: ignore[attr-defined]
            return
        if self.current_artifacts_pane_key == "patches":  # type: ignore[attr-defined]
            self._copy_patch_reference()  # type: ignore[attr-defined]
            return
        self._run_artifact_reference_action(handoff=False)

    def _non_pr_artifacts_copy_active(self) -> bool:
        return (
            self.current_tab
            in {
                ARTIFACTS_TAB,
                "patches",
                "changespecs",  # legacy compatibility alias
            }
            and self.current_artifacts_pane_key != "patches"
        )

    def _handle_artifacts_copy_key(self, key: str) -> bool:
        subtab = self.current_artifacts_pane_key
        group_name = _copy_group_for_artifacts_subtab(str(subtab))
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
        if subtab == "stitches":
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
        elif _document_copy_handlers_enabled(str(subtab)):
            handlers = _document_copy_handlers(self, subtab_keys, str(subtab))
        elif subtab == "beads":
            handlers = {
                str(subtab_keys["id"]): lambda: self._copy_bead_target("id"),
                str(subtab_keys["title"]): lambda: self._copy_bead_target("title"),
                str(subtab_keys["body"]): lambda: self._copy_bead_target("body"),
                str(subtab_keys["design"]): lambda: self._copy_bead_target("design"),
                str(subtab_keys["bug"]): lambda: self.action_beads_copy_bug(),  # type: ignore[attr-defined]
            }
        elif subtab == "agents":
            handlers = {
                str(subtab_keys["name"]): lambda: self._copy_agent_target("name"),
                str(subtab_keys["path"]): lambda: self._copy_agent_target("path"),
                str(subtab_keys["chat"]): lambda: self._copy_agent_target("chat"),
                str(subtab_keys["prompt"]): lambda: self._copy_agent_target("prompt"),
            }
        else:
            handlers = {
                str(subtab_keys["contents"]): lambda: self._copy_file_target(
                    "contents"
                ),
                str(subtab_keys["path"]): lambda: self._copy_file_target("path"),
                str(subtab_keys["source"]): lambda: self._copy_file_target("source"),
                str(subtab_keys["label"]): lambda: self._copy_file_target("label"),
            }

        handler = handlers.get(key)
        if handler is None:
            key_list = ", ".join(
                key_display_name(value)
                for value in subtab_keys.values()
                if isinstance(value, str)
            )
            self.notify(  # type: ignore[attr-defined]
                f"Unknown copy key ({_copy_label_for_artifacts_subtab(str(subtab))}: "
                f"{key_list})",
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
