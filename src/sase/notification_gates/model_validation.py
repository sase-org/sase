"""Shared validation helpers for notification gate models."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, Literal

LEGACY_GATE_REQUEST_SCHEMA_VERSION = 2
GATE_REQUEST_SCHEMA_VERSION = 3
GATE_RESPONSE_SCHEMA_VERSION = 2
GATE_RESULT_SCHEMA_VERSION = 2

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OPTION_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_MAX_GATE_LABEL_LENGTH = 160
_MAX_GATE_ICON_CODEPOINTS = 32
_MAX_GATE_ICON_BYTES = 128
_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")

GateFeedbackMode = Literal["disabled", "optional", "required"]

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_ACCEPTED_SCHEMA_DIALECTS = {JSON_SCHEMA_DIALECT, f"{JSON_SCHEMA_DIALECT}#"}

#: Bounds shared by the creation-time schema check and the submission-time
#: input check, so an author learns at ``sase gate create`` rather than at
#: submit time. :mod:`sase.notification_gates.input_bounds` re-exports them.
MAX_INPUT_BYTES = 64 * 1024
MAX_INPUT_DEPTH = 16
MAX_OBJECT_PROPERTIES = 128
MAX_ARRAY_ITEMS = 512

#: The schema an option gets when it declares neither ``inputs`` nor
#: ``input_schema``: the honest reading of "this command takes no input".
NO_INPUT_SCHEMA: dict[str, Any] = {
    "$schema": JSON_SCHEMA_DIALECT,
    "type": "object",
    "additionalProperties": False,
}


class GateError(RuntimeError):
    """A deterministic gate validation, durability, or execution failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target


def validate_identifier(value: object, target: str) -> str:
    """Return a safe identifier or raise :class:`GateError`."""
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise GateError(
            "invalid_identifier",
            target,
            f"{target} must contain only letters, digits, '.', '_', or '-'",
        )
    return value


def validate_option_identifier(value: object, target: str) -> str:
    """Return an identifier accepted by the option-query grammar."""
    if not isinstance(value, str) or not _OPTION_IDENTIFIER_RE.fullmatch(value):
        raise GateError(
            "invalid_identifier",
            target,
            f"{target} must match [a-z][a-z0-9_-]*",
        )
    return value


def validate_relative_path(value: object, target: str) -> str:
    """Return a normalized safe POSIX path owned by a request bundle."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise GateError("invalid_path", target, f"{target} must be a relative path")
    if "\\" in value:
        raise GateError("invalid_path", target, f"{target} must use '/' separators")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise GateError(
            "invalid_path", target, f"{target} must stay within the request bundle"
        )
    return path.as_posix()


def validate_icon(value: object, target: str) -> str | None:
    """Return one bounded display grapheme, or reject an invalid icon."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise GateError(
            "invalid_icon", target, f"{target} must be a single emoji or glyph"
        )
    if (
        len(value) > _MAX_GATE_ICON_CODEPOINTS
        or len(value.encode("utf-8")) > _MAX_GATE_ICON_BYTES
        or _grapheme_cluster_count(value) != 1
    ):
        raise GateError(
            "invalid_icon", target, f"{target} must be a single emoji or glyph"
        )
    return value


def validate_color(value: object, target: str) -> str | None:
    """Return a sender-declared ``#RRGGBB`` accent, or reject it at write time.

    Storing junk here would render as an unstyled chip long after the sender is
    gone, so a malformed color fails the write instead.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not _COLOR_RE.fullmatch(value.strip()):
        raise GateError(
            "invalid_color", target, f"{target} must be an '#RRGGBB' hex color"
        )
    return value.strip()


def _grapheme_cluster_count(value: str) -> int:
    """Count the bounded glyph forms accepted for gate icons.

    This deliberately covers combining marks, emoji modifiers, regional-indicator
    pairs, keycaps, tag sequences, and zero-width-joiner emoji without adding a
    Unicode-segmentation dependency to the gate service.
    """
    clusters = 0
    join_next = False
    regional_run = 0
    for character in value:
        codepoint = ord(character)
        if _is_disallowed_icon_control(character):
            return 2
        if clusters == 0:
            if codepoint == 0x200D or _is_grapheme_extend(character):
                return 2
            clusters = 1
            regional_run = 1 if _is_regional_indicator(codepoint) else 0
            continue
        if join_next:
            if codepoint == 0x200D:
                return 2
            join_next = False
            regional_run = 0
            continue
        if codepoint == 0x200D:
            join_next = True
            regional_run = 0
            continue
        if _is_grapheme_extend(character):
            continue
        if _is_regional_indicator(codepoint) and regional_run % 2 == 1:
            regional_run += 1
            continue
        clusters += 1
        regional_run = 1 if _is_regional_indicator(codepoint) else 0
    return clusters + int(join_next)


def _is_grapheme_extend(character: str) -> bool:
    codepoint = ord(character)
    return (
        unicodedata.combining(character) != 0
        or unicodedata.category(character) in {"Mc", "Me", "Mn"}
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0x1F3FB <= codepoint <= 0x1F3FF
        or 0xE0020 <= codepoint <= 0xE007F
    )


def _is_disallowed_icon_control(character: str) -> bool:
    codepoint = ord(character)
    return unicodedata.category(character).startswith("C") and not (
        codepoint == 0x200D or 0xE0020 <= codepoint <= 0xE007F
    )


def _is_regional_indicator(codepoint: int) -> bool:
    return 0x1F1E6 <= codepoint <= 0x1F1FF


def validate_label(value: object, target: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError("invalid_request", target, f"{target} is required")
    normalized = value.strip()
    if len(normalized) > _MAX_GATE_LABEL_LENGTH:
        raise GateError(
            "invalid_request",
            target,
            f"{target} must be at most {_MAX_GATE_LABEL_LENGTH} characters",
        )
    return normalized


def json_object(value: object, target: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GateError("invalid_request", target, f"{target} must be an object")
    return {str(key): item for key, item in value.items()}


def string_list(value: object, target: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GateError(
            "invalid_request", target, f"{target} must be an array of strings"
        )
    return tuple(value)


def check_json_schema(schema: dict[str, Any], target: str) -> None:
    """Reject a schema the gate executor could not enforce as written.

    Gates pin one dialect. The executor builds a ``Draft202012Validator`` and
    nothing reads ``$schema`` at submission time, so a schema declaring a
    different dialect would be silently enforced as Draft 2020-12 anyway --
    which is exactly the kind of quiet disagreement this contract exists to
    prevent.
    """
    declared_dialect = schema.get("$schema")
    if declared_dialect is not None and (
        not isinstance(declared_dialect, str)
        or declared_dialect not in _ACCEPTED_SCHEMA_DIALECTS
    ):
        raise GateError(
            "unsupported_schema_dialect",
            target,
            f"{target}.$schema must be {JSON_SCHEMA_DIALECT}; gates enforce "
            "JSON Schema Draft 2020-12 and nothing else",
        )
    try:
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise GateError(
            "invalid_schema", target, f"invalid JSON schema: {exc}"
        ) from exc


def first_schema_error(value: Any, schema: Mapping[str, Any]) -> Any:
    """Return the first Draft 2020-12 error for *value*, or ``None``.

    Returned as the raw ``jsonschema`` error so a caller can branch on
    ``validator``/``validator_value`` when it wants to name the offending
    property rather than echo a library message.
    """
    from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

    errors = sorted(Draft202012Validator(dict(schema)).iter_errors(value), key=str)
    return errors[0] if errors else None


def stamp_schema_dialect(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return *schema* with the pinned dialect recorded on it.

    Stamping at parse time makes the stored envelope self-describing and keeps
    the operation idempotent, so an envelope re-parsed by
    :meth:`GateOption.from_mapping` compares equal to the one that was written.
    """
    stamped = dict(schema)
    stamped["$schema"] = JSON_SCHEMA_DIALECT
    return stamped


def check_schema_bounds(schema: Mapping[str, Any], target: str) -> None:
    """Reject a schema wider or deeper than a submitted input may ever be.

    The numbers are the submission-time bounds. Enforcing them at creation
    turns "every answer fails" into one pointed creation error.
    """
    pending: list[tuple[object, int]] = [(schema, 0)]
    while pending:
        current, depth = pending.pop()
        if isinstance(current, Mapping):
            _reject_schema_depth(depth, target)
            properties = current.get("properties")
            if (
                isinstance(properties, Mapping)
                and len(properties) > MAX_OBJECT_PROPERTIES
            ):
                raise GateError(
                    "schema_too_large",
                    target,
                    f"{target} declares {len(properties)} properties in one "
                    f"object; at most {MAX_OBJECT_PROPERTIES} are allowed",
                )
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            _reject_schema_depth(depth, target)
            pending.extend((item, depth + 1) for item in current)


def _reject_schema_depth(depth: int, target: str) -> None:
    if depth >= MAX_INPUT_DEPTH:
        raise GateError(
            "schema_too_large",
            target,
            f"{target} nests deeper than {MAX_INPUT_DEPTH} levels",
        )


def reject_unknown_fields(
    data: Mapping[str, Any], allowed: set[str], target: str
) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise GateError(
            "invalid_request",
            target,
            f"unsupported field(s): {', '.join(sorted(unknown))}",
        )
