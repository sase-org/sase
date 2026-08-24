"""Rust-backed glossary catalog facade.

The Rust core owns glossary validation, effective aliases, and phrase
matching. Python callers own config and strand file discovery,
source-preserving YAML parsing, and editor presentation; this module only
converts small Python records to and from the ``sase_core_rs`` wire
dictionaries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class GlossarySource:
    """Optional source metadata attached to one glossary entry."""

    source_path: str | None = None
    key_path: tuple[str, ...] = ()
    keyword_range: dict[str, Any] | None = None
    body_range: dict[str, Any] | None = None
    aliases_range: dict[str, Any] | None = None

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "key_path": list(self.key_path),
        }
        if self.source_path is not None:
            wire["source_path"] = self.source_path
        if self.keyword_range is not None:
            wire["keyword_range"] = self.keyword_range
        if self.body_range is not None:
            wire["body_range"] = self.body_range
        if self.aliases_range is not None:
            wire["aliases_range"] = self.aliases_range
        return wire


@dataclass(frozen=True)
class GlossaryInputEntry:
    """Authored glossary entry handed to Rust for validation/compilation."""

    term: str
    definition: str
    aliases: tuple[str, ...] = ()
    source: GlossarySource | Mapping[str, Any] | None = None

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "term": self.term,
            "definition": self.definition,
            "aliases": list(self.aliases),
        }
        if self.source is not None:
            wire["source"] = (
                self.source.to_wire()
                if isinstance(self.source, GlossarySource)
                else dict(self.source)
            )
        return wire


@dataclass(frozen=True)
class GlossaryDiagnostic:
    severity: str
    code: str
    message: str
    path: str | None

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> GlossaryDiagnostic:
        return cls(
            severity=str(payload["severity"]),
            code=str(payload["code"]),
            message=str(payload["message"]),
            path=payload.get("path"),
        )


@dataclass(frozen=True)
class GlossaryEntry:
    index: int
    term: str
    normalized_term: str
    definition: str
    configured_aliases: tuple[str, ...]
    display_aliases: tuple[str, ...]
    effective_aliases: tuple[str, ...]
    source: Mapping[str, Any] | None

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> GlossaryEntry:
        return cls(
            index=int(payload["index"]),
            term=str(payload["term"]),
            normalized_term=str(payload["normalized_term"]),
            definition=str(payload["definition"]),
            configured_aliases=tuple(payload["configured_aliases"]),
            display_aliases=tuple(payload["display_aliases"]),
            effective_aliases=tuple(payload["effective_aliases"]),
            source=payload.get("source"),
        )


@dataclass(frozen=True)
class GlossaryCatalog:
    schema_version: int
    entries: tuple[GlossaryEntry, ...]

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> GlossaryCatalog:
        return cls(
            schema_version=int(payload["schema_version"]),
            entries=tuple(
                GlossaryEntry.from_wire(entry) for entry in payload["entries"]
            ),
        )


@dataclass(frozen=True)
class GlossarySpan:
    term: str
    entry_index: int
    alias_index: int
    alias: str
    matched_text: str
    byte_start: int
    byte_end: int
    range: Mapping[str, Any]
    segments: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> GlossarySpan:
        return cls(
            term=str(payload["term"]),
            entry_index=int(payload["entry_index"]),
            alias_index=int(payload["alias_index"]),
            alias=str(payload["alias"]),
            matched_text=str(payload["matched_text"]),
            byte_start=int(payload["byte_start"]),
            byte_end=int(payload["byte_end"]),
            range=payload["range"],
            segments=tuple(payload["segments"]),
        )


EntryLike = GlossaryInputEntry | Mapping[str, Any]
CompiledGlossaryCatalog = Any


def _entries_to_wire(entries: Sequence[EntryLike]) -> list[dict[str, Any]]:
    return [
        entry.to_wire() if isinstance(entry, GlossaryInputEntry) else dict(entry)
        for entry in entries
    ]


def validate_glossary_entries(
    entries: Sequence[EntryLike],
) -> tuple[GlossaryDiagnostic, ...]:
    """Return glossary validation diagnostics without compiling a matcher."""
    binding = require_rust_binding("glossary_validate")
    return tuple(
        GlossaryDiagnostic.from_wire(item)
        for item in binding(_entries_to_wire(entries))
    )


def build_glossary_catalog(entries: Sequence[EntryLike]) -> GlossaryCatalog:
    """Return normalized, Markdown-ready glossary catalog data."""
    binding = require_rust_binding("glossary_catalog")
    return GlossaryCatalog.from_wire(binding(_entries_to_wire(entries)))


def compile_glossary_catalog(
    entries: Sequence[EntryLike],
) -> CompiledGlossaryCatalog:
    """Compile entries into an immutable native matcher handle."""
    binding = require_rust_binding("compile_glossary_catalog")
    return binding(_entries_to_wire(entries))


def scan_glossary_spans(
    catalog: CompiledGlossaryCatalog, text: str
) -> tuple[GlossarySpan, ...]:
    """Scan *text* with a compiled native glossary catalog."""
    return tuple(GlossarySpan.from_wire(item) for item in catalog.scan(text))


def lookup_glossary_span(
    catalog: CompiledGlossaryCatalog, text: str, *, line: int, character: int
) -> GlossarySpan | None:
    """Return the glossary span under a UTF-16 editor position, if any."""
    payload = catalog.lookup(text, line, character)
    return None if payload is None else GlossarySpan.from_wire(payload)
