"""Normalized surface rows for directive completion parity tests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SurfaceRow:
    label: str
    insertion: str
    documentation: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class LspSurfaceRow(SurfaceRow):
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class LspCompletionList:
    """Raw LSP completion list plus normalized surface rows."""

    is_incomplete: bool
    items: list[LspSurfaceRow]
    raw: Any = None


@dataclass(frozen=True, slots=True)
class LspSemanticToken:
    line: int
    start: int
    length: int
    token_type: str
    modifiers: frozenset[str]


def _surface_rows(rows: Iterable[SurfaceRow]) -> list[SurfaceRow]:
    return [
        SurfaceRow(
            label=row.label,
            insertion=row.insertion,
            documentation=row.documentation,
            detail=_comparison_detail(row.detail),
        )
        for row in rows
    ]


def _comparison_detail(detail: str) -> str:
    if detail in {
        "agent",
        "bead",
        "clan",
        "hood",
        "keyword",
        "model",
        "proc",
        "role",
        "session",
        "tribe",
        "value",
    }:
        return "" if detail != "keyword" else detail
    return detail


def _only_lsp(rows: list[LspSurfaceRow]) -> LspSurfaceRow:
    assert len(rows) == 1
    return rows[0]
