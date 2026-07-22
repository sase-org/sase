"""Typed Python facade for Rust-owned AXE composition and edit planning.

This module is deliberately Textual-free. Python discovers config layers,
resolves chezmoi targets, and applies source-preserving YAML edits; the Rust
core owns exact-key composition, inventory, provenance, and mutation logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Sequence

from sase.config._edit_plan import apply_config_edit, build_edit_plan_result
from sase.config._edit_types import AppliedResult, EditPlanResult
from sase.config.core import ConfigLayer, get_use_chezmoi, load_config_layers
from sase.config.inventory import (
    ConfigBackendError,
    ConfigDiagnostic,
    load_config_schema,
    serialize_config_layer,
)
from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class AxeEntrySelector:
    """Exact identity for one lumberjack or base chop."""

    kind: str
    lumberjack: str
    chop: str | None = None

    @classmethod
    def lumberjack_entry(cls, name: str) -> AxeEntrySelector:
        return cls("lumberjack", name)

    @classmethod
    def chop_entry(cls, lumberjack: str, chop: str) -> AxeEntrySelector:
        return cls("chop", lumberjack, chop)

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> AxeEntrySelector:
        return cls(
            kind=str(payload["kind"]),
            lumberjack=str(payload["lumberjack"]),
            chop=str(payload["chop"]) if payload.get("chop") is not None else None,
        )

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "lumberjack": self.lumberjack,
        }
        if self.chop is not None:
            payload["chop"] = self.chop
        return payload

    @property
    def key_path(self) -> tuple[str, ...]:
        path = ("axe", "lumberjacks", self.lumberjack)
        if self.chop is not None:
            return (*path, "chops", self.chop)
        return path


@dataclass(frozen=True)
class AxeFieldProvenance:
    """One exact effective path and its source layer."""

    key_path: tuple[str, ...]
    path: str
    layer: str

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> AxeFieldProvenance:
        return cls(
            key_path=tuple(str(item) for item in payload["key_path"]),
            path=str(payload["path"]),
            layer=str(payload["layer"]),
        )


@dataclass(frozen=True)
class AxeRawContribution:
    """One writable layer's sparse contribution to an AXE entity."""

    layer: str
    file: str | None
    writable: bool
    representation: str
    has_value: bool
    value: Any

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> AxeRawContribution:
        return cls(
            layer=str(payload["layer"]),
            file=str(payload["file"]) if payload.get("file") is not None else None,
            writable=bool(payload["writable"]),
            representation=str(payload["representation"]),
            has_value=bool(payload["has_value"]),
            value=payload["value"],
        )


@dataclass(frozen=True)
class AxeInventoryEntry:
    """Effective lumberjack, base chop, or generated chop instance."""

    selector: AxeEntrySelector
    key_path: tuple[str, ...]
    path: str
    effective: dict[str, Any]
    enabled: bool
    mutable: bool
    generated: bool
    base_selector: AxeEntrySelector | None
    target_key: str | None
    field_provenance: tuple[AxeFieldProvenance, ...]
    contributions: tuple[AxeRawContribution, ...]

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> AxeInventoryEntry:
        raw_base = payload.get("base_selector")
        return cls(
            selector=AxeEntrySelector.from_wire(payload["selector"]),
            key_path=tuple(str(item) for item in payload["key_path"]),
            path=str(payload["path"]),
            effective=dict(payload["effective"]),
            enabled=bool(payload["enabled"]),
            mutable=bool(payload["mutable"]),
            generated=bool(payload["generated"]),
            base_selector=(
                AxeEntrySelector.from_wire(raw_base)
                if isinstance(raw_base, dict)
                else None
            ),
            target_key=(
                str(payload["target_key"])
                if payload.get("target_key") is not None
                else None
            ),
            field_provenance=tuple(
                AxeFieldProvenance.from_wire(item)
                for item in payload["field_provenance"]
            ),
            contributions=tuple(
                AxeRawContribution.from_wire(item) for item in payload["contributions"]
            ),
        )


@dataclass(frozen=True)
class AxeConfigComposition:
    """Effective AXE data plus exact provenance and entity inventory."""

    schema_version: int
    effective_config: dict[str, Any]
    provenance: tuple[AxeFieldProvenance, ...]
    entries: tuple[AxeInventoryEntry, ...]
    diagnostics: tuple[ConfigDiagnostic, ...]
    layer_inputs: tuple[dict[str, Any], ...]

    @classmethod
    def from_wire(
        cls,
        payload: dict[str, Any],
        *,
        layer_inputs: Sequence[dict[str, Any]],
    ) -> AxeConfigComposition:
        return cls(
            schema_version=int(payload["schema_version"]),
            effective_config=dict(payload["effective_config"]),
            provenance=tuple(
                AxeFieldProvenance.from_wire(item) for item in payload["provenance"]
            ),
            entries=tuple(
                AxeInventoryEntry.from_wire(item) for item in payload["entries"]
            ),
            diagnostics=tuple(
                ConfigDiagnostic.from_wire(item) for item in payload["diagnostics"]
            ),
            layer_inputs=tuple(layer_inputs),
        )

    def entry(self, selector: AxeEntrySelector) -> AxeInventoryEntry | None:
        """Return the exact inventory entry selected by *selector*."""
        return next(
            (item for item in self.entries if item.selector == selector),
            None,
        )

    def chop_provenance(self, lumberjack: str, chop: str) -> dict[str, str]:
        """Project exact provenance to the runtime's per-chop field view."""
        prefix = ("axe", "lumberjacks", lumberjack, "chops", chop)
        result: dict[str, str] = {}
        for item in self.provenance:
            if item.key_path == prefix:
                result.setdefault("*", item.layer)
            elif item.key_path[: len(prefix)] == prefix:
                relative = item.key_path[len(prefix) :]
                result[_display_key_path(relative)] = item.layer
        return result

    def legacy_provenance(self) -> dict[str, str]:
        """Return the established dotted display map for compatibility."""
        return {item.path: item.layer for item in self.provenance}


@dataclass(frozen=True)
class AxeFieldOperation:
    """An ordered exact-path set/reset relative to one AXE entity."""

    kind: str
    key_path: tuple[str, ...]
    value: Any = None

    @classmethod
    def set_value(cls, key_path: Sequence[str], value: Any) -> AxeFieldOperation:
        return cls("set", tuple(key_path), value)

    @classmethod
    def unset(cls, key_path: Sequence[str]) -> AxeFieldOperation:
        return cls("unset", tuple(key_path))

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "key_path": list(self.key_path),
        }
        if self.kind == "set":
            payload["value"] = self.value
        return payload


@dataclass(frozen=True)
class AxeEntryPreview:
    """Effective entity before/after a candidate sparse mutation."""

    selector: AxeEntrySelector
    has_before: bool
    before: Any
    has_after: bool
    after: Any
    changed: bool

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> AxeEntryPreview:
        return cls(
            selector=AxeEntrySelector.from_wire(payload["selector"]),
            has_before=bool(payload["has_before"]),
            before=payload["before"],
            has_after=bool(payload["has_after"]),
            after=payload["after"],
            changed=bool(payload["changed"]),
        )


@dataclass(frozen=True)
class AxeMutationPlan:
    """Typed AXE result plus the shared source-preserving file edit plan."""

    edit_plan: EditPlanResult
    selector: AxeEntrySelector
    effective_preview: AxeEntryPreview
    candidate_composition: AxeConfigComposition
    axe_diagnostics: tuple[ConfigDiagnostic, ...]
    target_representation: str
    promoted_legacy_list: bool

    @property
    def target_path(self) -> str | None:
        return self.edit_plan.target_path

    @property
    def new_text(self) -> str:
        return self.edit_plan.new_text

    @property
    def text_diff(self) -> str:
        return self.edit_plan.text_diff

    @property
    def is_valid(self) -> bool:
        return self.edit_plan.is_valid and not any(
            item.severity == "error" for item in self.axe_diagnostics
        )


def compose_axe_config(
    layers: Sequence[ConfigLayer] | None = None,
) -> AxeConfigComposition:
    """Compose and inventory the ordered AXE layer stack in Rust."""
    discovered = list(load_config_layers() if layers is None else layers)
    layer_inputs = [serialize_config_layer(layer) for layer in discovered]
    binding = require_rust_binding("axe_config_compose")
    try:
        payload = binding({"layers": layer_inputs})
    except ValueError as exc:
        raise ConfigBackendError(str(exc)) from exc
    return AxeConfigComposition.from_wire(payload, layer_inputs=layer_inputs)


def _display_key_path(path: Sequence[str]) -> str:
    display = ""
    for segment in path:
        if segment.startswith("["):
            display += segment
        else:
            display += ("." if display else "") + segment
    return display


def build_axe_config_inventory(
    layers: Sequence[ConfigLayer] | None = None,
) -> AxeConfigComposition:
    """Compatibility-friendly inventory name for :func:`compose_axe_config`."""
    return compose_axe_config(layers)


def plan_axe_entry_edit(
    composition: AxeConfigComposition,
    selector: AxeEntrySelector,
    target: str,
    operations: Sequence[AxeFieldOperation],
    *,
    schema: dict[str, Any] | None = None,
    use_chezmoi: bool | None = None,
) -> AxeMutationPlan:
    """Plan an exact sparse AXE entity mutation without writing a file."""
    request = {
        "schema": load_config_schema() if schema is None else schema,
        "layers": list(composition.layer_inputs),
        "target_layer": target,
        "selector": selector.to_wire(),
        "operations": [operation.to_wire() for operation in operations],
    }
    binding = require_rust_binding("axe_config_plan_entry")
    try:
        payload = binding(request)
    except ValueError as exc:
        raise ConfigBackendError(str(exc)) from exc

    preview = AxeEntryPreview.from_wire(payload["effective_preview"])
    file_payload = dict(payload)
    file_payload["effective_preview"] = {
        "path": ".".join(selector.key_path),
        "has_before": preview.has_before,
        "before": preview.before,
        "has_after": preview.has_after,
        "after": preview.after,
        "changed": preview.changed,
    }
    file_payload["diagnostics"] = [
        *payload["diagnostics"],
        *payload["axe_diagnostics"],
    ]
    chezmoi = get_use_chezmoi() if use_chezmoi is None else use_chezmoi
    edit_plan = build_edit_plan_result(file_payload, use_chezmoi=chezmoi)
    candidate = AxeConfigComposition.from_wire(
        payload["candidate_composition"],
        layer_inputs=composition.layer_inputs,
    )
    return AxeMutationPlan(
        edit_plan=edit_plan,
        selector=selector,
        effective_preview=preview,
        candidate_composition=candidate,
        axe_diagnostics=tuple(
            ConfigDiagnostic.from_wire(item) for item in payload["axe_diagnostics"]
        ),
        target_representation=str(payload["target_representation"]),
        promoted_legacy_list=bool(payload["promoted_legacy_list"]),
    )


plan_axe_config_entry_edit = plan_axe_entry_edit


def apply_axe_entry_edit(plan: AxeMutationPlan) -> AppliedResult:
    """Apply an AXE mutation through the shared conflict-safe transaction."""
    return apply_config_edit(plan.edit_plan)


__all__ = [
    "AxeConfigComposition",
    "AxeEntryPreview",
    "AxeEntrySelector",
    "AxeFieldOperation",
    "AxeFieldProvenance",
    "AxeInventoryEntry",
    "AxeMutationPlan",
    "AxeRawContribution",
    "build_axe_config_inventory",
    "apply_axe_entry_edit",
    "compose_axe_config",
    "plan_axe_config_entry_edit",
    "plan_axe_entry_edit",
]
