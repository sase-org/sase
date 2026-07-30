"""Rich rendering helpers for canonical output-variable lines."""

from __future__ import annotations

from rich.text import Text

from sase.core.output_variable_display import VarLine, format_var_value_lines
from sase.core.output_variable_values import VarValue

_KEY_STYLE = "bold #87D7FF"
_VALUE_STYLES = {
    "string": "#5FD75F",
    "number": "#FFAF5F",
    "boolean": "italic #AFAFAF",
    "null": "italic #AFAFAF",
    "list": "dim",
    "map": "dim",
    "block": "dim",
}


def append_var_value_lines(
    text: Text,
    value: VarValue,
    *,
    key: str | None = None,
    first_prefix: Text | None = None,
    continuation_prefix: str = "",
) -> None:
    """Append a canonical block value with Rich styles for each value kind."""
    rendered_value: VarValue = {key: value} if key is not None else value
    lines, _ = format_var_value_lines(rendered_value)
    for index, line in enumerate(lines):
        if index == 0 and first_prefix is not None:
            text.append_text(first_prefix)
        elif index > 0 and continuation_prefix:
            text.append(continuation_prefix, style="dim")
        _append_var_line(text, line)
        text.append("\n")


def var_value_style(value: VarValue) -> str:
    """Return the Rich style for an inline preview of *value*."""
    if value is None:
        return _VALUE_STYLES["null"]
    if isinstance(value, bool):
        return _VALUE_STYLES["boolean"]
    if isinstance(value, (int, float)):
        return _VALUE_STYLES["number"]
    if isinstance(value, str):
        return _VALUE_STYLES["string"]
    if isinstance(value, list):
        return _VALUE_STYLES["list"]
    return _VALUE_STYLES["map"]


def _append_var_line(text: Text, line: VarLine) -> None:
    text.append("  " * line.indent, style="dim")
    if line.bullet:
        text.append("-", style="dim")
    if line.key is not None:
        if line.bullet:
            text.append(" ")
        text.append(f"{line.key}:", style=_KEY_STYLE)
        if line.text is not None:
            text.append(" ")
    elif line.bullet and line.text is not None:
        text.append(" ")
    if line.text is not None:
        text.append(line.text, style=_VALUE_STYLES[line.kind])


__all__ = ["append_var_value_lines", "var_value_style"]
