"""Pure helpers for config edit value parsing, formatting, and target policy."""

from __future__ import annotations

import io
import json
import re
from typing import TYPE_CHECKING, Any

from rich.text import Text

from sase.config import (
    ConfigField,
    ConfigInventory,
    ConfigSource,
    default_target_layer,
)

from .config_edit_types import (
    EditorKind,
    _ACCENT,
    _MUTED,
    _OK_COLOR,
    _WARN_COLOR,
)

if TYPE_CHECKING:
    from sase.ace.tui.modals.config_pane import ConfigPaneView

_LONG_STRING_TEXTAREA_MIN_LENGTH = 240


def deref_schema_ref(schema_root: dict[str, Any], node: Any, _depth: int = 0) -> Any:
    """Resolve a local ``$ref`` against *schema_root* (best-effort)."""
    if not isinstance(node, dict) or _depth > 16:
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        target: Any = schema_root
        for part in ref[2:].split("/"):
            if not isinstance(target, dict):
                return node
            target = target.get(part)
            if target is None:
                return node
        return deref_schema_ref(schema_root, target, _depth + 1)
    return node


def schema_node_for_path(schema_root: dict[str, Any], path: str) -> Any:
    """Walk ``properties`` to the schema node for the dotted *path*, or None."""
    node: Any = schema_root
    for segment in path.split("."):
        node = deref_schema_ref(schema_root, node)
        if not isinstance(node, dict):
            return None
        props = node.get("properties")
        if not isinstance(props, dict):
            return None
        node = props.get(segment)
        if node is None:
            return None
    return node


def array_item_type(schema_root: dict[str, Any], path: str) -> str | None:
    """The declared ``items.type`` for the array field at *path*, if any."""
    node = schema_node_for_path(schema_root, path)
    if node is None:
        return None
    node = deref_schema_ref(schema_root, node)
    items = node.get("items") if isinstance(node, dict) else None
    if not isinstance(items, dict):
        return None
    items = deref_schema_ref(schema_root, items)
    item_type = items.get("type") if isinstance(items, dict) else None
    return item_type if isinstance(item_type, str) else None


def looks_like_string_list(value: Any) -> bool:
    """True when *value* is a non-empty list of plain strings."""
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, str) for item in value)
    )


def editor_kind_for(
    field: ConfigField, schema_root: dict[str, Any], current_value: Any
) -> EditorKind:
    """Pick the typed editor for *field*.

    Enums always use the option cycle. Scalars map to bool / int / number /
    string by their JSON-Schema type(s). Arrays of strings get the line editor;
    every other array, open map, or mixed shape falls back to the raw-YAML
    escape hatch.
    """
    if field.enum_values:
        return "enum"
    if field.kind == "scalar":
        types = set(field.types)
        if types == {"boolean"}:
            return "bool"
        if "string" not in types and types & {"integer", "number"}:
            return "number" if "number" in types else "int"
        if isinstance(current_value, str) and "\n" in current_value:
            return "text"
        max_length = field.constraints.max_length
        if max_length is not None and max_length >= _LONG_STRING_TEXTAREA_MIN_LENGTH:
            return "text"
        return "string"
    if field.kind == "array":
        item_type = array_item_type(schema_root, field.path)
        if item_type == "string":
            return "string_list"
        if item_type is None and looks_like_string_list(current_value):
            return "string_list"
        return "yaml"
    return "yaml"


def yaml_dumps(value: Any) -> str:
    """Dump *value* as block YAML for the raw-YAML editor."""
    from ruamel.yaml import YAML

    handler = YAML()
    handler.default_flow_style = False
    handler.width = 4096
    buffer = io.StringIO()
    handler.dump(value, buffer)
    return buffer.getvalue()


def yaml_loads(text: str) -> Any:
    """Parse YAML *text* into plain Python types for the wire."""
    from ruamel.yaml import YAML

    handler = YAML(typ="safe")
    loaded = handler.load(io.StringIO(text))
    # Normalize to plain JSON-able types (the binding is JSON in/out).
    return json.loads(json.dumps(loaded)) if loaded is not None else None


def format_value_for_editor(kind: EditorKind, value: Any) -> str:
    """Render *value* as the initial text for a *kind* editor."""
    if kind in ("int", "number", "string", "text"):
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return value
        return str(value)
    if kind == "string_list":
        if isinstance(value, list):
            return "\n".join(str(item) for item in value)
        return ""
    if kind == "yaml":
        if value is None:
            return ""
        return yaml_dumps(value)
    return ""


def parse_editor_value(
    kind: EditorKind, text: str, field: ConfigField
) -> tuple[Any, str | None]:
    """Parse editor *text* for *kind*; return ``(value, error_or_None)``."""
    if kind == "int":
        stripped = text.strip()
        try:
            return check_constraints(int(stripped), field)
        except ValueError:
            return None, f"'{stripped}' is not an integer"
    if kind == "number":
        stripped = text.strip()
        try:
            return check_constraints(float(stripped), field)
        except ValueError:
            return None, f"'{stripped}' is not a number"
    if kind in ("string", "text"):
        return check_constraints(text, field)
    if kind == "string_list":
        items = [line.strip() for line in text.splitlines() if line.strip()]
        return items, None
    if kind == "yaml":
        try:
            return yaml_loads(text), None
        except Exception as exc:  # ruamel raises a variety of parse errors
            return None, f"invalid YAML: {exc}"
    return None, "unsupported editor"


def check_constraints(value: Any, field: ConfigField) -> tuple[Any, str | None]:
    """Apply the field's numeric/length constraints, returning an error if any."""
    constraints = field.constraints
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if constraints.minimum is not None and value < constraints.minimum:
            return None, f"must be ≥ {constraints.minimum}"
        if constraints.maximum is not None and value > constraints.maximum:
            return None, f"must be ≤ {constraints.maximum}"
        if (
            constraints.exclusive_minimum is not None
            and value <= constraints.exclusive_minimum
        ):
            return None, f"must be > {constraints.exclusive_minimum}"
        if (
            constraints.exclusive_maximum is not None
            and value >= constraints.exclusive_maximum
        ):
            return None, f"must be < {constraints.exclusive_maximum}"
    if isinstance(value, str):
        if constraints.min_length is not None and len(value) < constraints.min_length:
            return None, f"must be at least {constraints.min_length} char(s)"
        if constraints.max_length is not None and len(value) > constraints.max_length:
            return None, f"must be at most {constraints.max_length} char(s)"
        if constraints.pattern is not None:
            try:
                matches = re.search(constraints.pattern, value) is not None
            except re.error:
                matches = False
            if not matches:
                return None, f"must match pattern {constraints.pattern}"
    return value, None


def format_value(value: Any) -> str:
    """Compact display rendering of a config value."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


def list_strategy_banner(source: ConfigSource) -> Text:
    """Banner describing how a list write merges for *source*."""
    text = Text()
    if source.list_strategy == "replace":
        text.append("⚠ list replace: ", style=f"bold {_WARN_COLOR}")
        text.append(
            f"a list here replaces lower layers entirely ({source.name}).",
            style=_MUTED,
        )
    else:
        text.append("list append: ", style=f"bold {_OK_COLOR}")
        text.append(
            f"a list here is concatenated after lower layers ({source.name}).",
            style=_MUTED,
        )
    return text


def scope_label(source: ConfigSource) -> Text:
    """One-line label for a writable scope row."""
    text = Text()
    text.append(source.name, style=f"bold {_ACCENT}")
    suffix = " · new" if not source.exists else ""
    text.append(f"  ({source.list_strategy}{suffix})", style=_MUTED)
    return text


def initial_target(
    inventory: ConfigInventory, field: ConfigField, view: ConfigPaneView
) -> str | None:
    """Default writable target: where the field is already set, else policy.

    Prefers the highest-priority *writable* layer that currently contributes to
    the field (so "edit where it lives" is the default). Otherwise falls back to
    the research defaulting rules, forcing an explicit choice for list fields.
    """
    state = view.state_by_path.get(field.path)
    if state is not None:
        writable = {s.name for s in inventory.sources if s.writable}
        for contribution in reversed(state.contributions):
            if contribution.layer in writable:
                return contribution.layer
    force_explicit = field.kind == "array"
    target = default_target_layer(inventory, force_explicit=force_explicit)
    if target is not None:
        return target
    writable_sources = [s for s in inventory.sources if s.writable]
    return writable_sources[0].name if writable_sources else None
