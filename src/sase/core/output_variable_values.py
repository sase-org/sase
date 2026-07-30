"""Canonical JSON value model for SASE agent output variables."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

MAX_OUTPUT_VARIABLES = 256
MAX_OUTPUT_VARIABLE_VALUE_BYTES = 8_192
MAX_OUTPUT_VARIABLE_DEPTH = 8
MAX_OUTPUT_VARIABLE_NODES = 1_024
MAX_OUTPUT_VARIABLE_ENCODED_BYTES = 65_536

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_ATTRIBUTE_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

type VarValue = str | int | float | bool | None | list[VarValue] | dict[str, VarValue]


@dataclass
class _NormalizationState:
    nodes: int = 0


def normalize_var_value(key: str, value: object) -> VarValue:
    """Validate and normalize one output-variable value.

    Error messages include the JSON-shaped path to the invalid value. Strings
    use LF line endings, map keys are sorted, and list order is preserved.
    """
    state = _NormalizationState()
    normalized = _normalize_value(value, path=key, depth=0, state=state)
    encoded_size = len(_encode_normalized_value(normalized).encode("utf-8"))
    if encoded_size > MAX_OUTPUT_VARIABLE_ENCODED_BYTES:
        raise ValueError(
            f"output variable value for {key} is {encoded_size} encoded UTF-8 "
            f"bytes; limit is {MAX_OUTPUT_VARIABLE_ENCODED_BYTES}"
        )
    return normalized


def coerce_var_value(value: object) -> VarValue | None:
    """Return a supported value from persisted data, or ``None`` if invalid.

    JSON ``null`` is itself represented by ``None``. Callers that need to
    distinguish valid null from invalid data should use :func:`coerce_var_map`,
    which performs coercion without relying on that sentinel.
    """
    try:
        return normalize_var_value("value", value)
    except (TypeError, ValueError):
        return None


def coerce_var_map(raw: object) -> dict[str, VarValue]:
    """Tolerantly coerce a persisted output-variable mapping.

    Unsupported entries are dropped independently so one malformed value does
    not hide the rest of an agent's output variables.
    """
    if not isinstance(raw, dict):
        return {}

    result: dict[str, VarValue] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            result[key] = normalize_var_value(key, value)
        except (TypeError, ValueError):
            continue
    return {key: result[key] for key in sorted(result)}


def encode_var_value(value: VarValue) -> str:
    """Return the compact, sorted-key canonical JSON encoding of *value*."""
    return _encode_normalized_value(normalize_var_value("value", value))


def decode_var_value(text: str) -> VarValue:
    """Decode and validate a canonical output-variable JSON value."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid output variable JSON: {exc.msg}") from exc
    return normalize_var_value("value", value)


def _normalize_value(
    value: object,
    *,
    path: str,
    depth: int,
    state: _NormalizationState,
) -> VarValue:
    if depth > MAX_OUTPUT_VARIABLE_DEPTH:
        raise ValueError(
            f"output variable value at {path} exceeds maximum depth "
            f"{MAX_OUTPUT_VARIABLE_DEPTH}"
        )
    state.nodes += 1
    if state.nodes > MAX_OUTPUT_VARIABLE_NODES:
        raise ValueError(
            f"output variable value at {path} exceeds the "
            f"{MAX_OUTPUT_VARIABLE_NODES}-node limit"
        )

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value < _INT64_MIN or value > _INT64_MAX:
            raise ValueError(
                f"output variable integer at {path} must be within signed 64-bit range"
            )
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"output variable number at {path} must be finite "
                "(NaN and Infinity are not supported)"
            )
        return value
    if isinstance(value, str):
        return _normalize_string(value, path=path, label="value")
    if isinstance(value, list):
        return [
            _normalize_value(
                item,
                path=f"{path}[{index}]",
                depth=depth + 1,
                state=state,
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        normalized_items: dict[str, VarValue] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ValueError(f"output variable map key at {path} must be a string")
            if not raw_key:
                raise ValueError(f"output variable map key at {path} must not be empty")
            normalized_key = _normalize_string(
                raw_key,
                path=path,
                label="map key",
            )
            if not normalized_key:
                raise ValueError(f"output variable map key at {path} must not be empty")
            if normalized_key in normalized_items:
                raise ValueError(
                    f"output variable map at {path} contains duplicate key "
                    f"after line-ending normalization: {normalized_key!r}"
                )
            child_path = _child_path(path, normalized_key)
            normalized_items[normalized_key] = _normalize_value(
                item,
                path=child_path,
                depth=depth + 1,
                state=state,
            )
        return {
            item_key: normalized_items[item_key]
            for item_key in sorted(normalized_items)
        }
    raise ValueError(
        f"output variable value at {path} must be a JSON value, "
        f"not {type(value).__name__}"
    )


def _normalize_string(value: str, *, path: str, label: str) -> str:
    if "\x00" in value:
        raise ValueError(
            f"output variable {label} at {path} must not contain NUL bytes"
        )
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    try:
        size = len(normalized.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(
            f"output variable {label} at {path} is not valid UTF-8"
        ) from exc
    if size > MAX_OUTPUT_VARIABLE_VALUE_BYTES:
        raise ValueError(
            f"output variable {label} at {path} is {size} UTF-8 bytes; "
            f"limit is {MAX_OUTPUT_VARIABLE_VALUE_BYTES}"
        )
    return normalized


def _child_path(path: str, key: str) -> str:
    if _ATTRIBUTE_KEY_RE.fullmatch(key):
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, ensure_ascii=False)}]"


def _encode_normalized_value(value: VarValue) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = [
    "MAX_OUTPUT_VARIABLE_DEPTH",
    "MAX_OUTPUT_VARIABLE_ENCODED_BYTES",
    "MAX_OUTPUT_VARIABLE_NODES",
    "MAX_OUTPUT_VARIABLES",
    "MAX_OUTPUT_VARIABLE_VALUE_BYTES",
    "VarValue",
    "coerce_var_map",
    "coerce_var_value",
    "decode_var_value",
    "encode_var_value",
    "normalize_var_value",
]
