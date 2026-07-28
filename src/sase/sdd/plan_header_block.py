"""Typed adapter for the Rust-owned SDD plan-header block contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sase.core.rust import require_rust_binding

PLAN_HEADER_BLOCK_WIRE_SCHEMA_VERSION = 2
MAX_RENDERED_PLAN_HEADER_ENTRIES = 50


class PlanHeaderDisposition(StrEnum):
    """Representation recognized in one SDD Markdown document."""

    CANONICAL = "canonical"
    LEGACY = "legacy"
    MIXED = "mixed"
    MISSING = "missing"
    INVALID = "invalid"


class PlanHeaderSectionKind(StrEnum):
    """A fixed-order section in the plan-header block."""

    PLAN = "PLAN"
    PROMPT = "PROMPT"
    PARENT = "PARENT"
    BEAD = "BEAD"
    AGENTS = "AGENTS"
    COMMITS = "COMMITS"


@dataclass(frozen=True)
class PlanHeaderEntry:
    """One item in an AGENTS or COMMITS section."""

    label: str
    target: str | None = None
    trailing_text: str | None = None


@dataclass(frozen=True)
class PlanHeaderSection:
    """One link-shaped or list-shaped header section."""

    kind: PlanHeaderSectionKind
    label: str | None = None
    target: str | None = None
    entries: tuple[PlanHeaderEntry, ...] = ()
    omitted: int = 0


@dataclass(frozen=True)
class _PlanHeaderLegacyLink:
    """One historical YAML-property artifact link."""

    kind: PlanHeaderSectionKind
    format: str
    reference: str
    target: str


@dataclass(frozen=True)
class _PlanHeaderDocument:
    """Parsed header sections plus the clean user-authored body."""

    disposition: PlanHeaderDisposition
    sections: tuple[PlanHeaderSection, ...]
    body: str
    legacy: _PlanHeaderLegacyLink | None = None
    has_frontmatter: bool = False
    canonical_layout: bool = False
    reason: str | None = None


def parse_plan_header_block(document: str) -> _PlanHeaderDocument:
    """Parse a complete SDD Markdown document."""
    _require_schema_version()
    binding = require_rust_binding("sdd_plan_header_block_parse")
    payload = dict(binding(document))
    _assert_payload_schema(payload)
    legacy_payload = payload.get("legacy")
    legacy = None
    if isinstance(legacy_payload, dict):
        legacy = _PlanHeaderLegacyLink(
            kind=PlanHeaderSectionKind(str(legacy_payload["link_type"])),
            format=str(legacy_payload["format"]),
            reference=str(legacy_payload["reference"]),
            target=str(legacy_payload["target"]),
        )
    return _PlanHeaderDocument(
        disposition=PlanHeaderDisposition(str(payload["kind"])),
        sections=tuple(
            _section_from_payload(item)
            for item in payload.get("sections", ())
            if isinstance(item, dict)
        ),
        body=str(payload.get("body") or ""),
        legacy=legacy,
        has_frontmatter=bool(payload.get("has_frontmatter")),
        canonical_layout=bool(payload.get("canonical_layout")),
        reason=_optional_str(payload, "reason"),
    )


def render_plan_header_block(sections: tuple[PlanHeaderSection, ...]) -> str:
    """Render sections in the canonical fixed order."""
    _require_schema_version()
    binding = require_rust_binding("sdd_plan_header_block_render")
    return str(binding([_section_payload(section) for section in sections]))


def upsert_plan_header_section(
    document: str,
    section: PlanHeaderSection,
    *,
    remove_legacy: bool = True,
    allow_resolved_mixed: bool = False,
) -> str:
    """Install or replace one section."""
    _require_schema_version()
    binding = require_rust_binding("sdd_plan_header_block_upsert_section")
    return str(
        binding(
            document,
            _section_payload(section),
            remove_legacy,
            allow_resolved_mixed,
        )
    )


def remove_plan_header_section(
    document: str,
    kind: PlanHeaderSectionKind,
    *,
    remove_legacy: bool = True,
    allow_resolved_mixed: bool = False,
) -> str:
    """Remove one section while preserving the rest of the header block."""
    _require_schema_version()
    binding = require_rust_binding("sdd_plan_header_block_remove_section")
    return str(
        binding(
            document,
            kind.value,
            remove_legacy,
            allow_resolved_mixed,
        )
    )


def _section_from_payload(payload: dict[str, Any]) -> PlanHeaderSection:
    return PlanHeaderSection(
        kind=PlanHeaderSectionKind(str(payload["kind"])),
        label=_optional_str(payload, "label"),
        target=_optional_str(payload, "target"),
        entries=tuple(
            PlanHeaderEntry(
                label=str(entry["label"]),
                target=_optional_str(entry, "target"),
                trailing_text=_optional_str(entry, "trailing_text"),
            )
            for entry in payload.get("entries", ())
            if isinstance(entry, dict)
        ),
        omitted=int(payload.get("omitted") or 0),
    )


def _section_payload(section: PlanHeaderSection) -> dict[str, object]:
    return {
        "kind": section.kind.value,
        "label": section.label,
        "target": section.target,
        "entries": [
            {
                "label": entry.label,
                "target": entry.target,
                "trailing_text": entry.trailing_text,
            }
            for entry in section.entries
        ],
        "omitted": section.omitted,
    }


def _require_schema_version() -> None:
    binding = require_rust_binding("sdd_plan_header_block_wire_schema_version")
    binding_version = int(binding())
    if binding_version != PLAN_HEADER_BLOCK_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "plan header block wire schema version mismatch: "
            f"expected {PLAN_HEADER_BLOCK_WIRE_SCHEMA_VERSION}, "
            f"got {binding_version}"
        )


def _assert_payload_schema(payload: dict[str, Any]) -> None:
    schema_version = int(payload.get("schema_version") or 0)
    if schema_version != PLAN_HEADER_BLOCK_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "plan header block payload schema version mismatch: "
            f"expected {PLAN_HEADER_BLOCK_WIRE_SCHEMA_VERSION}, "
            f"got {schema_version}"
        )


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


__all__ = [
    "MAX_RENDERED_PLAN_HEADER_ENTRIES",
    "PLAN_HEADER_BLOCK_WIRE_SCHEMA_VERSION",
    "PlanHeaderDisposition",
    "PlanHeaderEntry",
    "PlanHeaderSection",
    "PlanHeaderSectionKind",
    "parse_plan_header_block",
    "remove_plan_header_section",
    "render_plan_header_block",
    "upsert_plan_header_section",
]
