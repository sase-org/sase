"""Typed builders for structured axe chop reports."""

from __future__ import annotations

import copy
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, Literal

Tone = Literal["neutral", "muted", "info", "ok", "warn", "error", "accent"]

_TONES: frozenset[str] = frozenset(
    {"neutral", "muted", "info", "ok", "warn", "error", "accent"}
)
_GLYPHS: frozenset[str] = frozenset(
    {"▲", "◆", "•", "·", "●", "○", "✓", "✗", "↗", "↷", "⏱", "!", "▸", "─"}
)
_MAX_BLOCKS = 48
_MAX_ENTRIES = 64
_MAX_COLUMNS = 6
_MAX_TEXT_CHARS = 512
_MAX_TITLE_CHARS = 64


def _normalize_text(value: str, *, limit: int = _MAX_TEXT_CHARS) -> str:
    """Return one bounded line with controls removed and whitespace collapsed."""

    without_controls = "".join(
        " " if unicodedata.category(character) == "Cc" else character
        for character in value
    )
    normalized = " ".join(without_controls.split())
    if len(normalized) > limit:
        return normalized[: limit - 1] + "…"
    return normalized


def _tone_value(tone: Tone | None) -> Tone | None:
    if tone is not None and tone not in _TONES:
        raise ValueError(f"unknown chop report tone: {tone!r}")
    return tone


def _glyph_value(glyph: str | None) -> str | None:
    if glyph is not None and glyph not in _GLYPHS:
        raise ValueError(f"glyph must be one allowlisted character: {glyph!r}")
    return glyph


def _with_tone(document: dict[str, Any], tone: Tone | None) -> dict[str, Any]:
    if (normalized := _tone_value(tone)) is not None:
        document["tone"] = normalized
    return document


def _with_glyph(document: dict[str, Any], glyph: str | None) -> dict[str, Any]:
    if (normalized := _glyph_value(glyph)) is not None:
        document["glyph"] = normalized
    return document


class ChopReport:
    """Mutable builder for a frontend-agnostic structured chop report."""

    def __init__(self, *, title: str | None = None) -> None:
        self.title = (
            _normalize_text(title, limit=_MAX_TITLE_CHARS)
            if title is not None
            else None
        )
        if not self.title:
            self.title = None
        self._blocks: list[dict[str, Any]] = []

    def _append(self, block: dict[str, Any]) -> None:
        if len(self._blocks) >= _MAX_BLOCKS:
            raise ValueError(f"a chop report may contain at most {_MAX_BLOCKS} blocks")
        self._blocks.append(block)

    def headline(self, text: str, *, tone: Tone | None = None) -> ChopReport:
        """Add a prominent summary line."""

        if normalized := _normalize_text(text):
            self._append(_with_tone({"kind": "headline", "text": normalized}, tone))
        return self

    def heading(self, text: str) -> ChopReport:
        """Add a section heading."""

        if normalized := _normalize_text(text):
            self._append({"kind": "heading", "text": normalized})
        return self

    def text(self, text: str, *, tone: Tone | None = None) -> ChopReport:
        """Add a literal text block."""

        if normalized := _normalize_text(text):
            self._append(_with_tone({"kind": "text", "text": normalized}, tone))
        return self

    def kv(
        self,
        items: Mapping[str, str],
        *,
        tone: Tone | None = None,
    ) -> ChopReport:
        """Add a key/value block, applying one semantic tone to every pair."""

        normalized_tone = _tone_value(tone)
        normalized_items: list[dict[str, Any]] = []
        for key, value in items.items():
            normalized_key = _normalize_text(key)
            normalized_value = _normalize_text(value)
            if not normalized_key or not normalized_value:
                continue
            item = {"key": normalized_key, "value": normalized_value}
            if normalized_tone is not None:
                item["tone"] = normalized_tone
            normalized_items.append(item)
        if len(normalized_items) > _MAX_ENTRIES:
            raise ValueError(
                f"a chop report key/value block may contain at most "
                f"{_MAX_ENTRIES} items"
            )
        if normalized_items:
            self._append({"kind": "kv", "items": normalized_items})
        return self

    def rows(
        self,
        *,
        columns: Sequence[str] | None = None,
        tone: Tone | None = None,
    ) -> _ChopReportRows:
        """Start a row block and return its chainable row collector."""

        return _ChopReportRows(self, columns=columns, tone=tone)

    def bullets(
        self,
        items: Sequence[str],
        *,
        tone: Tone | None = None,
        glyph: str | None = None,
    ) -> ChopReport:
        """Add a bullet list with shared semantic presentation."""

        normalized_tone = _tone_value(tone)
        normalized_glyph = _glyph_value(glyph)
        normalized_items: list[dict[str, Any]] = []
        for text in items:
            if not (normalized_text := _normalize_text(text)):
                continue
            item: dict[str, Any] = {"text": normalized_text}
            if normalized_tone is not None:
                item["tone"] = normalized_tone
            if normalized_glyph is not None:
                item["glyph"] = normalized_glyph
            normalized_items.append(item)
        if len(normalized_items) > _MAX_ENTRIES:
            raise ValueError(
                f"a chop report bullet block may contain at most {_MAX_ENTRIES} items"
            )
        if normalized_items:
            self._append({"kind": "bullets", "items": normalized_items})
        return self

    def gauge(
        self,
        label: str,
        value: int,
        max: int,
        *,
        tone: Tone | None = None,
    ) -> ChopReport:
        """Add a bounded gauge; values above the maximum are allowed."""

        normalized_label = _normalize_text(label)
        if not normalized_label:
            return self
        if max <= 0:
            raise ValueError("a chop report gauge maximum must be greater than zero")
        if value < 0:
            raise ValueError("a chop report gauge value must be non-negative")
        self._append(
            _with_tone(
                {
                    "kind": "gauge",
                    "label": normalized_label,
                    "value": value,
                    "max": max,
                },
                tone,
            )
        )
        return self

    def divider(self) -> ChopReport:
        """Add a visual divider."""

        self._append({"kind": "divider"})
        return self

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible report document."""

        document: dict[str, Any] = {"blocks": copy.deepcopy(self._blocks)}
        if self.title is not None:
            document["title"] = self.title
        return document

    def __bool__(self) -> bool:
        """Return whether the report contains at least one renderable block."""

        return bool(self._blocks)


class _ChopReportRows:
    """Chainable collector for one report rows block."""

    def __init__(
        self,
        report: ChopReport,
        *,
        columns: Sequence[str] | None,
        tone: Tone | None,
    ) -> None:
        self._report = report
        self._tone = _tone_value(tone)
        self._rows: list[dict[str, Any]] = []
        self._appended = False
        if columns is None:
            self._columns = None
            self._expected_cells = None
            return
        normalized_columns = tuple(_normalize_text(column) for column in columns)
        if (
            not normalized_columns
            or len(normalized_columns) > _MAX_COLUMNS
            or any(not column for column in normalized_columns)
        ):
            raise ValueError(
                f"chop report rows require 1–{_MAX_COLUMNS} non-empty columns"
            )
        self._columns = normalized_columns
        self._expected_cells = len(normalized_columns)

    def row(
        self,
        cells: Sequence[str],
        *,
        tone: Tone | None = None,
        glyph: str | None = None,
    ) -> _ChopReportRows:
        """Append one row whose cell count matches the rest of the block."""

        normalized_cells = tuple(_normalize_text(cell) for cell in cells)
        if (
            not normalized_cells
            or len(normalized_cells) > _MAX_COLUMNS
            or any(not cell for cell in normalized_cells)
        ):
            raise ValueError(
                f"chop report rows require 1–{_MAX_COLUMNS} non-empty cells"
            )
        if self._expected_cells is None:
            self._expected_cells = len(normalized_cells)
        if len(normalized_cells) != self._expected_cells:
            raise ValueError(
                f"row has {len(normalized_cells)} cells, "
                f"expected {self._expected_cells}"
            )
        if len(self._rows) >= _MAX_ENTRIES:
            raise ValueError(
                f"a chop report rows block may contain at most {_MAX_ENTRIES} rows"
            )
        row = _with_tone(
            {"cells": list(normalized_cells)},
            self._tone if tone is None else tone,
        )
        _with_glyph(row, glyph)
        self._rows.append(row)
        if not self._appended:
            block: dict[str, Any] = {"kind": "rows", "rows": self._rows}
            if self._columns is not None:
                block["columns"] = list(self._columns)
            self._report._append(block)
            self._appended = True
        return self


__all__ = ["ChopReport", "Tone"]
