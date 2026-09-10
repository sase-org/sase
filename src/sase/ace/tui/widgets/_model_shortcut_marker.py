"""Marker compatibility for shared Rust model shortcut bindings."""

from __future__ import annotations

from typing import Any

from sase.core.rust import require_rust_binding

MODEL_ALIAS_SHORTCUT_MARKER = "="
MODEL_EXPLICIT_SHORTCUT_MARKER = "=="

_LEGACY_MODEL_ALIAS_SHORTCUT_MARKER = "*"
_LEGACY_MODEL_EXPLICIT_SHORTCUT_MARKER = "**"


def model_shortcut_context_payload(
    text: str,
    cursor_location: tuple[int, int],
    position: dict[str, int],
    *,
    binding_name: str,
    marker: str,
    expected_kind: str | None = None,
) -> dict[str, Any] | None:
    """Return a current-marker context from possibly legacy Rust bindings."""
    binding = require_rust_binding(binding_name)
    payload: Any = binding(text, position)
    if _valid_context_payload(payload, marker, expected_kind=expected_kind):
        return payload

    legacy_marker = _legacy_marker_for(marker)
    legacy_text = _translate_shortcut_marker(
        text,
        cursor_location,
        marker=marker,
        replacement_marker=legacy_marker,
    )
    if legacy_text is None:
        return None
    payload = binding(legacy_text, position)
    if not _valid_context_payload(
        payload,
        legacy_marker,
        expected_kind=expected_kind,
    ):
        return None
    return _retokenize_payload(payload, marker)


def model_shortcut_edit_payload(
    text: str,
    cursor_location: tuple[int, int],
    position: dict[str, int],
    entries: list[dict[str, object]],
    selected_value: str,
    *,
    binding_name: str,
    marker: str,
    expected_kind: str | None = None,
) -> dict[str, Any] | None:
    """Return a current-marker edit from possibly legacy Rust bindings."""
    if not _token_at_cursor_uses_marker(text, cursor_location, marker=marker):
        return None

    binding = require_rust_binding(binding_name)
    payload: Any = binding(text, position, entries, selected_value)
    if _valid_edit_payload(payload, expected_kind=expected_kind):
        return payload

    legacy_text = _translate_shortcut_marker(
        text,
        cursor_location,
        marker=marker,
        replacement_marker=_legacy_marker_for(marker),
    )
    if legacy_text is None:
        return None
    payload = binding(legacy_text, position, entries, selected_value)
    if _valid_edit_payload(payload, expected_kind=expected_kind):
        return payload
    return None


def _legacy_marker_for(marker: str) -> str:
    if marker == MODEL_ALIAS_SHORTCUT_MARKER:
        return _LEGACY_MODEL_ALIAS_SHORTCUT_MARKER
    if marker == MODEL_EXPLICIT_SHORTCUT_MARKER:
        return _LEGACY_MODEL_EXPLICIT_SHORTCUT_MARKER
    raise ValueError(f"unsupported model shortcut marker: {marker!r}")


def _valid_context_payload(
    payload: Any,
    marker: str,
    *,
    expected_kind: str | None,
) -> bool:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return False
    if expected_kind is not None and payload.get("kind") != expected_kind:
        return False
    token = payload.get("token")
    return isinstance(token, str) and _token_uses_exact_marker(token, marker)


def _valid_edit_payload(
    payload: Any,
    *,
    expected_kind: str | None,
) -> bool:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return False
    return expected_kind is None or payload.get("kind") == expected_kind


def _token_at_cursor_uses_marker(
    text: str,
    cursor_location: tuple[int, int],
    *,
    marker: str,
) -> bool:
    bounds = _token_bounds_at_cursor(text, cursor_location)
    if bounds is None:
        return False
    start, end = bounds
    token = text[start:end]
    return _token_uses_exact_marker(token, marker)


def _translate_shortcut_marker(
    text: str,
    cursor_location: tuple[int, int],
    *,
    marker: str,
    replacement_marker: str,
) -> str | None:
    bounds = _token_bounds_at_cursor(text, cursor_location)
    if bounds is None:
        return None
    start, end = bounds
    token = text[start:end]
    if not _token_uses_exact_marker(token, marker):
        return None
    marker_end = start + len(marker)
    return f"{text[:start]}{replacement_marker}{text[marker_end:]}"


def _token_uses_exact_marker(token: str, marker: str) -> bool:
    marker_char = marker[0]
    suffix = token[len(marker) :]
    return (
        token.startswith(marker)
        and not suffix.startswith(marker_char)
        and marker_char not in suffix
    )


def _retokenize_payload(payload: Any, marker: str) -> dict[str, Any]:
    retokenized = dict(payload)
    token = retokenized.get("token")
    if isinstance(token, str):
        retokenized["token"] = f"{marker}{token[len(marker) :]}"
    return retokenized


def _token_bounds_at_cursor(
    text: str,
    cursor_location: tuple[int, int],
) -> tuple[int, int] | None:
    cursor = _cursor_offset(text, cursor_location)
    if cursor is None:
        return None
    start = cursor
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    end = cursor
    while end < len(text) and not text[end].isspace():
        end += 1
    return start, end


def _cursor_offset(text: str, location: tuple[int, int]) -> int | None:
    row, col = location
    if row < 0 or col < 0:
        return None
    lines = text.split("\n")
    if row >= len(lines):
        return None
    offset = 0
    for line in lines[:row]:
        offset += len(line) + 1
    return offset + min(col, len(lines[row]))
