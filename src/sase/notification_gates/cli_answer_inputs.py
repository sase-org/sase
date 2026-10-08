"""CLI value parsing for ``sase gate answer``.

This module turns CLI words into the arguments the shared gate entry
points take: which options were selected, which typed input values go
with them, and which operation-request fields override the flags. All
``--set`` type coercion lives here, next to the only callers that need
it.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sase.macro.models import InputType
from sase.notification_gates.cli_support import (
    GateCliError,
    JsonArgumentReader,
    split_assignment,
)
from sase.notification_gates.model_inputs import GateInputField
from sase.notification_gates.model_options import GateOption

_TRUE_WORDS = frozenset({"1", "on", "true", "yes", "y"})
_FALSE_WORDS = frozenset({"0", "off", "false", "no", "n"})


def request_review_revision(payload: Mapping[str, Any]) -> int | None:
    """Validate the operation-request ``review_revision`` using wire rules.

    A missing revision stays missing for older-client compatibility. A
    present revision must be an integer: booleans, non-integral numbers,
    and malformed strings raise instead of silently disabling the check.
    """
    if "review_revision" not in payload:
        return None
    raw = payload.get("review_revision")
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise GateCliError("review_revision must be an integer, got a boolean")
    if isinstance(raw, int):
        return int(raw)
    if isinstance(raw, float):
        if not raw.is_integer():
            raise GateCliError(f"review_revision must be an integer, got {raw!r}")
        return int(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise GateCliError("review_revision must be an integer, got empty text")
        body = text[1:] if text[:1] in ("+", "-") else text
        if not body.isdigit():
            raise GateCliError(f"review_revision must be an integer, got {raw!r}")
        try:
            return int(text)
        except ValueError as exc:
            raise GateCliError(
                f"review_revision must be an integer, got {raw!r}"
            ) from exc
    raise GateCliError(f"review_revision must be an integer, got {type(raw).__name__}")


def request_option_ids(payload: Mapping[str, Any]) -> list[str]:
    """Read the operation-request ``option_ids`` list, tolerantly."""
    raw = payload.get("option_ids")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def request_option_inputs(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read the operation-request ``option_inputs`` object, strictly."""
    raw = payload.get("option_inputs")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise GateCliError("operation request option_inputs must be an object")
    return {str(key): value for key, value in raw.items()}


def request_source(payload: Mapping[str, Any]) -> str | None:
    """Read the operation-request ``source`` tag, tolerantly."""
    raw = payload.get("source")
    if not isinstance(raw, str):
        return None
    source = raw.strip()
    return source or None


def resolve_selection(
    options: Sequence[GateOption], requested: Sequence[str]
) -> tuple[GateOption, ...]:
    """Map requested option ids onto declared options, in requested order."""
    if not requested:
        raise GateCliError("--option is required at least once")
    by_id = {option.id: option for option in options}
    unknown = [option_id for option_id in requested if option_id not in by_id]
    if unknown:
        known = ", ".join(sorted(by_id))
        raise GateCliError(
            f"gate declares no option(s): {', '.join(unknown)}; declared: {known}"
        )
    duplicates = sorted({value for value in requested if requested.count(value) > 1})
    if duplicates:
        raise GateCliError(f"--option repeated: {', '.join(duplicates)}")
    return tuple(by_id[option_id] for option_id in requested)


def read_shared_input(
    args: argparse.Namespace, reader: JsonArgumentReader
) -> object | None:
    """Read one shared ``--input`` JSON value, if the flags carry one."""
    raw = getattr(args, "input", None)
    if raw is None:
        return None
    return reader.read(str(raw), target="--input")


def retry_choice(args: argparse.Namespace) -> Literal["resume", "restart"] | None:
    """Map the ``--resume``/``--restart`` flags onto one retry directive."""
    if bool(getattr(args, "resume", False)):
        return "resume"
    if bool(getattr(args, "restart", False)):
        return "restart"
    return None


def build_per_option_inputs(
    args: argparse.Namespace,
    selected: tuple[GateOption, ...],
    reader: JsonArgumentReader,
) -> dict[str, Any] | None:
    """Build the per-option submission from ``--option-input`` and ``--set``."""
    whole_values = _whole_option_values(args, selected, reader)
    field_values = _field_option_values(args, selected)
    overlap = sorted(set(whole_values) & set(field_values))
    if overlap:
        raise GateCliError(
            "--option-input already submits the whole value for option(s) "
            f"{', '.join(overlap)}; --set cannot also target them"
        )
    if not whole_values and not field_values:
        return None
    return {**whole_values, **field_values}


def _whole_option_values(
    args: argparse.Namespace,
    selected: tuple[GateOption, ...],
    reader: JsonArgumentReader,
) -> dict[str, Any]:
    selected_ids = {option.id for option in selected}
    values: dict[str, Any] = {}
    for raw in getattr(args, "option_input", None) or []:
        option_id, source = split_assignment(str(raw), target="--option-input")
        if option_id not in selected_ids:
            raise GateCliError(
                f"--option-input targets an unselected option: {option_id}"
            )
        if option_id in values:
            raise GateCliError(f"--option-input repeated for option: {option_id}")
        values[option_id] = reader.read(source, target=f"--option-input {option_id}")
    return values


def _field_option_values(
    args: argparse.Namespace, selected: tuple[GateOption, ...]
) -> dict[str, dict[str, Any]]:
    """Broadcast every ``--set`` key to each selected option that accepts it.

    A key no selected option accepts is a usage error rather than a schema
    failure at submission time: the reviewer learns which keys exist while
    they can still fix the command line.
    """
    raw_values: dict[str, dict[str, list[str]]] = {}
    for raw in getattr(args, "set", None) or []:
        key, value = split_assignment(str(raw), target="--set")
        accepting = [option for option in selected if _option_accepts_key(option, key)]
        if not accepting:
            raise GateCliError(
                f"--set {key}: no selected option accepts that input; "
                f"accepted: {_accepted_keys(selected)}"
            )
        for option in accepting:
            raw_values.setdefault(option.id, {}).setdefault(key, []).append(value)

    values: dict[str, dict[str, Any]] = {}
    for option in selected:
        for key, entries in raw_values.get(option.id, {}).items():
            values.setdefault(option.id, {})[key] = _coerce_set_value(
                option, key, entries
            )
    return values


def _option_accepts_key(option: GateOption, key: str) -> bool:
    """Whether ``key`` can appear in this option's submitted input value."""
    properties = option.input_schema.get("properties")
    if isinstance(properties, Mapping) and key in properties:
        return True
    return option.input_schema.get("additionalProperties") is not False


def _accepted_keys(selected: Sequence[GateOption]) -> str:
    keys: set[str] = set()
    open_options: list[str] = []
    for option in selected:
        properties = option.input_schema.get("properties")
        if isinstance(properties, Mapping):
            keys.update(str(key) for key in properties)
        if option.input_schema.get("additionalProperties") is not False:
            open_options.append(option.id)
    rendered = ", ".join(sorted(keys)) if keys else "(none declared)"
    if open_options:
        rendered += f"; any key for option(s) {', '.join(sorted(open_options))}"
    return rendered


def _declared_field(option: GateOption, key: str) -> GateInputField | None:
    for field in option.inputs:
        if field.id == key:
            return field
    return None


def _coerce_set_value(option: GateOption, key: str, entries: list[str]) -> Any:
    """Type one ``--set`` value from a declared field or the raw schema."""
    field = _declared_field(option, key)
    if field is not None:
        return _coerce_field_value(field, entries, key=key, option_id=option.id)
    if len(entries) > 1:
        raise GateCliError(
            f"--set {key} (option {option.id}): repeated, but the field is not "
            "repeatable"
        )
    return _coerce_schema_scalar(option, key, entries[0])


def _schema_property_type(option: GateOption, key: str) -> str | None:
    properties = option.input_schema.get("properties")
    if not isinstance(properties, Mapping):
        return None
    spec = properties.get(key)
    if not isinstance(spec, Mapping):
        return None
    schema_type = spec.get("type")
    return schema_type if isinstance(schema_type, str) else None


def _coerce_schema_scalar(option: GateOption, key: str, raw: str) -> Any:
    """Coerce a raw-schema ``--set`` value so integer properties stay integers."""
    target = f"--set {key} (option {option.id})"
    if _schema_property_type(option, key) != "integer":
        return raw
    text = raw.strip()
    body = text[1:] if text.startswith(("+", "-")) else text
    if not body.isdigit():
        raise GateCliError(f"{target}: expected an integer, got {raw!r}")
    return int(text)


def _coerce_field_value(
    field: GateInputField | None,
    entries: list[str],
    *,
    key: str,
    option_id: str,
) -> Any:
    """Type one ``--set`` value by its declared field, or keep it a string."""
    target = f"--set {key} (option {option_id})"
    if field is not None and field.repeatable:
        return [_coerce_scalar(field, entry, target=target) for entry in entries]
    if len(entries) > 1:
        raise GateCliError(f"{target}: repeated, but the field is not repeatable")
    return _coerce_scalar(field, entries[0], target=target)


def _coerce_scalar(field: GateInputField | None, raw: str, *, target: str) -> Any:
    if field is None:
        return raw
    if field.type is InputType.BOOL:
        lowered = raw.strip().lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
        raise GateCliError(f"{target}: expected a boolean, got {raw!r}")
    if field.type is InputType.INT:
        try:
            return int(raw.strip())
        except ValueError as exc:
            raise GateCliError(f"{target}: expected an integer, got {raw!r}") from exc
    if field.type is InputType.FLOAT:
        try:
            return float(raw.strip())
        except ValueError as exc:
            raise GateCliError(f"{target}: expected a number, got {raw!r}") from exc
    if field.type is InputType.ENUM:
        allowed = [choice.value for choice in field.choices]
        if raw not in allowed:
            raise GateCliError(
                f"{target}: expected one of {', '.join(allowed)}, got {raw!r}"
            )
    return raw


__all__ = [
    "build_per_option_inputs",
    "read_shared_input",
    "request_option_ids",
    "request_option_inputs",
    "request_review_revision",
    "request_source",
    "resolve_selection",
    "retry_choice",
]
