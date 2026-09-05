"""Typed facade for Rust prompt-archive inventory snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd.plan_header_block import (
    PlanHeaderDisposition,
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
)

PROMPT_ARCHIVE_INVENTORY_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PromptArchiveDocument:
    """One parsed prompt archive document."""

    path: Path
    relpath: str
    month: str
    name: str
    content: str
    body: str
    disposition: PlanHeaderDisposition
    sections: tuple[PlanHeaderSection, ...]
    has_frontmatter: bool
    canonical_layout: bool
    parse_error: str | None


def prompt_archive_inventory(
    repo: Path | str,
    *,
    month: str | None = None,
) -> tuple[PromptArchiveDocument, ...]:
    """Return read-only prompt archive documents without validation checks."""
    _require_schema_version()
    root = Path(repo).expanduser().resolve(strict=False)
    binding = require_rust_binding("prompt_archive_inventory")
    payload = dict(binding(str(root), {"month": month}))
    _assert_payload_schema(payload)
    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise RuntimeError("prompt archive inventory payload is missing documents")
    return tuple(
        _document_from_payload(root, item)
        for item in documents
        if isinstance(item, dict)
    )


def _document_from_payload(
    root: Path,
    payload: dict[str, Any],
) -> PromptArchiveDocument:
    relpath = _required_str(payload, "path")
    return PromptArchiveDocument(
        path=root / relpath,
        relpath=relpath,
        month=_required_str(payload, "month"),
        name=_required_str(payload, "name"),
        content=_required_str(payload, "content"),
        body=_required_str(payload, "body"),
        disposition=PlanHeaderDisposition(_required_str(payload, "kind")),
        sections=tuple(
            _section_from_payload(item)
            for item in payload.get("sections", ())
            if isinstance(item, dict)
        ),
        has_frontmatter=bool(payload.get("has_frontmatter")),
        canonical_layout=bool(payload.get("canonical_layout")),
        parse_error=_optional_str(payload, "parse_error"),
    )


def _section_from_payload(payload: dict[str, Any]) -> PlanHeaderSection:
    return PlanHeaderSection(
        kind=PlanHeaderSectionKind(_required_str(payload, "kind")),
        label=_optional_str(payload, "label"),
        target=_optional_str(payload, "target"),
        entries=tuple(
            PlanHeaderEntry(
                label=_required_str(entry, "label"),
                target=_optional_str(entry, "target"),
                trailing_text=_optional_str(entry, "trailing_text"),
            )
            for entry in payload.get("entries", ())
            if isinstance(entry, dict)
        ),
        omitted=int(payload.get("omitted") or 0),
    )


def _require_schema_version() -> None:
    binding = require_rust_binding("prompt_archive_inventory_wire_schema_version")
    binding_version = int(binding())
    if binding_version != PROMPT_ARCHIVE_INVENTORY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "prompt archive inventory wire schema version mismatch: "
            f"expected {PROMPT_ARCHIVE_INVENTORY_WIRE_SCHEMA_VERSION}, "
            f"got {binding_version}"
        )


def _assert_payload_schema(payload: dict[str, Any]) -> None:
    schema_version = int(payload.get("schema_version") or 0)
    if schema_version != PROMPT_ARCHIVE_INVENTORY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "prompt archive inventory payload schema version mismatch: "
            f"expected {PROMPT_ARCHIVE_INVENTORY_WIRE_SCHEMA_VERSION}, "
            f"got {schema_version}"
        )


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"prompt archive inventory payload missing {key!r}")
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


__all__ = [
    "PROMPT_ARCHIVE_INVENTORY_WIRE_SCHEMA_VERSION",
    "PromptArchiveDocument",
    "prompt_archive_inventory",
]
