"""Typed facade for bounded named lookups in the dismissed-bundle archive."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.core.rust import require_rust_binding

NamedDismissedBundleAvailability = Literal[
    "ready", "missing", "stale_schema", "newer_schema", "corrupt", "busy"
]


@dataclass(frozen=True)
class _NamedDismissedBundleHitWire:
    """Validated indexed or recovered bundle identity."""

    bundle_path: str
    artifacts_dir: str
    raw_suffix: str
    filename: str


@dataclass(frozen=True)
class _NamedDismissedBundleLookupWire:
    """Bundle lookup result with explicit availability and completeness."""

    availability: NamedDismissedBundleAvailability
    complete: bool
    source: str
    winner: _NamedDismissedBundleHitWire | None = None
    diagnostic: str | None = None
    truncated: bool = False
    directories_visited: int = 0
    entries_visited: int = 0
    file_probes: int = 0
    payloads_decoded: int = 0


def lookup_named_dismissed_bundle(
    root: Path | str, name: str
) -> _NamedDismissedBundleLookupWire:
    """Resolve a bundle name without migrating or rebuilding the archive index."""
    raw = require_rust_binding("lookup_named_dismissed_bundle")(str(root), name)
    if not isinstance(raw, dict):
        raise RuntimeError("lookup_named_dismissed_bundle returned a non-object result")
    availability = str(raw.get("availability") or "corrupt")
    if availability not in {
        "ready",
        "missing",
        "stale_schema",
        "newer_schema",
        "corrupt",
        "busy",
    }:
        availability = "corrupt"
    winner_value = raw.get("winner")
    winner = (
        _NamedDismissedBundleHitWire(
            bundle_path=str(winner_value.get("bundle_path") or ""),
            artifacts_dir=str(winner_value.get("artifacts_dir") or ""),
            raw_suffix=str(winner_value.get("raw_suffix") or ""),
            filename=str(winner_value.get("filename") or ""),
        )
        if isinstance(winner_value, dict)
        else None
    )
    return _NamedDismissedBundleLookupWire(
        availability=availability,  # type: ignore[arg-type]
        complete=bool(raw.get("complete")),
        source=str(raw.get("source") or "none"),
        winner=winner,
        diagnostic=(
            str(raw["diagnostic"]) if raw.get("diagnostic") is not None else None
        ),
        truncated=bool(raw.get("truncated")),
        directories_visited=_int(raw.get("directories_visited")),
        entries_visited=_int(raw.get("entries_visited")),
        file_probes=_int(raw.get("file_probes")),
        payloads_decoded=_int(raw.get("payloads_decoded")),
    )


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


__all__ = [
    "lookup_named_dismissed_bundle",
]
