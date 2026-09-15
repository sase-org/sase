"""Thin adapter over the Rust disk-inventory classifier."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sase.core.rust import require_rust_binding

DISK_INVENTORY_WIRE_SCHEMA_VERSION = 1


def classify_disk_inventory(
    rows: Iterable[Mapping[str, Any]],
    *,
    scan_diagnostics: Iterable[str] = (),
    stray_scan_visited: int = 0,
    stray_scan_truncated: bool = False,
) -> dict[str, Any]:
    """Classify observed disk-inventory rows through the Rust core contract."""

    _require_disk_inventory_wire_schema()
    request = {
        "schema_version": DISK_INVENTORY_WIRE_SCHEMA_VERSION,
        "rows": [_row_payload(row) for row in rows],
        "scan_diagnostics": [str(value) for value in scan_diagnostics],
        "stray_scan_visited": int(stray_scan_visited),
        "stray_scan_truncated": bool(stray_scan_truncated),
    }
    binding = require_rust_binding("classify_disk_inventory")
    payload = binding(request)
    if not isinstance(payload, dict):
        raise TypeError("sase_core_rs classify_disk_inventory returned a non-dict")
    if payload.get("schema_version") != DISK_INVENTORY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs returned an incompatible disk-inventory result: "
            f"schema_version must be {DISK_INVENTORY_WIRE_SCHEMA_VERSION}"
        )
    return payload


def _require_disk_inventory_wire_schema() -> None:
    binding = require_rust_binding("disk_inventory_wire_schema_version")
    version = int(binding())
    if version != DISK_INVENTORY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs disk-inventory wire is stale: expected "
            f"{DISK_INVENTORY_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _row_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = row.get("diagnostics") or ()
    physical_path = row.get("physical_path")
    return {
        "section": str(row.get("section") or ""),
        "name": str(row.get("name") or ""),
        "path": str(row.get("path") or ""),
        "physical_path": None if physical_path is None else str(physical_path),
        "size_bytes": int(row.get("size_bytes") or 0),
        "owner": str(row.get("owner") or ""),
        "horizon": str(row.get("horizon") or ""),
        "status": str(row.get("status") or "owned"),
        "reclaim": row.get("reclaim"),
        "coverage": str(row.get("coverage") or "complete"),
        "diagnostics": [str(value) for value in diagnostics],
    }


__all__ = [
    "DISK_INVENTORY_WIRE_SCHEMA_VERSION",
    "classify_disk_inventory",
]
