"""Thin adapter over the Rust disk-pressure classifier."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sase.config import (
    get_disk_pressure_error_free_percent,
    get_disk_pressure_top_owner_min_bytes,
    get_disk_pressure_warn_free_percent,
)
from sase.core.rust import require_rust_binding

DISK_PRESSURE_WIRE_SCHEMA_VERSION = 1
ABSOLUTE_ERROR_FREE_BYTES = 1024**3
ABSOLUTE_WARN_FREE_BYTES = 3 * 1024**3


def classify_disk_pressure(
    observations: Iterable[Mapping[str, Any]],
    *,
    owner_rows: Iterable[Mapping[str, Any]] = (),
    absolute_warn_free_bytes: int = ABSOLUTE_WARN_FREE_BYTES,
    absolute_error_free_bytes: int = ABSOLUTE_ERROR_FREE_BYTES,
    warn_free_percent: float | None = None,
    error_free_percent: float | None = None,
    top_owner_min_bytes: int | None = None,
    top_owner_limit: int = 5,
) -> dict[str, Any]:
    """Classify disk pressure through the Rust core contract."""

    _require_disk_pressure_wire_schema()
    request = {
        "schema_version": DISK_PRESSURE_WIRE_SCHEMA_VERSION,
        "observations": [_observation_payload(row) for row in observations],
        "owner_rows": [_owner_row_payload(row) for row in owner_rows],
        "absolute_warn_free_bytes": int(absolute_warn_free_bytes),
        "absolute_error_free_bytes": int(absolute_error_free_bytes),
        "warn_free_percent": (
            get_disk_pressure_warn_free_percent()
            if warn_free_percent is None
            else float(warn_free_percent)
        ),
        "error_free_percent": (
            get_disk_pressure_error_free_percent()
            if error_free_percent is None
            else float(error_free_percent)
        ),
        "top_owner_min_bytes": (
            get_disk_pressure_top_owner_min_bytes()
            if top_owner_min_bytes is None
            else int(top_owner_min_bytes)
        ),
        "top_owner_limit": int(top_owner_limit),
    }
    binding = require_rust_binding("classify_disk_pressure")
    payload = binding(request)
    if not isinstance(payload, dict):
        raise TypeError("sase_core_rs classify_disk_pressure returned a non-dict")
    if payload.get("schema_version") != DISK_PRESSURE_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs returned an incompatible disk-pressure result: "
            f"schema_version must be {DISK_PRESSURE_WIRE_SCHEMA_VERSION}"
        )
    return payload


def _require_disk_pressure_wire_schema() -> None:
    binding = require_rust_binding("disk_pressure_wire_schema_version")
    version = int(binding())
    if version != DISK_PRESSURE_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs disk-pressure wire is stale: expected "
            f"{DISK_PRESSURE_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _observation_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "label": str(row["label"]),
        "role": str(row.get("role") or ""),
        "path": str(row["path"]),
        "measurement_path": str(row.get("measurement_path") or row["path"]),
        "total_bytes": int(row["total_bytes"]),
        "used_bytes": int(row["used_bytes"]),
        "free_bytes": int(row["free_bytes"]),
    }


def _owner_row_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    size_bytes = row.get("exclusive_size_bytes")
    if size_bytes is None:
        size_bytes = row.get("size_bytes") or 0
    return {
        "section": str(row.get("section") or ""),
        "name": str(row.get("name") or ""),
        "path": str(row.get("path") or ""),
        "size_bytes": int(size_bytes),
        "owner": str(row.get("owner") or ""),
        "status": str(row.get("status") or "owned"),
    }


__all__ = [
    "ABSOLUTE_ERROR_FREE_BYTES",
    "ABSOLUTE_WARN_FREE_BYTES",
    "DISK_PRESSURE_WIRE_SCHEMA_VERSION",
    "classify_disk_pressure",
]
