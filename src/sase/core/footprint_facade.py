"""Thin Footprint ledger adapter over ``sase_core_rs``.

Rust owns spool validation, catalog ingest, the SQLite ledger, fold,
derived upserts, prune, clear, report and card queries, and local review
decisions. This module is a wire-only facade: it resolves paths, releases
the GIL inside the bindings, and never opens the store through stdlib
``sqlite3``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding

FOOTPRINT_WIRE_SCHEMA_VERSION = 1
_STORE_FILENAME = "footprint.sqlite"


def footprint_dir(sase_home: Path) -> Path:
    """Return ``<sase_home>/footprint``."""

    return Path(sase_home) / "footprint"


def footprint_ledger_path(sase_home: Path) -> Path:
    """Return the SQLite path Rust receives for the Footprint ledger."""

    return footprint_dir(sase_home) / _STORE_FILENAME


def footprint_spool_dir(sase_home: Path) -> Path:
    """Return ``<sase_home>/footprint/spool``."""

    return footprint_dir(sase_home) / "spool"


def _path_str(path: Path | str) -> str:
    return str(Path(path))


def _require_wire_schema() -> None:
    binding = require_rust_binding("footprint_wire_schema_version")
    version = int(binding())
    if version != FOOTPRINT_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs footprint wire is stale: expected "
            f"{FOOTPRINT_WIRE_SCHEMA_VERSION}, got {version}"
        )


def footprint_wire_schema_version() -> int:
    """Return the Footprint wire schema version from the Rust binding."""

    return int(require_rust_binding("footprint_wire_schema_version")())


def footprint_catalog_status(
    store_path: Path | str,
    catalog_path: Path | str,
    *,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Return whether ``catalog_path``'s revision is already ingested."""

    _require_wire_schema()
    payload = require_rust_binding("footprint_catalog_status")(
        _path_str(store_path),
        _path_str(catalog_path),
        busy_timeout_ms,
    )
    return dict(payload)


def footprint_ingest_catalog(
    store_path: Path | str,
    catalog_path: Path | str,
    enrichment: Mapping[str, int],
    today: str,
    *,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Upsert catalog features and record the revision."""

    _require_wire_schema()
    payload = require_rust_binding("footprint_ingest_catalog")(
        _path_str(store_path),
        _path_str(catalog_path),
        {str(key): int(value) for key, value in enrichment.items()},
        str(today),
        busy_timeout_ms,
    )
    return dict(payload)


def footprint_fold(
    store_path: Path | str,
    spool_dir: Path | str,
    today: str,
    spool_keep_days: int,
    spool_max_age_days: int,
    *,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Fold spool JSONL files into the daily ledger."""

    _require_wire_schema()
    payload = require_rust_binding("footprint_fold")(
        _path_str(store_path),
        _path_str(spool_dir),
        str(today),
        int(spool_keep_days),
        int(spool_max_age_days),
        busy_timeout_ms,
    )
    return dict(payload)


def footprint_upsert_derived(
    store_path: Path | str,
    origin: str,
    days: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    coverage: Sequence[Mapping[str, Any]],
    *,
    busy_timeout_ms: int = 250,
) -> None:
    """Replace exactly ``origin``'s rows for ``days``."""

    _require_wire_schema()
    require_rust_binding("footprint_upsert_derived")(
        _path_str(store_path),
        str(origin),
        [str(day) for day in days],
        [dict(row) for row in rows],
        [dict(row) for row in coverage],
        busy_timeout_ms,
    )


def footprint_status(
    store_path: Path | str,
    spool_dir: Path | str,
    today: str,
    *,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Return schema, generation, spool backlog, catalog, and coverage."""

    _require_wire_schema()
    payload = require_rust_binding("footprint_status")(
        _path_str(store_path),
        _path_str(spool_dir),
        str(today),
        busy_timeout_ms,
    )
    return dict(payload)


def footprint_prune(
    store_path: Path | str,
    today: str,
    retention_days: int,
    *,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Delete daily and coverage rows older than ``retention_days``."""

    _require_wire_schema()
    payload = require_rust_binding("footprint_prune")(
        _path_str(store_path),
        str(today),
        int(retention_days),
        busy_timeout_ms,
    )
    return dict(payload)


def footprint_clear(
    store_path: Path | str,
    spool_dir: Path | str,
    *,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Delete data rows and spool files and bump ``meta.generation``."""

    _require_wire_schema()
    payload = require_rust_binding("footprint_clear")(
        _path_str(store_path),
        _path_str(spool_dir),
        busy_timeout_ms,
    )
    return dict(payload)


def footprint_validate_overlay(overlay: Mapping[str, Any]) -> None:
    """Validate overlay JSON produced from YAML by Python."""

    _require_wire_schema()
    require_rust_binding("footprint_validate_overlay")(dict(overlay))


def _query_request(request: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(request)
    store_path = payload.get("store_path")
    if store_path is not None:
        payload["store_path"] = _path_str(store_path)
    overlay = payload.get("overlay")
    if isinstance(overlay, Mapping):
        payload["overlay"] = dict(overlay)
    return payload


def footprint_report(
    request: Mapping[str, Any],
    *,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Return a lens report (header, tiles, areas, rows, coverage)."""

    _require_wire_schema()
    payload = require_rust_binding("footprint_report")(
        _query_request(request),
        busy_timeout_ms,
    )
    return dict(payload)


def footprint_card(
    request: Mapping[str, Any],
    *,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Return an evidence card for one feature or area."""

    _require_wire_schema()
    payload = require_rust_binding("footprint_card")(
        _query_request(request),
        busy_timeout_ms,
    )
    return dict(payload)


def footprint_decide(
    store_path: Path | str,
    feature_id: str,
    decision: str,
    reason: str | None,
    today: str,
    snooze_days: int = 30,
    *,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Record, snooze, or clear a local review decision."""

    _require_wire_schema()
    payload = require_rust_binding("footprint_decide")(
        _path_str(store_path),
        str(feature_id),
        str(decision),
        None if reason is None else str(reason),
        str(today),
        int(snooze_days),
        busy_timeout_ms,
    )
    return dict(payload)
