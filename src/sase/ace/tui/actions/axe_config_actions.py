"""Non-blocking AXE add/edit actions backed by exact config transactions."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase.axe.chop_inventory import ChopInventory, collect_chop_inventory
from sase.axe.chop_script_runner import discover_chop_script
from sase.axe.config import load_axe_config
from sase.axe.config_backend import (
    AxeConfigComposition,
    AxeEntrySelector,
    AxeFieldOperation,
    AxeInventoryEntry,
    AxeMutationPlan,
    apply_axe_entry_edit,
    compose_axe_config,
    plan_axe_entry_edit,
)
from sase.axe.process import is_axe_running
from sase.config import AppliedResult
from sase.config.inventory import load_config_schema
from sase.config.targets import apply_chezmoi

from ..modals import (
    AxeAddChooserModal,
    AxeEntryEditorModal,
    AxeEntryEditorResult,
    AxeEntryEditorSeed,
    AxeEntryIdentity,
    AxeEntryMutationRequest,
    AxeLumberjackPickerModal,
    AxeNewEntryDraft,
    AxeNewEntryIdentityModal,
    AxeScriptChoice,
    AxeScriptPickerModal,
    AxeWritableScope,
    ConfigTransactionPreview,
    TransactionDiagnostic,
    TransactionEffectivePreview,
    stable_chop_name,
)
from ..modals.config_commit import (
    ConfigCommitOffer,
    build_config_commit_offer,
    push_config_commit_prompt,
    submit_config_commit_task,
)
from ..util.pump_tasks import spawn_pump_free_task
from ..widgets.bgcmd_list import ChopItem, LumberjackItem
from .axe_display._loaders import AxeItemKey, selected_axe_item_key


@dataclass(frozen=True)
class _AxeConfigActionInventory:
    """All disk/process-backed input loaded for one AXE editor session."""

    composition: AxeConfigComposition
    schema: dict[str, Any]
    chop_inventory: ChopInventory
    axe_running: bool


@dataclass(frozen=True)
class _AxeConfigActionPlan:
    """Backend mutation plan plus the shared modal preview projection."""

    mutation_plan: AxeMutationPlan
    preview: ConfigTransactionPreview


@dataclass(frozen=True)
class _AxeAppliedConfigOutcome:
    """Successful config write and its independently verified runtime state."""

    applied: AppliedResult
    axe_running: bool
    chezmoi_warning: str | None = None


@dataclass(frozen=True)
class _PendingAxeSelection:
    """One refresh-time selection intent guarded by the previous selection."""

    target_key: AxeItemKey
    guard_key: AxeItemKey | None


@dataclass
class _AxeEditorSession:
    """Mutable reload state captured by one modal's worker callbacks."""

    inventory: _AxeConfigActionInventory
    selector: AxeEntrySelector
    display_target: AxeItemKey
    generated_instance: str | None = None
    generated_warning: str | None = None
    new_entry: bool = False
    initial_values: dict[str, Any] | None = None
    initial_touched: tuple[str, ...] = ()

    def seed(self) -> AxeEntryEditorSeed:
        return _build_axe_editor_seed(
            self.inventory,
            self.selector,
            generated_instance=self.generated_instance,
            generated_warning=self.generated_warning,
            new_entry=self.new_entry,
            initial_values=self.initial_values,
            initial_touched=self.initial_touched,
        )

    def plan(self, request: AxeEntryMutationRequest) -> _AxeConfigActionPlan:
        return _plan_axe_editor_request(self.inventory, self.selector, request)

    def apply(self, plan: _AxeConfigActionPlan) -> _AxeAppliedConfigOutcome:
        return _apply_axe_editor_plan(plan)

    def reload(self) -> AxeEntryEditorSeed:
        self.inventory = _load_axe_config_action_inventory()
        return self.seed()


def _load_axe_config_action_inventory() -> _AxeConfigActionInventory:
    """Load the exact config, schema, scripts, and process state off-thread."""
    composition = compose_axe_config()
    schema = load_config_schema()
    runtime_config = load_axe_config()
    return _AxeConfigActionInventory(
        composition=composition,
        schema=schema,
        chop_inventory=collect_chop_inventory(runtime_config),
        axe_running=is_axe_running(),
    )


def _axe_base_chop_identities(
    composition: AxeConfigComposition,
) -> frozenset[tuple[str, str]]:
    """Return exact immutable base identities, excluding generated rows."""
    return frozenset(
        (entry.selector.lumberjack, entry.selector.chop)
        for entry in composition.entries
        if entry.selector.kind == "chop"
        and entry.selector.chop is not None
        and not entry.generated
    )


def _axe_lumberjack_names(composition: AxeConfigComposition) -> frozenset[str]:
    """Return exact lumberjack identities from the composed inventory."""
    return frozenset(
        entry.selector.lumberjack
        for entry in composition.entries
        if entry.selector.kind == "lumberjack"
    )


def _writable_scopes(
    composition: AxeConfigComposition,
) -> tuple[AxeWritableScope, ...]:
    return tuple(
        AxeWritableScope(
            name=str(layer["name"]),
            path=str(layer["path"]) if layer.get("path") is not None else None,
            kind=str(layer.get("kind", "other")),
            exists=bool(layer.get("exists", False)),
            list_strategy=str(layer.get("list_strategy", "concatenate")),
        )
        for layer in composition.layer_inputs
        if bool(layer.get("writable", False))
    )


def _initial_target(
    scopes: tuple[AxeWritableScope, ...], entry: AxeInventoryEntry | None
) -> str | None:
    if entry is not None:
        contributed = {
            contribution.layer
            for contribution in entry.contributions
            if contribution.writable and contribution.has_value
        }
        for scope in reversed(scopes):
            if scope.name in contributed:
                return scope.name
    for scope in scopes:
        if scope.kind == "user":
            return scope.name
    return scopes[0].name if scopes else None


def _raw_values_by_scope(
    scopes: tuple[AxeWritableScope, ...], entry: AxeInventoryEntry | None
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {scope.name: {} for scope in scopes}
    if entry is None:
        return result
    for contribution in entry.contributions:
        if not contribution.writable or not contribution.has_value:
            continue
        if isinstance(contribution.value, Mapping):
            result[contribution.layer] = dict(contribution.value)
    return result


def _field_provenance(entry: AxeInventoryEntry | None) -> dict[str, tuple[str, ...]]:
    if entry is None:
        return {}
    prefix_len = len(entry.key_path)
    result: dict[str, list[str]] = {}
    for item in entry.field_provenance:
        relative = item.key_path[prefix_len:]
        if not relative:
            continue
        sources = result.setdefault(relative[0], [])
        if item.layer not in sources:
            sources.append(item.layer)
    return {name: tuple(sources) for name, sources in result.items()}


def _build_axe_editor_seed(
    inventory: _AxeConfigActionInventory,
    selector: AxeEntrySelector,
    *,
    generated_instance: str | None = None,
    generated_warning: str | None = None,
    new_entry: bool = False,
    initial_values: Mapping[str, Any] | None = None,
    initial_touched: tuple[str, ...] = (),
) -> AxeEntryEditorSeed:
    """Project exact backend inventory into the reusable schema editor seed."""
    entry = inventory.composition.entry(selector)
    if entry is None and not new_entry:
        label = selector.lumberjack
        if selector.chop is not None:
            label += f" / {selector.chop}"
        raise ValueError(f"AXE entry no longer exists: {label}")

    scopes = _writable_scopes(inventory.composition)
    by_scope = _raw_values_by_scope(scopes, entry)
    target = _initial_target(scopes, entry)
    if new_entry:
        effective = dict(initial_values or {})
    else:
        assert entry is not None
        effective = dict(entry.effective)
    raw = dict(by_scope.get(target or "", {}))
    kind: Literal["lumberjack", "chop"] = (
        "chop" if selector.kind == "chop" else "lumberjack"
    )
    status: str | None = None
    if entry is not None and kind == "chop" and not entry.enabled:
        status = "disabled"
    return AxeEntryEditorSeed(
        identity=AxeEntryIdentity(
            kind=kind,
            lumberjack=selector.lumberjack,
            chop=selector.chop,
            generated_instance=generated_instance,
        ),
        schema=inventory.schema,
        writable_scopes=scopes,
        effective_values=effective,
        raw_values=raw,
        target_values=raw,
        provenance=_field_provenance(entry),
        initial_target=target,
        inherited_values=effective,
        raw_values_by_scope=by_scope,
        generated_warning=generated_warning,
        new_entry=new_entry,
        initial_touched=initial_touched,
        running=inventory.axe_running,
        status=status,
    )


def _transaction_diagnostics(
    plan: AxeMutationPlan,
) -> tuple[TransactionDiagnostic, ...]:
    seen: set[tuple[str, str, str | None, str | None]] = set()
    projected: list[TransactionDiagnostic] = []
    diagnostics = (
        *plan.edit_plan.validation,
        *plan.edit_plan.diagnostics,
        *plan.axe_diagnostics,
    )
    for diagnostic in diagnostics:
        key = (
            diagnostic.severity,
            diagnostic.message,
            diagnostic.path,
            diagnostic.code,
        )
        if key in seen:
            continue
        seen.add(key)
        projected.append(
            TransactionDiagnostic(
                severity=diagnostic.severity,
                message=diagnostic.message,
                path=diagnostic.path,
                code=diagnostic.code,
            )
        )
    return tuple(projected)


def _missing_script_warning(
    plan: AxeMutationPlan, inventory: _AxeConfigActionInventory
) -> str | None:
    after = plan.effective_preview.after
    if plan.selector.kind != "chop" or not isinstance(after, Mapping):
        return None
    if after.get("enabled", True) is False:
        return None
    script = after.get("script") or plan.selector.chop
    if not isinstance(script, str) or not script:
        return None
    if discover_chop_script(script, list(inventory.chop_inventory.chop_script_dirs)):
        return None
    return f"Executable {script!r} was not found; this chop cannot run until it is installed."


def _plan_axe_editor_request(
    inventory: _AxeConfigActionInventory,
    selector: AxeEntrySelector,
    request: AxeEntryMutationRequest,
) -> _AxeConfigActionPlan:
    """Plan a sparse schema request through the exact AXE backend."""
    operations = tuple(
        AxeFieldOperation(
            kind=operation.kind,
            key_path=operation.key_path,
            value=operation.value,
        )
        for operation in request.operations
    )
    mutation_plan = plan_axe_entry_edit(
        inventory.composition,
        selector,
        request.target_scope,
        operations,
        schema=inventory.schema,
    )
    warnings: list[str] = []
    if mutation_plan.promoted_legacy_list:
        warnings.append(
            "This edit promotes the target layer's legacy chop list to an exact-key mapping."
        )
    missing = _missing_script_warning(mutation_plan, inventory)
    if missing is not None:
        warnings.append(missing)
    effective = mutation_plan.effective_preview
    preview = ConfigTransactionPreview(
        target_path=mutation_plan.target_path,
        effective=TransactionEffectivePreview(
            has_before=effective.has_before,
            before=effective.before,
            has_after=effective.has_after,
            after=effective.after,
            changed=effective.changed,
            label="Effective AXE entry",
        ),
        diagnostics=_transaction_diagnostics(mutation_plan),
        warnings=tuple(warnings),
        text_diff=mutation_plan.text_diff,
        used_chezmoi=mutation_plan.edit_plan.used_chezmoi,
        valid=mutation_plan.is_valid,
    )
    return _AxeConfigActionPlan(mutation_plan=mutation_plan, preview=preview)


def _apply_axe_editor_plan(plan: _AxeConfigActionPlan) -> _AxeAppliedConfigOutcome:
    """Apply a previewed edit, propagate chezmoi, then probe AXE state."""
    mutation = plan.mutation_plan
    applied = apply_axe_entry_edit(mutation)
    warning: str | None = None
    home_target = mutation.edit_plan.write_plan.file
    if (
        applied.used_chezmoi
        and home_target is not None
        and Path(applied.path) != Path(home_target)
    ):
        try:
            result = apply_chezmoi(home_target)
        except OSError as exc:
            warning = f"Config source was saved, but chezmoi apply failed: {exc}"
        else:
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                warning = "Config source was saved, but chezmoi apply failed"
                if detail:
                    warning += f": {detail}"
    return _AxeAppliedConfigOutcome(
        applied=applied,
        axe_running=is_axe_running(),
        chezmoi_warning=warning,
    )


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
        if guard is not None and guard[0] in {"lumberjack", "chop"}:
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
            inventory = await asyncio.to_thread(_load_axe_config_action_inventory)
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
        inventory: _AxeConfigActionInventory,
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
        session = _AxeEditorSession(
            inventory=inventory,
            selector=selector,
            display_target=key,
            generated_instance=generated_instance,
            generated_warning=generated_warning,
        )
        self._push_axe_editor_session(session)

    def _show_new_lumberjack_identity(
        self, inventory: _AxeConfigActionInventory
    ) -> None:
        existing = _axe_lumberjack_names(inventory.composition)

        def identified(draft: AxeNewEntryDraft | None) -> None:
            if draft is None:
                return
            selector = AxeEntrySelector.lumberjack_entry(draft.name)
            self._push_axe_editor_session(
                _AxeEditorSession(
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
        self, inventory: _AxeConfigActionInventory, parent: str
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
        inventory: _AxeConfigActionInventory,
        *,
        parent: str,
        initial_name: str,
        initial_script: str,
    ) -> None:
        identities = _axe_base_chop_identities(inventory.composition)

        def identified(draft: AxeNewEntryDraft | None) -> None:
            if draft is None or draft.script is None:
                return
            selector = AxeEntrySelector.chop_entry(parent, draft.name)
            self._push_axe_editor_session(
                _AxeEditorSession(
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

    def _push_axe_editor_session(self, session: _AxeEditorSession) -> None:
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
        self, session: _AxeEditorSession, result: AxeEntryEditorResult
    ) -> None:
        outcome = result.applied
        if not isinstance(outcome, _AxeAppliedConfigOutcome):
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


__all__ = [
    "AxeConfigActionsMixin",
]
