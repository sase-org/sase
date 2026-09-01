"""TUI orchestration for AXE config add and edit actions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.axe.config_backend import AxeEntrySelector

from ...modals import (
    AxeAddChooserModal,
    AxeEntryEditorModal,
    AxeEntryEditorResult,
    AxeLumberjackPickerModal,
    AxeNewEntryDraft,
    AxeNewEntryIdentityModal,
    AxeScriptChoice,
    AxeScriptPickerModal,
    stable_chop_name,
)
from ...modals.config_commit import (
    ConfigCommitOffer,
    build_config_commit_offer,
    push_config_commit_prompt,
    submit_config_commit_task,
)
from ...util.pump_tasks import spawn_pump_free_task
from ..axe_display._loaders import AxeItemKey, selected_axe_item_key
from ._backend import (
    AxeAppliedConfigOutcome,
    AxeConfigActionInventory,
    AxeEditorSession,
    axe_base_chop_identities,
    axe_lumberjack_names,
    load_axe_config_action_inventory,
)


@dataclass(frozen=True)
class _PendingAxeSelection:
    """One refresh-time selection intent guarded by the previous selection."""

    target_key: AxeItemKey
    guard_key: AxeItemKey | None


class AxeConfigActionsMixin:
    """ACE action surface for contextual AXE adds and exact config edits."""

    _axe_items: list[Any]
    _axe_pending_selection: Any
    _axe_config_restart_saved_path: str | None

    if TYPE_CHECKING:

        def notify(
            self,
            message: str,
            *,
            title: str = "",
            severity: Literal["information", "warning", "error"] = "information",
            timeout: float | None = None,
            markup: bool = True,
        ) -> None: ...

    def action_add_axe_item(self) -> None:
        if self.current_tab != "axe":  # type: ignore[attr-defined]
            return
        guard = self._selected_axe_config_key()
        contextual_parent: str | None = None
        if guard is not None and guard[0] == "lumberjack":
            contextual_parent = guard[1]
        elif guard is not None and guard[0] == "chop":
            contextual_parent = guard[1]

        def chosen(kind: str | None) -> None:
            if kind == "lumberjack":
                self._start_axe_config_inventory_load(
                    "new_lumberjack", guard=guard, parent=None
                )
            elif kind == "chop" and contextual_parent is not None:
                self._start_axe_config_inventory_load(
                    "new_chop", guard=guard, parent=contextual_parent
                )
            elif kind == "chop":
                self._choose_cached_axe_parent(guard)

        self.push_screen(  # type: ignore[attr-defined]
            AxeAddChooserModal(contextual_parent), chosen
        )

    def _choose_cached_axe_parent(self, guard: AxeItemKey | None) -> None:
        names = tuple(getattr(self, "_axe_lumberjack_names", ()))
        if not names:
            self.notify(  # type: ignore[attr-defined]
                "Add a lumberjack before adding a chop", severity="warning"
            )
            return

        def selected(parent: str | None) -> None:
            if parent:
                self._start_axe_config_inventory_load(
                    "new_chop", guard=guard, parent=parent
                )

        self.push_screen(AxeLumberjackPickerModal(names), selected)  # type: ignore[attr-defined]

    def _open_selected_axe_entry_editor(self) -> None:
        if self.current_tab != "axe":  # type: ignore[attr-defined]
            return
        key = self._selected_axe_config_key()
        if key is None or key[0] == "bgcmd":
            self.notify("No AXE config row selected", severity="warning")  # type: ignore[attr-defined]
            return
        self._start_axe_config_inventory_load("edit", guard=key, parent=None)

    def _selected_axe_config_key(self) -> AxeItemKey | None:
        return selected_axe_item_key(  # type: ignore[attr-defined]
            self._axe_items,
            self.current_idx,  # type: ignore[attr-defined]
        )

    def _start_axe_config_inventory_load(
        self,
        purpose: Literal["edit", "new_lumberjack", "new_chop"],
        *,
        guard: AxeItemKey | None,
        parent: str | None,
    ) -> None:
        self.notify("Loading AXE configuration…")  # type: ignore[attr-defined]
        spawn_pump_free_task(
            self,
            self._load_axe_config_inventory_async(purpose, guard=guard, parent=parent),
            name="sase-axe-config-action-load",
            registry_attr="_pump_free_async_tasks",
        )

    async def _load_axe_config_inventory_async(
        self,
        purpose: Literal["edit", "new_lumberjack", "new_chop"],
        *,
        guard: AxeItemKey | None,
        parent: str | None,
    ) -> None:
        try:
            inventory = await asyncio.to_thread(load_axe_config_action_inventory)
        except Exception as exc:
            if getattr(self, "is_mounted", True):
                self.notify(f"Could not load AXE config: {exc}", severity="error")  # type: ignore[attr-defined]
            return
        if not getattr(self, "is_mounted", True):
            return
        if self.current_tab != "axe" or self._selected_axe_config_key() != guard:  # type: ignore[attr-defined]
            return
        if purpose == "edit":
            self._show_axe_edit_session(inventory, guard)
        elif purpose == "new_lumberjack":
            self._show_new_lumberjack_identity(inventory)
        elif parent is not None:
            self._show_axe_script_picker(inventory, parent)

    def _show_axe_edit_session(
        self,
        inventory: AxeConfigActionInventory,
        key: AxeItemKey | None,
    ) -> None:
        if key is None:
            return
        generated_instance: str | None = None
        generated_warning: str | None = None
        if key[0] == "lumberjack":
            selector = AxeEntrySelector.lumberjack_entry(key[1])
        elif key[0] == "chop":
            snapshot = self._axe_chop_snapshots.get((key[1], key[2]))  # type: ignore[attr-defined]
            base_name = (
                snapshot.base_chop_name
                if snapshot is not None and snapshot.base_chop_name
                else key[2]
            )
            selector = AxeEntrySelector.chop_entry(key[1], base_name)
            if snapshot is not None and snapshot.generated:
                generated_instance = key[2]
                generated_warning = (
                    f"Editing base chop {base_name!r} affects every generated instance."
                )
        else:
            return
        session = AxeEditorSession(
            inventory=inventory,
            selector=selector,
            display_target=key,
            generated_instance=generated_instance,
            generated_warning=generated_warning,
        )
        self._push_axe_editor_session(session)

    def _show_new_lumberjack_identity(
        self, inventory: AxeConfigActionInventory
    ) -> None:
        existing = axe_lumberjack_names(inventory.composition)

        def identified(draft: AxeNewEntryDraft | None) -> None:
            if draft is None:
                return
            selector = AxeEntrySelector.lumberjack_entry(draft.name)
            self._push_axe_editor_session(
                AxeEditorSession(
                    inventory=inventory,
                    selector=selector,
                    display_target=("lumberjack", draft.name),
                    new_entry=True,
                    initial_values={"interval": 1},
                    initial_touched=("interval",),
                )
            )

        self.push_screen(  # type: ignore[attr-defined]
            AxeNewEntryIdentityModal(
                kind="lumberjack",
                initial_name="new_lumberjack",
                lumberjack_names=existing,
            ),
            identified,
        )

    def _show_axe_script_picker(
        self, inventory: AxeConfigActionInventory, parent: str
    ) -> None:
        def selected(choice: AxeScriptChoice | None) -> None:
            if choice is None:
                return
            script = choice.name if not choice.custom else "sase_chop_"
            name = stable_chop_name(script) if not choice.custom else "new_chop"
            self._show_new_chop_identity(
                inventory,
                parent=parent,
                initial_name=name,
                initial_script=script,
            )

        self.push_screen(AxeScriptPickerModal(inventory.chop_inventory), selected)  # type: ignore[attr-defined]

    def _show_new_chop_identity(
        self,
        inventory: AxeConfigActionInventory,
        *,
        parent: str,
        initial_name: str,
        initial_script: str,
    ) -> None:
        identities = axe_base_chop_identities(inventory.composition)

        def identified(draft: AxeNewEntryDraft | None) -> None:
            if draft is None or draft.script is None:
                return
            selector = AxeEntrySelector.chop_entry(parent, draft.name)
            self._push_axe_editor_session(
                AxeEditorSession(
                    inventory=inventory,
                    selector=selector,
                    display_target=("chop", parent, draft.name),
                    new_entry=True,
                    initial_values={"script": draft.script},
                    initial_touched=("script",),
                )
            )

        self.push_screen(  # type: ignore[attr-defined]
            AxeNewEntryIdentityModal(
                kind="chop",
                lumberjack=parent,
                initial_name=initial_name,
                initial_script=initial_script,
                base_chop_identities=identities,
            ),
            identified,
        )

    def _push_axe_editor_session(self, session: AxeEditorSession) -> None:
        try:
            seed = session.seed()
        except Exception as exc:
            self.notify(f"Could not edit AXE config: {exc}", severity="error")  # type: ignore[attr-defined]
            return

        def finished(result: AxeEntryEditorResult | None) -> None:
            if result is not None:
                self._finish_axe_config_write(session, result)

        self.push_screen(  # type: ignore[attr-defined]
            AxeEntryEditorModal(
                seed,
                plan_callback=session.plan,
                apply_callback=session.apply,
                reload_callback=session.reload,
            ),
            finished,
        )

    def _finish_axe_config_write(
        self, session: AxeEditorSession, result: AxeEntryEditorResult
    ) -> None:
        outcome = result.applied
        if not isinstance(outcome, AxeAppliedConfigOutcome):
            self.notify(
                "AXE config saved, but the write result was incomplete",
                severity="warning",
            )  # type: ignore[attr-defined]
            self._schedule_axe_async_refresh()  # type: ignore[attr-defined]
            return
        guard = self._selected_axe_config_key()
        self._axe_pending_selection = _PendingAxeSelection(
            target_key=session.display_target,
            guard_key=guard,
        )
        self._schedule_axe_async_refresh()  # type: ignore[attr-defined]
        path = outcome.applied.path
        if outcome.chezmoi_warning:
            self.notify(outcome.chezmoi_warning, severity="warning")  # type: ignore[attr-defined]

        if result.restart_requested:
            if not outcome.axe_running:
                self.notify(
                    f"Config saved to {path}; AXE stopped before restart, so it was not started",
                    severity="warning",
                )  # type: ignore[attr-defined]
            elif getattr(self, "_axe_worker", None) is not None:
                self.notify(
                    f"Config saved to {path}, but AXE is already changing state; restart it when that finishes",
                    severity="warning",
                )  # type: ignore[attr-defined]
            else:
                self._axe_config_restart_saved_path = path
                self._restart_axe_daemon(source="ace AXE config edit")  # type: ignore[attr-defined]
        elif outcome.axe_running:
            self.notify(
                f"Config saved to {path}; running AXE keeps its previous config until restarted",
                severity="information",
            )  # type: ignore[attr-defined]
        else:
            self.notify(f"Config saved to {path}; AXE is stopped")  # type: ignore[attr-defined]
        self._schedule_axe_config_commit_offer(path)

    def _schedule_axe_config_commit_offer(self, path: str) -> None:
        spawn_pump_free_task(
            self,
            self._offer_axe_config_commit_async(path),
            name="sase-axe-config-commit-offer",
            registry_attr="_pump_free_async_tasks",
        )

    async def _offer_axe_config_commit_async(self, path: str) -> None:
        offer = await asyncio.to_thread(
            build_config_commit_offer,
            path,
            subject="Update AXE configuration",
        )
        if offer is None or not getattr(self, "is_mounted", True):
            return

        def confirmed(value: ConfigCommitOffer) -> None:
            submit_config_commit_task(
                self,
                value,
                display_name="Commit AXE configuration",
            )

        push_config_commit_prompt(
            self,
            offer,
            message="The AXE config changed. Commit and push the written source file?",
            on_confirm=confirmed,
        )
