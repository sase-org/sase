"""Macro input parsing for front matter definitions."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .models import (
    UNSET,
    InputArg,
    InputChoice,
    InputType,
    MacroValidationError,
)
from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class ResolvedInputType:
    """Python view of one type resolved by the Rust input-type catalog."""

    base: InputType
    named_type: str | None
    value_role: str | None
    choices: tuple[InputChoice, ...] = ()
    warnings: tuple[str, ...] = ()


def _plugin_registry_snapshot() -> dict[str, Any] | None:
    """Return the cached plugin registry snapshot for the resolver."""
    try:
        from .plugin_input_types import get_plugin_input_type_registry
    except Exception:
        return None
    try:
        snapshot = get_plugin_input_type_registry()
    except Exception:
        return None
    registry = snapshot.get("registry")
    return registry if isinstance(registry, dict) else None


def parse_input_type(
    raw: Any,
    *,
    name: str = "input",
    source_path: str | None = None,
) -> ResolvedInputType:
    """Resolve a raw YAML type through the shared Rust catalog.

    Unknown names keep their historical ``line`` fallback only while the
    ``strict_macro_input_types`` sunset flag is disabled. Deprecated spellings
    are accepted and surfaced as load warnings regardless of that flag.
    """
    request: dict[str, Any] = {"name": name, "raw": raw}
    registry = _plugin_registry_snapshot()
    if registry is not None:
        request["registry"] = registry
    try:
        resolved = require_rust_binding("resolve_input_type")(request)
    except ValueError as exc:
        message = str(exc)
        if "unknown type" in message.casefold():
            from sase.feature_flags import FeatureFlag, current_flags

            if not current_flags().enabled(FeatureFlag.strict_macro_input_types):
                return ResolvedInputType(
                    base=InputType.LINE,
                    named_type=None,
                    value_role=None,
                )
        raise MacroValidationError(message) from None

    choices = tuple(
        InputChoice(
            value=str(item["value"]),
            label=None if item.get("label") is None else str(item["label"]),
            description=(
                None if item.get("description") is None else str(item["description"])
            ),
        )
        for item in resolved.get("choices", [])
    )
    warnings: tuple[str, ...] = ()
    if resolved.get("deprecated"):
        warnings = (
            f"input `{name}` uses deprecated type `string`; use `line` instead",
        )

    result = ResolvedInputType(
        base=InputType(str(resolved["base"])),
        named_type=resolved.get("named_type"),
        value_role=resolved.get("value_role"),
        choices=choices,
        warnings=warnings,
    )
    if source_path is not None:
        from .load_issues import record_load_issue

        for warning in result.warnings:
            record_load_issue(source_path, warning, kind="input_type_warning")
    return result


def _parse_input_choices(
    raw: Any,
    name: str,
    *,
    source_path: str | None = None,
) -> tuple[InputChoice, ...]:
    """Parse an enum input's ``choices`` value into :class:`InputChoice` tuples.

    Args:
        raw: A raw YAML list of scalar values or ``{value, label, description}``
            mappings. Values are passed to Rust without Python coercion.
        name: The owning input's name, used in error messages.

    Returns:
        Tuple of :class:`InputChoice` objects, in declared order.

    Raises:
        MacroValidationError: If Rust reports invalid choices or choice values.
    """
    try:
        result = require_rust_binding("validate_enum_choices")({"items": raw})
    except ValueError as exc:
        raise MacroValidationError(str(exc)) from None
    choices = tuple(
        InputChoice(
            value=str(item["value"]),
            label=None if item.get("label") is None else str(item["label"]),
            description=(
                None if item.get("description") is None else str(item["description"])
            ),
        )
        for item in result.get("choices", [])
    )
    first_error: str | None = None
    for issue in result.get("issues", []):
        message = str(issue.get("message", "invalid enum choice"))
        if issue.get("severity") == "error":
            first_error = first_error or message
        elif issue.get("severity") == "warning" and source_path is not None:
            from .load_issues import record_load_issue

            record_load_issue(source_path, message, kind="input_type_warning")
    if first_error is not None:
        raise MacroValidationError(first_error)
    if not isinstance(raw, list) or not raw:
        raise MacroValidationError(
            f"Argument '{name}' choices must be a non-empty list"
        )
    return choices


def parse_input_definition(
    *,
    name: str,
    type_raw: Any,
    default: Any,
    description: str | None,
    repeatable: bool,
    choices_raw: Any,
    source_path: str | None,
) -> InputArg:
    """Build one input definition from raw frontmatter values."""
    resolved = parse_input_type(
        type_raw,
        name=name,
        source_path=source_path,
    )
    if choices_raw is not None and resolved.named_type is not None:
        raise MacroValidationError(
            f"input `{name}` uses type `{resolved.named_type}` which already "
            "defines its values; remove `choices`"
        )
    choices = resolved.choices
    if choices_raw is not None:
        choices = _parse_input_choices(
            choices_raw,
            name,
            source_path=source_path,
        )
    _validate_enum_default(name, default, choices, resolved.base)
    return InputArg(
        name=name,
        type=resolved.base,
        default=default,
        description=description,
        repeatable=repeatable,
        choices=choices,
        named_type=resolved.named_type,
        value_role=resolved.value_role,
    )


def _validate_enum_default(
    name: str,
    default: Any,
    choices: tuple[InputChoice, ...],
    input_type: InputType,
) -> None:
    if (
        input_type is not InputType.ENUM
        or not choices
        or default is UNSET
        or default is None
    ):
        return
    if not isinstance(default, str):
        scalar_name = (
            "a boolean"
            if isinstance(default, bool)
            else "an int"
            if isinstance(default, int)
            else "a float"
            if isinstance(default, float)
            else type(default).__name__
        )
        raise MacroValidationError(
            f"Argument '{name}' default arrived as {scalar_name} and must be a quoted choice"
        )
    values = tuple(choice.value for choice in choices)
    if default in values:
        return
    allowed = " | ".join(values) if len(values) <= 8 else f"{len(values)} choices"
    raise MacroValidationError(f"default `{default}` is not one of {allowed}")


def _parse_shortform_input_metadata(
    name: str,
    value: Any,
) -> tuple[Any, Any, str | None, bool, Any]:
    """Parse raw shortform metadata without coercing YAML input-type scalars."""
    if isinstance(value, dict):
        type_str = value.get("type", "line")
        default = value.get("default", UNSET)
        description_value = value.get("description")
        description = None if description_value is None else str(description_value)
        repeatable = value.get("repeatable", False) is True
        choices_value = value.get("choices")
        return type_str, default, description, repeatable, choices_value

    return value, UNSET, None, False, None


def parse_shortform_inputs(
    input_dict: Mapping[str, Any],
    *,
    source_path: str | None = None,
) -> list[InputArg]:
    """Parse shortform input dict to list of InputArg.

    Args:
        input_dict: Dict mapping name to type string or dict with type/default.
            Example: {"diff_path": "path", "bug_flag": {"type": "line", "default": ""}}

    Returns:
        List of InputArg objects.
    """
    inputs: list[InputArg] = []
    for name, value in input_dict.items():
        type_raw, default, description, repeatable, choices_raw = (
            _parse_shortform_input_metadata(name, value)
        )
        inputs.append(
            parse_input_definition(
                name=name,
                type_raw=type_raw,
                default=default,
                description=description,
                repeatable=repeatable,
                choices_raw=choices_raw,
                source_path=source_path,
            )
        )
    from .input_binding import validate_repeatable_input_order

    validate_repeatable_input_order(inputs)
    return inputs


def parse_inputs_from_front_matter(
    input_data: list[dict[str, Any]] | dict[str, Any] | None,
    *,
    source_path: str | None = None,
) -> list[InputArg]:
    """Parse input definitions from front matter.

    Supports both longform (list of dicts) and shortform (dict) syntax.

    Args:
        input_data: Either a list of input dicts (longform) or a dict (shortform).
            Longform: [{"name": "foo", "type": "word", "default": ""}]
            Shortform: {"foo": "word", "bar": {"type": "line", "default": ""}}

    Returns:
        List of InputArg objects.
    """
    if not input_data:
        return []

    # Handle shortform dict syntax
    if isinstance(input_data, dict):
        return parse_shortform_inputs(input_data, source_path=source_path)

    # Handle longform list syntax
    inputs: list[InputArg] = []
    for item in input_data:
        if not isinstance(item, dict) or "name" not in item:
            continue

        name = str(item["name"])
        type_raw = item.get("type", "line")
        default = item.get("default", UNSET)
        description_value = item.get("description")
        description = None if description_value is None else str(description_value)
        repeatable = item.get("repeatable", False) is True
        choices_value = item.get("choices")
        inputs.append(
            parse_input_definition(
                name=name,
                type_raw=type_raw,
                default=default,
                description=description,
                repeatable=repeatable,
                choices_raw=choices_value,
                source_path=source_path,
            )
        )

    from .input_binding import validate_repeatable_input_order

    validate_repeatable_input_order(inputs)
    return inputs
