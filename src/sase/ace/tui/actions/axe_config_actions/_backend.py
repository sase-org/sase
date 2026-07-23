"""AXE config inventory, transaction planning, and application."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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

from ...modals import (
    AxeEntryEditorSeed,
    AxeEntryIdentity,
    AxeEntryMutationRequest,
    AxeWritableScope,
    ConfigTransactionPreview,
    TransactionDiagnostic,
    TransactionEffectivePreview,
)
from ..axe_display._loaders import AxeItemKey


@dataclass(frozen=True)
class AxeConfigActionInventory:
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
class AxeAppliedConfigOutcome:
    """Successful config write and its independently verified runtime state."""

    applied: AppliedResult
    axe_running: bool
    chezmoi_warning: str | None = None


@dataclass
class AxeEditorSession:
    """Mutable reload state captured by one modal's worker callbacks."""

    inventory: AxeConfigActionInventory
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

    def apply(self, plan: _AxeConfigActionPlan) -> AxeAppliedConfigOutcome:
        return _apply_axe_editor_plan(plan)

    def reload(self) -> AxeEntryEditorSeed:
        self.inventory = load_axe_config_action_inventory()
        return self.seed()


def load_axe_config_action_inventory() -> AxeConfigActionInventory:
    """Load the exact config, schema, scripts, and process state off-thread."""
    composition = compose_axe_config()
    schema = load_config_schema()
    runtime_config = load_axe_config()
    return AxeConfigActionInventory(
        composition=composition,
        schema=schema,
        chop_inventory=collect_chop_inventory(runtime_config),
        axe_running=is_axe_running(),
    )


def axe_base_chop_identities(
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


def axe_lumberjack_names(composition: AxeConfigComposition) -> frozenset[str]:
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
    inventory: AxeConfigActionInventory,
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
    plan: AxeMutationPlan, inventory: AxeConfigActionInventory
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
    inventory: AxeConfigActionInventory,
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


def _apply_axe_editor_plan(plan: _AxeConfigActionPlan) -> AxeAppliedConfigOutcome:
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
    return AxeAppliedConfigOutcome(
        applied=applied,
        axe_running=is_axe_running(),
        chezmoi_warning=warning,
    )
