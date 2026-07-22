"""Python adapter over the Rust config inventory + field-model backend.

The deterministic config domain (schema field model, layer merge, per-field
provenance, validation) lives in the Rust core (``sase_core::config``) and is
reached through the ``sase_core_rs`` binding. This module owns the parts that
must stay in Python: plugin/layer discovery, file IO, and JSON Schema loading.
It serializes the already-discovered layer stack to the wire shape the binding
expects and rehydrates the JSON-out payload into typed dataclasses so callers
(the Config Center TUI panel, a future CLI/web frontend) never touch raw
binding dicts.

Nothing here reimplements merge/provenance/validation logic; that would risk
diverging from the Rust authority. The layer-merge parity test
(``tests/test_config_inventory.py``) pins the Python ``_deep_merge`` and the
Rust merge to the same golden vectors.

No Textual imports: every entry point is callable from a worker thread.
"""

from __future__ import annotations

import importlib.resources
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.config.core import (
    DEPRECATED_TOP_LEVEL_KEYS,
    UNSUPPORTED_TOP_LEVEL_KEYS,
    ConfigLayer,
    without_retired_sdd_selectors,
    load_config_layers,
    load_yaml_file_with_metadata,
)
from sase.core.rust import require_rust_binding


_schema_cache: dict[str, Any] | None = None


class ConfigBackendError(RuntimeError):
    """Raised when the config backend cannot satisfy a request."""


# --- Schema loading -------------------------------------------------------


def config_schema_path() -> Path:
    """Resolve the bundled ``src/sase/config/sase.schema.json`` path.

    The schema lives inside the ``sase`` package, so ``importlib.resources``
    resolves it for both wheel and editable installs.
    """
    sase_pkg = Path(str(importlib.resources.files("sase"))).resolve()
    return sase_pkg / "config" / "sase.schema.json"


def _config_schema_path() -> Path:
    """Backward-compatible private alias for :func:`config_schema_path`."""
    return config_schema_path()


def load_config_schema() -> dict[str, Any]:
    """Load and cache the SASE config JSON Schema document.

    Raises:
        ConfigBackendError: when the schema file cannot be found or parsed.
    """
    global _schema_cache
    cached = _schema_cache
    if cached is None:
        path = _config_schema_path()
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ConfigBackendError(
                f"could not load config schema at {path}: {exc}"
            ) from exc
        _schema_cache = cached
    return cached


# --- Layer serialization --------------------------------------------------


def _layer_kind(name: str) -> str:
    """Classify a layer by its merge-chain name (mirrors the source rail)."""
    if name == "default":
        return "builtin"
    if name.startswith("plugin:"):
        return "plugin"
    if name == "user":
        return "user"
    if name.startswith("overlay:"):
        return "overlay"
    if name == "local" or name.startswith("local:"):
        return "local"
    return "other"


def _serialize_layer(layer: ConfigLayer) -> dict[str, Any]:
    """Serialize a discovered ``ConfigLayer`` to the wire input shape.

    Package-backed layers (built-in defaults, plugin defaults) carry no path
    and are never writable; file-backed layers (user, overlays, local) are.
    """
    return {
        "name": layer.name,
        "kind": _layer_kind(layer.name),
        "path": layer.path,
        "value": without_retired_sdd_selectors(layer.data or {}),
        "list_strategy": layer.list_strategy,
        "writable": layer.path is not None,
        "exists": layer.exists,
        "error": layer.error,
    }


def serialize_config_layer(layer: ConfigLayer) -> dict[str, Any]:
    """Serialize one discovered layer for a Rust config-domain request."""
    return _serialize_layer(layer)


def _serialize_local_path(path: str | Path, *, name: str) -> dict[str, Any]:
    """Load an explicitly-selected local ``sase.yml`` into a wire layer."""
    target = Path(path)
    _, data, error = load_yaml_file_with_metadata(target)
    return {
        "name": name,
        "kind": "local",
        "path": str(target),
        "value": without_retired_sdd_selectors(data or {}),
        "list_strategy": "concatenate",
        "writable": True,
        "exists": data is not None,
        "error": error,
    }


def discover_layer_inputs(
    *, local_paths: tuple[str | Path, ...] | list[str | Path] = ()
) -> list[dict[str, Any]]:
    """Discover and serialize the ordered layer stack for the backend.

    Reuses :func:`load_config_layers` for the built-in/plugin/user/overlay
    layers. When *local_paths* is given, the auto-discovered local layer is
    replaced by one wire layer per explicitly-selected project-local file (the
    Config Center selects local config deliberately because ACE disables the
    implicit local layer).
    """
    layers = load_config_layers()
    locals_seq = tuple(local_paths)
    if locals_seq:
        layers = [layer for layer in layers if _layer_kind(layer.name) != "local"]
    inputs = [_serialize_layer(layer) for layer in layers]
    for path in locals_seq:
        name = "local" if len(locals_seq) == 1 else f"local:{Path(path).name}"
        inputs.append(_serialize_local_path(path, name=name))
    return inputs


# --- Field model ----------------------------------------------------------


@dataclass(frozen=True)
class ConfigConstraints:
    """Numeric/string constraints flattened from a schema field."""

    minimum: float | None
    maximum: float | None
    exclusive_minimum: float | None
    exclusive_maximum: float | None
    min_length: int | None
    max_length: int | None
    pattern: str | None

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigConstraints:
        return cls(
            minimum=payload.get("minimum"),
            maximum=payload.get("maximum"),
            exclusive_minimum=payload.get("exclusive_minimum"),
            exclusive_maximum=payload.get("exclusive_maximum"),
            min_length=payload.get("min_length"),
            max_length=payload.get("max_length"),
            pattern=payload.get("pattern"),
        )


@dataclass(frozen=True)
class ConfigField:
    """One flattened schema field (drives which editor a panel row uses).

    ``kind`` is ``"scalar"``, ``"array"``, ``"map"`` (an open object whose keys
    are user-defined), or ``"object"`` (a closed section recursed into). ``leaf``
    is ``False`` only for ``"object"`` containers.
    """

    path: str
    name: str
    depth: int
    parent: str | None
    kind: str
    leaf: bool
    types: tuple[str, ...]
    description: str
    has_default: bool
    default: Any
    enum_values: tuple[Any, ...]
    deprecated: bool
    deprecated_replacement: str | None
    constraints: ConfigConstraints
    additional_properties_allowed: bool

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigField:
        return cls(
            path=payload["path"],
            name=payload["name"],
            depth=payload["depth"],
            parent=payload.get("parent"),
            kind=payload["kind"],
            leaf=payload["leaf"],
            types=tuple(payload["types"]),
            description=payload["description"],
            has_default=payload["has_default"],
            default=payload["default"],
            enum_values=tuple(payload["enum_values"]),
            deprecated=payload["deprecated"],
            deprecated_replacement=payload.get("deprecated_replacement"),
            constraints=ConfigConstraints.from_wire(payload["constraints"]),
            additional_properties_allowed=payload["additional_properties_allowed"],
        )


@dataclass(frozen=True)
class ConfigFieldModel:
    """The ordered, flattened field model for the config schema."""

    schema_version: int
    fields: tuple[ConfigField, ...]

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigFieldModel:
        return cls(
            schema_version=payload["schema_version"],
            fields=tuple(ConfigField.from_wire(item) for item in payload["fields"]),
        )


def config_field_model(schema: dict[str, Any] | None = None) -> ConfigFieldModel:
    """Return the flattened field model for *schema* (defaults to the real one)."""
    schema_doc = schema if schema is not None else load_config_schema()
    binding = require_rust_binding("config_field_model")
    return ConfigFieldModel.from_wire(binding(schema_doc))


# --- Inventory ------------------------------------------------------------


@dataclass(frozen=True)
class ConfigDiagnostic:
    """A single diagnostic (deprecation, unsupported key, validation issue)."""

    severity: str
    code: str
    message: str
    path: str | None
    layer: str | None

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigDiagnostic:
        return cls(
            severity=payload["severity"],
            code=payload["code"],
            message=payload["message"],
            path=payload.get("path"),
            layer=payload.get("layer"),
        )


@dataclass(frozen=True)
class ConfigSource:
    """One row of the source rail (one config layer)."""

    name: str
    kind: str
    path: str | None
    exists: bool
    writable: bool
    list_strategy: str
    key_count: int
    unsupported_keys: tuple[str, ...]
    deprecated_keys: tuple[str, ...]
    error: str | None

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigSource:
        return cls(
            name=payload["name"],
            kind=payload["kind"],
            path=payload.get("path"),
            exists=payload["exists"],
            writable=payload["writable"],
            list_strategy=payload["list_strategy"],
            key_count=payload["key_count"],
            unsupported_keys=tuple(payload["unsupported_keys"]),
            deprecated_keys=tuple(payload["deprecated_keys"]),
            error=payload.get("error"),
        )


@dataclass(frozen=True)
class ConfigContribution:
    """One layer's contribution to a field (the provenance stack entry).

    ``winning`` marks the highest-priority contributor — the layer that "had
    the last word" for this field.
    """

    layer: str
    raw_value: Any
    winning: bool

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigContribution:
        return cls(
            layer=payload["layer"],
            raw_value=payload["raw_value"],
            winning=payload["winning"],
        )


@dataclass(frozen=True)
class ConfigFieldState:
    """Effective state + full provenance for one field."""

    path: str
    has_default: bool
    default: Any
    has_effective: bool
    effective_value: Any
    contributions: tuple[ConfigContribution, ...]
    deprecated_replacement: str | None
    write_capabilities: tuple[str, ...]

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigFieldState:
        return cls(
            path=payload["path"],
            has_default=payload["has_default"],
            default=payload["default"],
            has_effective=payload["has_effective"],
            effective_value=payload["effective_value"],
            contributions=tuple(
                ConfigContribution.from_wire(item) for item in payload["contributions"]
            ),
            deprecated_replacement=payload.get("deprecated_replacement"),
            write_capabilities=tuple(payload["write_capabilities"]),
        )


@dataclass(frozen=True)
class ConfigInventory:
    """The full config inventory: source rail, per-field provenance, diagnostics.

    The original ``schema`` and serialized ``layer_inputs`` are retained so an
    edit can be re-planned (:func:`sase.config.edit.plan_config_edit`) without
    re-reading every layer from disk. They are not part of the Rust wire output.
    """

    schema_version: int
    sources: tuple[ConfigSource, ...]
    fields: tuple[ConfigFieldState, ...]
    diagnostics: tuple[ConfigDiagnostic, ...]
    schema: dict[str, Any]
    layer_inputs: tuple[dict[str, Any], ...]

    @classmethod
    def from_wire(
        cls,
        payload: dict[str, Any],
        *,
        schema: dict[str, Any],
        layer_inputs: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    ) -> ConfigInventory:
        return cls(
            schema_version=payload["schema_version"],
            sources=tuple(ConfigSource.from_wire(item) for item in payload["sources"]),
            fields=tuple(
                ConfigFieldState.from_wire(item) for item in payload["fields"]
            ),
            diagnostics=tuple(
                ConfigDiagnostic.from_wire(item) for item in payload["diagnostics"]
            ),
            schema=schema,
            layer_inputs=tuple(layer_inputs),
        )

    def field(self, path: str) -> ConfigFieldState | None:
        """Return the field state for the dotted *path*, or ``None``."""
        for state in self.fields:
            if state.path == path:
                return state
        return None

    def source(self, name: str) -> ConfigSource | None:
        """Return the source row named *name*, or ``None``."""
        for src in self.sources:
            if src.name == name:
                return src
        return None


def overlay_layer_input(name: str) -> dict[str, Any]:
    """Build a wire layer for a not-yet-created user overlay named *name*.

    The new overlay is a writable, currently-missing ``concatenate`` layer at
    the ``sase_<name>.yml`` user-config path. It is the highest-priority
    overlay, so a value set here wins over the user base and other overlays
    (local config, which ACE never loads, would still win if selected).
    """
    from sase.config.targets import overlay_config_path

    path = overlay_config_path(name)
    return {
        "name": f"overlay:{path.name}",
        "kind": "overlay",
        "path": str(path),
        "value": {},
        "list_strategy": "concatenate",
        "writable": True,
        "exists": False,
        "error": None,
    }


def inventory_with_new_overlay(
    inventory: ConfigInventory, name: str
) -> tuple[ConfigInventory, str]:
    """Return a rebuilt inventory that includes a new overlay named *name*.

    Inserts a synthetic, to-be-created overlay layer just below any local
    layer (so it is the highest-priority overlay) and re-runs the Rust
    inventory pass against the augmented stack. The Config Center uses this so
    "create overlay" can be planned/previewed before the file exists. Returns
    the new inventory and the synthetic overlay's layer name. When an overlay
    with that name is already in the stack, the inventory is returned unchanged
    alongside the existing layer name.
    """
    new_layer = overlay_layer_input(name)
    layer_name: str = new_layer["name"]
    layers = list(inventory.layer_inputs)
    if any(layer.get("name") == layer_name for layer in layers):
        return inventory, layer_name
    insert_at = len(layers)
    for index, layer in enumerate(layers):
        if layer.get("kind") == "local":
            insert_at = index
            break
    layers.insert(insert_at, new_layer)
    request = {
        "schema": inventory.schema,
        "layers": layers,
        "deprecations": dict(DEPRECATED_TOP_LEVEL_KEYS),
        "unsupported": sorted(UNSUPPORTED_TOP_LEVEL_KEYS),
    }
    binding = require_rust_binding("config_inventory")
    payload = binding(request)
    new_inventory = ConfigInventory.from_wire(
        payload, schema=inventory.schema, layer_inputs=layers
    )
    return new_inventory, layer_name


def build_config_inventory(
    *,
    schema: dict[str, Any] | None = None,
    local_paths: tuple[str | Path, ...] | list[str | Path] = (),
) -> ConfigInventory:
    """Build the config inventory from the discovered layer stack.

    Args:
        schema: JSON Schema document to flatten. Defaults to the bundled
            ``src/sase/config/sase.schema.json``.
        local_paths: Explicitly-selected project-local ``sase.yml`` paths to
            include as selectable local layers (ACE disables the implicit
            local layer, so the Config Center selects local config here).

    Returns:
        A :class:`ConfigInventory` with the source rail, per-field provenance,
        and diagnostics, plus the inputs needed to re-plan edits.
    """
    schema_doc = schema if schema is not None else load_config_schema()
    layer_inputs = discover_layer_inputs(local_paths=local_paths)
    request = {
        "schema": schema_doc,
        "layers": layer_inputs,
        "deprecations": dict(DEPRECATED_TOP_LEVEL_KEYS),
        "unsupported": sorted(UNSUPPORTED_TOP_LEVEL_KEYS),
    }
    binding = require_rust_binding("config_inventory")
    payload = binding(request)
    return ConfigInventory.from_wire(
        payload, schema=schema_doc, layer_inputs=layer_inputs
    )
