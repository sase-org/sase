"""Thin adapter over the Rust disk-pressure classifier."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
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


@dataclass(frozen=True)
class _FilesystemPressurePolicy:
    """Effective disk-pressure thresholds for one measured filesystem."""

    observation: dict[str, Any]
    result: dict[str, Any]

    @property
    def free_bytes(self) -> int:
        return int(self.result["free_bytes"])

    @property
    def warn_free_bytes(self) -> int:
        return int(self.result["warn_threshold_bytes_effective"])

    @property
    def error_free_bytes(self) -> int:
        return int(self.result["error_threshold_bytes_effective"])


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


def collect_filesystem_observations(
    targets: Iterable[Mapping[str, Any]],
    *,
    disk_usage_fn: Any = shutil.disk_usage,
    filesystem_identity_fn: Any | None = None,
) -> tuple[dict[str, Any], ...]:
    """Measure one observation per filesystem for the supplied target paths."""

    observations: list[dict[str, Any]] = []
    seen_filesystems: set[object] = set()
    for target in targets:
        path = Path(str(target["path"])).expanduser()
        measurement_path = _nearest_existing_parent(path)
        if measurement_path is None:
            measurement_path = path
        filesystem_identity = _filesystem_identity(
            measurement_path,
            filesystem_identity_fn=filesystem_identity_fn,
        )
        if filesystem_identity in seen_filesystems:
            continue
        seen_filesystems.add(filesystem_identity)
        usage = disk_usage_fn(str(measurement_path))
        observations.append(
            {
                "label": str(target["label"]),
                "role": str(target.get("role") or ""),
                "path": str(path),
                "measurement_path": str(measurement_path),
                "total_bytes": int(usage.total),
                "used_bytes": int(usage.used),
                "free_bytes": int(usage.free),
            }
        )
    return tuple(observations)


def filesystem_pressure_policy(
    *,
    label: str,
    role: str,
    path: Path,
    disk_usage_fn: Any = shutil.disk_usage,
    filesystem_identity_fn: Any | None = None,
) -> _FilesystemPressurePolicy:
    """Return the Rust-classified effective free-space policy for *path*."""

    observations = collect_filesystem_observations(
        ({"label": label, "role": role, "path": str(path)},),
        disk_usage_fn=disk_usage_fn,
        filesystem_identity_fn=filesystem_identity_fn,
    )
    if not observations:
        raise RuntimeError(f"could not observe filesystem for {path}")
    classified = classify_disk_pressure(observations, top_owner_limit=0)
    return _FilesystemPressurePolicy(
        observation=observations[0],
        result=classified["observations"][0],
    )


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


def _nearest_existing_parent(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate if candidate.is_dir() else candidate.parent
    return None


def _filesystem_identity(
    path: Path,
    *,
    filesystem_identity_fn: Any | None = None,
) -> object:
    if filesystem_identity_fn is not None:
        return filesystem_identity_fn(path)
    try:
        stat_result = os.stat(path)
    except OSError:
        return ("path", os.path.realpath(path))
    device = getattr(stat_result, "st_dev", None)
    if device is None:
        return ("path", os.path.realpath(path))
    return ("dev", int(device))


__all__ = [
    "ABSOLUTE_ERROR_FREE_BYTES",
    "ABSOLUTE_WARN_FREE_BYTES",
    "DISK_PRESSURE_WIRE_SCHEMA_VERSION",
    "classify_disk_pressure",
    "collect_filesystem_observations",
    "filesystem_pressure_policy",
]
