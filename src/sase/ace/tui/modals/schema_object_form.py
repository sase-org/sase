"""Pure sparse editor model for one JSON-Schema object.

The model deliberately has no Textual or file-system dependencies.  It keeps
the effective object separate from the selected layer's raw contribution and
only emits operations for fields the user touched.  That prevents an overlay
edit from copying inherited defaults into the target layer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from sase.config import ConfigEditOp, ConfigField
from sase.config.inventory import ConfigConstraints

from .config_edit_helpers import check_constraints, parse_editor_value
from .config_edit_types import EditorKind


SchemaFieldGroup = Literal["basics", "advanced"]
SchemaOperationKind = Literal["set", "unset"]
_LIVE_YAML_PARSE_MAX_BYTES = 16_000
_MISSING = object()


@dataclass(frozen=True)
class SchemaFieldDiagnostic:
    """A parse, constraint, or required-field problem."""

    field: str
    message: str
    code: str
    severity: str = "error"


@dataclass(frozen=True)
class SchemaFieldOperation:
    """An exact-segment set/unset operation for a schema property."""

    key_path: tuple[str, ...]
    kind: SchemaOperationKind
    value: Any = None

    @classmethod
    def set_value(cls, key_path: Sequence[str], value: Any) -> SchemaFieldOperation:
        return cls(tuple(key_path), "set", value)

    @classmethod
    def unset(cls, key_path: Sequence[str]) -> SchemaFieldOperation:
        return cls(tuple(key_path), "unset")

    @property
    def path_segments(self) -> tuple[str, ...]:
        """Readable alias emphasizing that dotted names are never split."""
        return self.key_path

    def to_config_edit_op(self) -> ConfigEditOp:
        if self.kind == "unset":
            return ConfigEditOp.unset()
        return ConfigEditOp.set_value(self.value)

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key_path": list(self.key_path),
            "kind": self.kind,
        }
        if self.kind == "set":
            payload["value"] = self.value
        return payload


@dataclass(frozen=True)
class _SchemaObjectPatch:
    """Pure sparse patch plus diagnostics produced from a form."""

    operations: tuple[SchemaFieldOperation, ...]
    diagnostics: tuple[SchemaFieldDiagnostic, ...]

    @property
    def is_valid(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)


@dataclass(frozen=True)
class _ParsedSchemaValue:
    """Result of parsing one editor buffer."""

    value: Any
    error: str | None = None
    deferred: bool = False


@dataclass(frozen=True)
class SchemaObjectField:
    """Immutable edit state and schema metadata for one direct property."""

    name: str
    key_path: tuple[str, ...]
    group: SchemaFieldGroup
    required: bool
    description: str
    types: tuple[str, ...]
    enum_values: tuple[Any, ...]
    constraints: ConfigConstraints
    editor_kind: EditorKind
    compound: bool
    schema: Mapping[str, Any]
    has_effective: bool
    effective_value: Any
    has_target: bool
    target_value: Any
    has_inherited: bool
    inherited_value: Any
    provenance: tuple[str, ...]
    touched: bool = False
    reset: bool = False
    included: bool = False
    draft_value: Any = None
    draft_text: str | None = None
    parse_error: str | None = None
    parse_deferred: bool = False

    @property
    def source(self) -> str | None:
        return self.provenance[-1] if self.provenance else None

    @property
    def explicit_inherit(self) -> bool:
        return self.reset

    @property
    def operation(self) -> SchemaFieldOperation | None:
        """Return the sparse operation represented by this state, if valid."""
        if not self.touched:
            return None
        if self.reset:
            return SchemaFieldOperation.unset(self.key_path)
        if self.parse_error is not None:
            return None
        return SchemaFieldOperation.set_value(self.key_path, self.draft_value)

    def as_config_field(self) -> ConfigField:
        """Adapt the schema metadata to Config Center's parsing helpers."""
        kind = "array" if "array" in self.types else "scalar"
        if self.compound and "array" not in self.types:
            kind = "map" if "object" in self.types else "scalar"
        return ConfigField(
            path=self.name,
            name=self.name,
            depth=0,
            parent=None,
            kind=kind,
            leaf=True,
            types=self.types,
            description=self.description,
            has_default="default" in self.schema,
            default=self.schema.get("default"),
            enum_values=self.enum_values,
            deprecated=bool(self.schema.get("deprecated", False)),
            deprecated_replacement=None,
            constraints=self.constraints,
            additional_properties_allowed=self.schema.get("additionalProperties", False)
            is not False,
        )


@dataclass(frozen=True)
class SchemaObjectForm:
    """Immutable ordered form for a schema-defined object."""

    fields: tuple[SchemaObjectField, ...]
    key_prefix: tuple[str, ...] = ()

    @classmethod
    def build(
        cls,
        *,
        schema_root: Mapping[str, Any],
        object_schema: Mapping[str, Any] | str,
        effective_values: Mapping[str, Any] | None = None,
        target_values: Mapping[str, Any] | None = None,
        inherited_values: Mapping[str, Any] | None = None,
        provenance: Mapping[str, str | Sequence[str]] | None = None,
        key_prefix: Sequence[str] = (),
        basics: Sequence[str] = (),
        advanced: Sequence[str] = (),
        groups: Mapping[str, SchemaFieldGroup] | None = None,
        initially_included: Iterable[str] = (),
    ) -> SchemaObjectForm:
        """Build an ordered form, resolving local refs without any I/O."""
        if isinstance(object_schema, str):
            node: Any = {"$ref": object_schema}
        else:
            node = object_schema
        resolved = resolve_schema_node(schema_root, node)
        if not isinstance(resolved, Mapping):
            raise ValueError("object schema did not resolve to a mapping")
        properties = resolved.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError("object schema properties must be a mapping")
        required_raw = resolved.get("required", ())
        required = (
            {str(name) for name in required_raw}
            if isinstance(required_raw, Sequence) and not isinstance(required_raw, str)
            else set()
        )
        effective = effective_values or {}
        target = target_values or {}
        inherited = inherited_values or {}
        provenance_map = provenance or {}
        included_names = set(initially_included)
        ordered_names = _order_schema_properties(
            tuple(str(name) for name in properties),
            required=required,
            basics=basics,
            advanced=advanced,
            groups=groups,
        )
        fields: list[SchemaObjectField] = []
        for name in ordered_names:
            raw_property = properties[name]
            property_schema = resolve_schema_node(schema_root, raw_property)
            if not isinstance(property_schema, Mapping):
                property_schema = {}
            has_effective = name in effective
            has_target = name in target
            has_inherited = name in inherited
            draft = (
                effective[name]
                if has_effective
                else property_schema.get("default", None)
            )
            source_value = provenance_map.get(name, ())
            if isinstance(source_value, str):
                sources: tuple[str, ...] = (source_value,)
            else:
                sources = tuple(str(source) for source in source_value)
            group = _schema_property_group(
                name,
                basics=basics,
                advanced=advanced,
                groups=groups,
            )
            editor_kind, compound = _schema_editor_kind(property_schema, draft)
            fields.append(
                SchemaObjectField(
                    name=name,
                    key_path=(*tuple(key_prefix), name),
                    group=group,
                    required=name in required,
                    description=str(property_schema.get("description", "")),
                    types=_schema_types(property_schema),
                    enum_values=tuple(property_schema.get("enum", ())),
                    constraints=_schema_constraints(property_schema),
                    editor_kind=editor_kind,
                    compound=compound,
                    schema=property_schema,
                    has_effective=has_effective,
                    effective_value=effective.get(name),
                    has_target=has_target,
                    target_value=target.get(name),
                    has_inherited=has_inherited,
                    inherited_value=inherited.get(name),
                    provenance=sources,
                    included=(
                        name in required
                        or has_effective
                        or has_target
                        or name in included_names
                    ),
                    draft_value=draft,
                )
            )
        return cls(tuple(fields), tuple(key_prefix))

    @classmethod
    def from_schema(cls, **kwargs: Any) -> SchemaObjectForm:
        """Alias for callers that prefer constructor-style naming."""
        return cls.build(**kwargs)

    def field(self, name: str) -> SchemaObjectField:
        for field in self.fields:
            if field.name == name:
                return field
        raise KeyError(name)

    def visible_fields(
        self, group: SchemaFieldGroup | None = None
    ) -> tuple[SchemaObjectField, ...]:
        return tuple(
            field
            for field in self.fields
            if field.included and (group is None or field.group == group)
        )

    def addable_fields(
        self, group: SchemaFieldGroup | None = None
    ) -> tuple[SchemaObjectField, ...]:
        return tuple(
            field
            for field in self.fields
            if not field.included and (group is None or field.group == group)
        )

    def include(self, name: str) -> SchemaObjectForm:
        return self._replace(name, included=True)

    def set_value(self, name: str, value: Any) -> SchemaObjectForm:
        field = self.field(name)
        error = _validate_schema_value(field, value)
        return self._replace(
            name,
            included=True,
            touched=True,
            reset=False,
            draft_value=value,
            draft_text=None,
            parse_error=error,
            parse_deferred=False,
        )

    def edit(self, name: str, value: Any) -> SchemaObjectForm:
        return self.set_value(name, value)

    def set_text(self, name: str, text: str, *, live: bool = True) -> SchemaObjectForm:
        field = self.field(name)
        parsed = _parse_schema_field_value(field, text, live=live)
        return self._replace(
            name,
            included=True,
            touched=True,
            reset=False,
            draft_value=(field.draft_value if parsed.deferred else parsed.value),
            draft_text=text,
            parse_error=parsed.error,
            parse_deferred=parsed.deferred,
        )

    def edit_text(self, name: str, text: str, *, live: bool = True) -> SchemaObjectForm:
        return self.set_text(name, text, live=live)

    def reset_field(self, name: str) -> SchemaObjectForm:
        return self._replace(
            name,
            included=True,
            touched=True,
            reset=True,
            parse_error=None,
            parse_deferred=False,
        )

    def inherit(self, name: str) -> SchemaObjectForm:
        return self.reset_field(name)

    def clear_change(self, name: str) -> SchemaObjectForm:
        field = self.field(name)
        draft = (
            field.effective_value
            if field.has_effective
            else field.schema.get("default", None)
        )
        return self._replace(
            name,
            touched=False,
            reset=False,
            draft_value=draft,
            draft_text=None,
            parse_error=None,
            parse_deferred=False,
        )

    def diagnostics(self) -> tuple[SchemaFieldDiagnostic, ...]:
        return self.patch().diagnostics

    def operations(self) -> tuple[SchemaFieldOperation, ...]:
        return self.patch().operations

    def to_operations(self) -> tuple[SchemaFieldOperation, ...]:
        return self.operations()

    def patch(self) -> _SchemaObjectPatch:
        operations: list[SchemaFieldOperation] = []
        diagnostics: list[SchemaFieldDiagnostic] = []
        for field in self.fields:
            final_field = field
            if field.touched and not field.reset and field.parse_deferred:
                parsed = _parse_schema_field_value(
                    field,
                    field.draft_text or "",
                    live=False,
                )
                final_field = replace(
                    field,
                    draft_value=parsed.value,
                    parse_error=parsed.error,
                    parse_deferred=False,
                )
            if final_field.parse_error is not None:
                diagnostics.append(
                    SchemaFieldDiagnostic(
                        field=field.name,
                        message=final_field.parse_error,
                        code="parse",
                    )
                )
                continue
            if _required_field_missing(final_field):
                diagnostics.append(
                    SchemaFieldDiagnostic(
                        field=field.name,
                        message="required field must have a value",
                        code="required",
                    )
                )
            operation = final_field.operation
            if operation is not None:
                operations.append(operation)
        return _SchemaObjectPatch(tuple(operations), tuple(diagnostics))

    def _replace(self, name: str, **changes: Any) -> SchemaObjectForm:
        found = False
        fields: list[SchemaObjectField] = []
        for field in self.fields:
            if field.name == name:
                found = True
                fields.append(replace(field, **changes))
            else:
                fields.append(field)
        if not found:
            raise KeyError(name)
        return replace(self, fields=tuple(fields))


# More explicit public alias used by the AXE modal and integrations.
SchemaObjectFormModel = SchemaObjectForm
SchemaFormModel = SchemaObjectForm


def resolve_schema_node(
    schema_root: Mapping[str, Any], node: Any, *, _depth: int = 0
) -> Any:
    """Resolve local ``$ref`` values, retaining sibling annotations.

    JSON Pointer escaping is honored, so refs to keys containing ``/`` or ``~``
    are deterministic.  Cycles and malformed refs are left unresolved instead
    of recursing forever.
    """
    if not isinstance(node, Mapping) or _depth > 32:
        return node
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return dict(node)
    target: Any = schema_root
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, Mapping) or part not in target:
            return dict(node)
        target = target[part]
    resolved = resolve_schema_node(schema_root, target, _depth=_depth + 1)
    if not isinstance(resolved, Mapping):
        return resolved
    siblings = {key: value for key, value in node.items() if key != "$ref"}
    return {**resolved, **siblings}


def _order_schema_properties(
    names: Sequence[str],
    *,
    required: set[str] | frozenset[str] = frozenset(),
    basics: Sequence[str] = (),
    advanced: Sequence[str] = (),
    groups: Mapping[str, SchemaFieldGroup] | None = None,
) -> tuple[str, ...]:
    """Return deterministic Basics/Advanced, required-first schema order."""
    schema_index = {name: index for index, name in enumerate(names)}
    preferred = {
        name: index for index, name in enumerate((*tuple(basics), *tuple(advanced)))
    }

    def key(name: str) -> tuple[int, int, int, int]:
        group = _schema_property_group(
            name, basics=basics, advanced=advanced, groups=groups
        )
        return (
            0 if group == "basics" else 1,
            0 if name in required else 1,
            preferred.get(name, len(preferred) + schema_index[name]),
            schema_index[name],
        )

    return tuple(sorted(names, key=key))


def _schema_property_group(
    name: str,
    *,
    basics: Sequence[str] = (),
    advanced: Sequence[str] = (),
    groups: Mapping[str, SchemaFieldGroup] | None = None,
) -> SchemaFieldGroup:
    if groups is not None and name in groups:
        return groups[name]
    if name in advanced:
        return "advanced"
    if name in basics:
        return "basics"
    return "basics"


def _schema_types(node: Mapping[str, Any]) -> tuple[str, ...]:
    raw = node.get("type")
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, Sequence) and not isinstance(raw, str):
        return tuple(str(item) for item in raw)
    enum = node.get("enum")
    if isinstance(enum, Sequence) and enum:
        inferred = {_json_type(value) for value in enum}
        return tuple(sorted(inferred))
    return ()


def _schema_constraints(node: Mapping[str, Any]) -> ConfigConstraints:
    return ConfigConstraints(
        minimum=_number_or_none(node.get("minimum")),
        maximum=_number_or_none(node.get("maximum")),
        exclusive_minimum=_number_or_none(node.get("exclusiveMinimum")),
        exclusive_maximum=_number_or_none(node.get("exclusiveMaximum")),
        min_length=_int_or_none(node.get("minLength")),
        max_length=_int_or_none(node.get("maxLength")),
        pattern=str(node["pattern"]) if isinstance(node.get("pattern"), str) else None,
    )


def _schema_editor_kind(
    node: Mapping[str, Any], effective_value: Any = None
) -> tuple[EditorKind, bool]:
    """Select a typed editor; compound or ambiguous shapes always use YAML."""
    enum_values = node.get("enum")
    if isinstance(enum_values, Sequence) and not isinstance(enum_values, str):
        return "enum", False
    if any(key in node for key in ("oneOf", "anyOf", "allOf", "not")):
        return "yaml", True
    types = set(_schema_types(node))
    if len(types) != 1:
        return "yaml", True
    kind = next(iter(types))
    if kind == "boolean":
        return "bool", False
    if kind == "integer":
        return "int", False
    if kind == "number":
        return "number", False
    if kind == "string":
        if isinstance(effective_value, str) and "\n" in effective_value:
            return "text", False
        if (_int_or_none(node.get("maxLength")) or 0) >= 240:
            return "text", False
        return "string", False
    if kind == "array":
        items = node.get("items")
        if isinstance(items, Mapping) and _schema_types(items) == ("string",):
            return "string_list", False
        return "yaml", True
    return "yaml", True


def _parse_schema_field_value(
    field: SchemaObjectField, text: str, *, live: bool = True
) -> _ParsedSchemaValue:
    """Parse one field using Config Center's typed parsers.

    Large YAML is intentionally deferred during live editing and parsed only
    when a patch/preview is requested.
    """
    if (
        live
        and field.editor_kind == "yaml"
        and len(text.encode("utf-8", errors="replace")) > _LIVE_YAML_PARSE_MAX_BYTES
    ):
        return _ParsedSchemaValue(field.draft_value, deferred=True)
    value, error = parse_editor_value(field.editor_kind, text, field.as_config_field())
    if error is None:
        error = _validate_schema_value(field, value)
    return _ParsedSchemaValue(value, error=error)


def _validate_schema_value(field: SchemaObjectField, value: Any) -> str | None:
    """Apply direct type and scalar constraints without schema/file access."""
    types = set(field.types)
    value_type = _json_type(value)
    type_matches = value_type in types or (
        value_type == "integer" and "number" in types
    )
    if types and not type_matches:
        return f"must be {' or '.join(sorted(types))}"
    if field.enum_values and value not in field.enum_values:
        return "must be one of " + ", ".join(str(item) for item in field.enum_values)
    _checked, error = check_constraints(value, field.as_config_field())
    return error


def _required_field_missing(field: SchemaObjectField) -> bool:
    if not field.required:
        return False
    if field.touched and field.reset:
        return not field.has_inherited
    if field.touched:
        return field.draft_value is None
    return not field.has_effective and "default" not in field.schema


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _int_or_none(value: Any) -> int | None:
    return (
        int(value) if isinstance(value, int) and not isinstance(value, bool) else None
    )


__all__ = [
    "SchemaFieldDiagnostic",
    "SchemaFieldGroup",
    "SchemaFieldOperation",
    "SchemaObjectField",
    "SchemaObjectForm",
    "SchemaObjectFormModel",
    "resolve_schema_node",
]
