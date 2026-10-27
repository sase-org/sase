"""Light loader for the generated catalog and the curated overlay.

Hot paths never import this module; the fold driver, the report commands,
and the TUI view use it off the hot path.
"""

from __future__ import annotations

import importlib.resources
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.footprint.ids import CATALOG_SCHEMA, OVERLAY_SCHEMA


@dataclass(frozen=True)
class _CatalogHeader:
    """The first line of ``catalog.jsonl``."""

    schema: str
    rev: str
    count: int


@dataclass(frozen=True)
class CatalogEntry:
    """One catalogued feature."""

    id: str
    ns: str
    area: str
    kind: str
    label: str
    parent: str | None = None
    src: str | None = None


@dataclass(frozen=True)
class Overlay:
    """Curated human knowledge from ``overlay.yml``."""

    schema: str
    features: dict[str, dict[str, str]] = field(default_factory=dict)
    retire_with: tuple[tuple[str, ...], ...] = ()


def _catalog_path() -> Path:
    """Return the checked-in generated catalog path."""
    return Path(str(importlib.resources.files("sase.footprint") / "catalog.jsonl"))


def _overlay_path() -> Path:
    """Return the curated overlay path."""
    return Path(str(importlib.resources.files("sase.footprint") / "overlay.yml"))


def _parse_entry(raw: dict[str, Any]) -> CatalogEntry:
    return CatalogEntry(
        id=str(raw["id"]),
        ns=str(raw["ns"]),
        area=str(raw["area"]),
        kind=str(raw["kind"]),
        label=str(raw.get("label", "")),
        parent=raw.get("parent"),
        src=raw.get("src"),
    )


def load_catalog(path: Path | None = None) -> tuple[_CatalogHeader, list[CatalogEntry]]:
    """Load the catalog header and entries sorted by ID."""
    target = path if path is not None else _catalog_path()
    lines = target.read_text(encoding="utf-8").splitlines()
    header_raw = json.loads(lines[0])
    header = _CatalogHeader(
        schema=str(header_raw["schema"]),
        rev=str(header_raw["rev"]),
        count=int(header_raw["count"]),
    )
    if header.schema != CATALOG_SCHEMA:
        raise ValueError(f"unexpected catalog schema {header.schema!r}")
    entries = [_parse_entry(json.loads(line)) for line in lines[1:] if line.strip()]
    return header, entries


def load_overlay(path: Path | None = None) -> Overlay:
    """Load the curated overlay."""
    target = path if path is not None else _overlay_path()
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    schema = str(raw.get("schema", ""))
    if schema != OVERLAY_SCHEMA:
        raise ValueError(f"unexpected overlay schema {schema!r}")
    features = {str(k): dict(v) for k, v in (raw.get("features") or {}).items()}
    retire_with = tuple(
        tuple(str(item) for item in group) for group in (raw.get("retire_with") or [])
    )
    return Overlay(schema=schema, features=features, retire_with=retire_with)


__all__ = [
    "CatalogEntry",
    "Overlay",
    "load_catalog",
    "load_overlay",
]
