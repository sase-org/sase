"""Shared Markdown table primitives for the Projects Markdown report."""

from __future__ import annotations

from collections.abc import Sequence


def md_cell(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def md_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    escaped_headers = [md_cell(header) for header in headers]
    align = ["---" if index == 0 else "---:" for index in range(len(headers))]
    lines = [
        "| " + " | ".join(escaped_headers) + " |",
        "| " + " | ".join(align) + " |",
    ]
    for row in rows:
        cells = [md_cell(cell) for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


__all__ = [
    "md_cell",
    "md_table",
]
