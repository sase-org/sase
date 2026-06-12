"""Pure text transforms for vim-style prompt editing commands."""

from __future__ import annotations

INDENT_UNIT = "  "


def apply_case_operator(text: str, op: str) -> str:
    """Apply a vim case operator to *text*."""
    if op == "gu":
        return text.lower()
    if op == "gU":
        return text.upper()
    if op == "g~":
        return text.swapcase()
    return text


def _indent_line(line: str) -> str:
    """Indent one line by the prompt widget's fixed vim shift width."""
    return INDENT_UNIT + line


def _dedent_line(line: str) -> str:
    """Dedent one line by up to one fixed vim shift-width unit."""
    if line.startswith(INDENT_UNIT):
        return line[len(INDENT_UNIT) :]
    if line.startswith(" ") or line.startswith("\t"):
        return line[1:]
    return line


def apply_indent_operator(lines: list[str], op: str, *, units: int = 1) -> list[str]:
    """Apply a vim indent/dedent operator to *lines*."""
    units = max(1, units)
    transformed = list(lines)
    for _ in range(units):
        if op == ">":
            transformed = [_indent_line(line) for line in transformed]
        elif op == "<":
            transformed = [_dedent_line(line) for line in transformed]
    return transformed
