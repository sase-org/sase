"""Canonical renderers for structured SASE output-variable values."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from sase.core.output_variable_values import VarValue

_VarValueKind = Literal[
    "string",
    "number",
    "boolean",
    "null",
    "list",
    "map",
    "block",
]

_YAML_INDICATORS = frozenset("-?:,[]{}#&*!|>'\"%@`")
_AMBIGUOUS_WORD_RE = re.compile(r"(?:true|false|null)", re.IGNORECASE)
_AMBIGUOUS_NUMBER_RE = re.compile(
    r"[+-]?(?:(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|"
    r"\.[0-9]+)"
)


@dataclass(frozen=True, slots=True)
class VarLine:
    """One styleable line in the canonical block rendering."""

    indent: int
    bullet: bool
    key: str | None
    text: str | None
    kind: _VarValueKind


def format_var_value_lines(
    value: VarValue,
    *,
    max_lines: int | None = None,
) -> tuple[list[VarLine], bool]:
    """Render *value* into styleable YAML-shaped lines."""
    lines: list[VarLine] = []
    _append_value_lines(lines, value, indent=0, bullet=False, key=None)
    if max_lines is None or max_lines >= len(lines):
        return lines, False
    limit = max(0, max_lines)
    return lines[:limit], True


def format_var_value_block(
    value: VarValue,
    *,
    indent: str = "  ",
    max_lines: int | None = None,
) -> tuple[str, bool]:
    """Return the plain-text block rendering of *value*."""
    lines, truncated = format_var_value_lines(value, max_lines=max_lines)
    return "\n".join(_render_line(line, indent=indent) for line in lines), truncated


def format_var_value_inline(value: VarValue, *, max_chars: int) -> str:
    """Return a bounded single-line preview of *value*."""
    rendered = _format_inline_unbounded(value)
    return _truncate(rendered, max_chars=max_chars)


def var_value_is_container(value: VarValue) -> bool:
    """Return whether *value* is a list or map."""
    return isinstance(value, (list, dict))


def var_value_preview(value: VarValue, *, max_chars: int) -> str:
    """Return a bounded triage preview for a scalar or container."""
    if var_value_is_container(value):
        return format_var_value_inline(value, max_chars=max_chars)
    if isinstance(value, str):
        for raw_line in value.splitlines():
            line = " ".join(raw_line.split())
            if line:
                return _truncate(_format_string(line), max_chars=max_chars)
        return _truncate('""', max_chars=max_chars)
    return format_var_value_inline(value, max_chars=max_chars)


def _append_value_lines(
    lines: list[VarLine],
    value: VarValue,
    *,
    indent: int,
    bullet: bool,
    key: str | None,
) -> None:
    display_key = _format_key(key) if key is not None else None
    if isinstance(value, str):
        if "\n" in value:
            lines.append(
                VarLine(
                    indent=indent,
                    bullet=bullet,
                    key=display_key,
                    text="|",
                    kind="block",
                )
            )
            for content_line in value.split("\n"):
                content_indent = indent + (2 if bullet and key is not None else 1)
                lines.append(
                    VarLine(
                        indent=content_indent,
                        bullet=False,
                        key=None,
                        text=content_line,
                        kind="string",
                    )
                )
            return
        lines.append(
            VarLine(
                indent=indent,
                bullet=bullet,
                key=display_key,
                text=_format_string(value),
                kind="string",
            )
        )
        return
    if value is None:
        lines.append(VarLine(indent, bullet, display_key, "null", "null"))
        return
    if isinstance(value, bool):
        lines.append(
            VarLine(
                indent, bullet, display_key, "true" if value else "false", "boolean"
            )
        )
        return
    if isinstance(value, (int, float)):
        lines.append(
            VarLine(indent, bullet, display_key, _format_number(value), "number")
        )
        return
    if isinstance(value, list):
        _append_list_lines(
            lines,
            value,
            indent=indent,
            bullet=bullet,
            key=display_key,
        )
        return
    _append_map_lines(
        lines,
        value,
        indent=indent,
        bullet=bullet,
        key=display_key,
    )


def _append_list_lines(
    lines: list[VarLine],
    value: list[VarValue],
    *,
    indent: int,
    bullet: bool,
    key: str | None,
) -> None:
    if not value:
        lines.append(VarLine(indent, bullet, key, "[]", "list"))
        return
    child_indent = indent
    if key is not None or bullet:
        lines.append(VarLine(indent, bullet, key, None, "list"))
        child_indent += 2 if bullet and key is not None else 1
    for item in value:
        _append_value_lines(
            lines,
            item,
            indent=child_indent,
            bullet=True,
            key=None,
        )


def _append_map_lines(
    lines: list[VarLine],
    value: dict[str, VarValue],
    *,
    indent: int,
    bullet: bool,
    key: str | None,
) -> None:
    if not value:
        lines.append(VarLine(indent, bullet, key, "{}", "map"))
        return
    items = [(item_key, value[item_key]) for item_key in sorted(value)]
    if bullet and key is None:
        first_key, first_value = items[0]
        _append_value_lines(
            lines,
            first_value,
            indent=indent,
            bullet=True,
            key=first_key,
        )
        for item_key, item_value in items[1:]:
            _append_value_lines(
                lines,
                item_value,
                indent=indent + 1,
                bullet=False,
                key=item_key,
            )
        return

    child_indent = indent
    if key is not None or bullet:
        lines.append(VarLine(indent, bullet, key, None, "map"))
        child_indent += 2 if bullet and key is not None else 1
    for item_key, item_value in items:
        _append_value_lines(
            lines,
            item_value,
            indent=child_indent,
            bullet=False,
            key=item_key,
        )


def _render_line(line: VarLine, *, indent: str) -> str:
    prefix = indent * line.indent
    if line.bullet:
        prefix += "-"
    if line.key is not None:
        if line.bullet:
            prefix += f" {line.key}:"
        else:
            prefix += f"{line.key}:"
        if line.text is not None:
            prefix += f" {line.text}"
        return prefix
    if line.text is not None:
        if line.bullet:
            return f"{prefix} {line.text}"
        return f"{prefix}{line.text}"
    return prefix


def _format_inline_unbounded(value: VarValue) -> str:
    if isinstance(value, str):
        if "\n" in value:
            return json.dumps(value, ensure_ascii=False)
        return _format_string(value)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _format_number(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_inline_unbounded(item) for item in value) + "]"
    return (
        "{"
        + ", ".join(
            f"{_format_key(key)}: {_format_inline_unbounded(value[key])}"
            for key in sorted(value)
        )
        + "}"
    )


def _format_string(value: str) -> str:
    if _string_needs_quotes(value):
        return json.dumps(value, ensure_ascii=False)
    return value


def _format_key(value: str) -> str:
    if "\n" in value or ": " in value or " #" in value or _string_needs_quotes(value):
        return json.dumps(value, ensure_ascii=False)
    return value


def _string_needs_quotes(value: str) -> bool:
    return (
        not value
        or value != value.strip()
        or value[0] in _YAML_INDICATORS
        or _AMBIGUOUS_WORD_RE.fullmatch(value) is not None
        or _AMBIGUOUS_NUMBER_RE.fullmatch(value) is not None
    )


def _format_number(value: int | float) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


def _truncate(value: str, *, max_chars: int) -> str:
    if max_chars < 1:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars == 1:
        return "…"
    return value[: max_chars - 1].rstrip() + "…"


__all__ = [
    "VarLine",
    "format_var_value_block",
    "format_var_value_inline",
    "format_var_value_lines",
    "var_value_is_container",
    "var_value_preview",
]
