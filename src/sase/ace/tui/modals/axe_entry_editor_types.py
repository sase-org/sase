"""Data contracts and schema helpers for the AXE entry editor."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field, replace
from typing import Any, Literal

from .schema_object_form import (
    SchemaFieldOperation,
    SchemaFieldGroup,
    SchemaObjectForm,
    resolve_schema_node,
)


AxeEntryKind = Literal["lumberjack", "chop"]

_BASICS_BY_KIND: dict[AxeEntryKind, tuple[str, ...]] = {
    "lumberjack": ("description", "interval", "chop_timeout", "wait_runners"),
    "chop": ("description", "script", "enabled", "run_every", "timeout"),
}
_ADVANCED_BY_KIND: dict[AxeEntryKind, tuple[str, ...]] = {
    "lumberjack": ("env",),
    "chop": ("env", "inhibit_if", "trigger", "once_per", "for_each", "vars"),
}
_HIDDEN_BY_KIND: dict[AxeEntryKind, frozenset[str]] = {
    "lumberjack": frozenset({"chops"}),
    "chop": frozenset({"name"}),
}


@dataclass(frozen=True)
class AxeEntryIdentity:
    """Stable immutable identity shown by and returned from the editor."""

    kind: AxeEntryKind
    lumberjack: str
    chop: str | None = None
    generated_instance: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "chop" and not self.chop:
            raise ValueError("chop identity requires a chop name")

    @property
    def label(self) -> str:
        if self.kind == "lumberjack":
            return self.lumberjack
        return f"{self.lumberjack} / {self.chop}"


@dataclass(frozen=True)
class AxeWritableScope:
    """One writable AXE config layer in the modal's scope rail."""

    name: str
    path: str | None = None
    kind: str = "user"
    exists: bool = True
    list_strategy: str = "concatenate"


@dataclass(frozen=True)
class AxeEntryEditorSeed:
    """Immutable data needed to edit one AXE entry."""

    identity: AxeEntryIdentity
    schema: Mapping[str, Any]
    writable_scopes: tuple[AxeWritableScope, ...]
    effective_values: Mapping[str, Any] = dataclass_field(default_factory=dict)
    raw_values: Mapping[str, Any] = dataclass_field(default_factory=dict)
    target_values: Mapping[str, Any] | None = None
    provenance: Mapping[str, str | Sequence[str]] = dataclass_field(
        default_factory=dict
    )
    initial_target: str | None = None
    inherited_values: Mapping[str, Any] | None = None
    raw_values_by_scope: Mapping[str, Mapping[str, Any]] | None = None
    key_prefix: tuple[str, ...] = ()
    generated_warning: str | None = None
    new_entry: bool = False
    initial_touched: tuple[str, ...] = ()
    running: bool = False
    status: str | None = None


@dataclass(frozen=True)
class AxeEntryMutationRequest:
    """Sparse exact-segment request passed to the injected planner."""

    identity: AxeEntryIdentity
    target_scope: str
    operations: tuple[SchemaFieldOperation, ...]


@dataclass(frozen=True)
class AxeEntryEditorResult:
    """Successful write plus the caller-owned runtime consequence."""

    identity: AxeEntryIdentity
    applied: Any
    restart_requested: bool

    @property
    def save_only(self) -> bool:
        return not self.restart_requested


def build_axe_entry_form(
    seed: AxeEntryEditorSeed, *, target: str | None = None
) -> SchemaObjectForm:
    """Build the sparse form for an AXE entry and writable target."""
    object_schema = axe_entry_schema(seed.schema, seed.identity.kind)
    basics = _BASICS_BY_KIND[seed.identity.kind]
    advanced = _ADVANCED_BY_KIND[seed.identity.kind]
    hidden = _HIDDEN_BY_KIND[seed.identity.kind]
    properties = object_schema.get("properties", {})
    property_names = (
        tuple(str(name) for name in properties)
        if isinstance(properties, Mapping)
        else ()
    )
    groups: dict[str, SchemaFieldGroup] = {
        name: "basics" if name in basics else "advanced"
        for name in property_names
        if name not in hidden
    }
    target_values = seed.target_values
    if (
        seed.raw_values_by_scope is not None
        and target is not None
        and target in seed.raw_values_by_scope
    ):
        target_values = seed.raw_values_by_scope[target]
    form = SchemaObjectForm.build(
        schema_root=seed.schema,
        object_schema=object_schema,
        effective_values=seed.effective_values,
        target_values=(target_values if target_values is not None else seed.raw_values),
        inherited_values=seed.inherited_values,
        provenance=seed.provenance,
        key_prefix=seed.key_prefix,
        basics=basics,
        advanced=advanced,
        groups=groups,
    )
    form = replace(form, fields=tuple(f for f in form.fields if f.name not in hidden))
    for name in seed.initial_touched:
        if name not in hidden and name in property_names:
            form = form.set_value(name, form.field(name).draft_value)
    return form


def axe_entry_schema(
    schema_root: Mapping[str, Any], kind: AxeEntryKind
) -> Mapping[str, Any]:
    """Resolve the bundled lumberjack or chop object schema."""
    # Tests and embedding callers may pass the object schema directly.
    properties = schema_root.get("properties")
    if isinstance(properties, Mapping):
        expected = "interval" if kind == "lumberjack" else "script"
        if expected in properties:
            return schema_root
    if kind == "chop":
        resolved = resolve_schema_node(schema_root, {"$ref": "#/definitions/axeChop"})
    else:
        node: Any = schema_root
        for segment in ("axe", "lumberjacks"):
            node = resolve_schema_node(schema_root, node)
            node_properties = (
                node.get("properties", {}) if isinstance(node, Mapping) else {}
            )
            if (
                not isinstance(node_properties, Mapping)
                or segment not in node_properties
            ):
                raise ValueError("schema does not contain AXE lumberjack definitions")
            node = node_properties[segment]
        node = resolve_schema_node(schema_root, node)
        resolved = (
            resolve_schema_node(schema_root, node.get("additionalProperties"))
            if isinstance(node, Mapping)
            else None
        )
    if not isinstance(resolved, Mapping):
        raise ValueError(f"schema does not contain an AXE {kind} definition")
    return resolved


__all__ = [
    "AxeEntryEditorResult",
    "AxeEntryEditorSeed",
    "AxeEntryIdentity",
    "AxeEntryKind",
    "AxeEntryMutationRequest",
    "AxeWritableScope",
    "axe_entry_schema",
    "build_axe_entry_form",
]
