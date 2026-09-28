"""Thin, fail-open adapter over the Rust managed-temp-roots registry.

The registry records every root :func:`sase.core.paths.get_sase_managed_tmpdir`
writes into, so reaper entry points can reap all registered roots instead of
only the root their own environment resolves. ``sase_core_rs``
(``sase-core``'s ``managed_tmp_roots`` module) owns the registry file
(``$SASE_HOME/managed_tmp/roots.json``), validation, locking, and atomic
writes; this module resolves inputs, checks the wire schema, and keeps every
failure from breaking its caller.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from collections.abc import Mapping

from sase.core.rust import require_rust_binding

log = logging.getLogger(__name__)

MANAGED_TMP_ROOTS_WIRE_SCHEMA_VERSION = 1
"""Must match ``sase_core::managed_tmp_roots::MANAGED_TMP_ROOTS_WIRE_SCHEMA_VERSION``."""

_warned_registration_failures: set[str] = set()


def _register_managed_tmp_root(
    root: Path | str,
    *,
    sase_home: Path | str,
    now: float | None = None,
) -> Mapping[str, Any]:
    """Register *root* in the managed-temp-roots registry and return it.

    Raises the Rust binding's error (or a wire-schema mismatch) to the
    caller; use :func:`try_register_managed_tmp_root` for the fail-open
    writer hook.
    """
    _require_roots_wire_schema()
    binding = require_rust_binding("managed_tmp_roots_register")
    clock = time.time() if now is None else now
    raw = binding(str(sase_home), str(root), float(clock))
    return _snapshot_from_wire(raw)


def try_register_managed_tmp_root(
    root: Path | str,
    *,
    sase_home: Path | str,
) -> None:
    """Register *root*, logging one warning instead of raising on failure.

    Registration is fail-open: a failure logs one warning per root and never
    breaks a launch.
    """
    key = str(root)
    try:
        _register_managed_tmp_root(root, sase_home=sase_home)
    except Exception as exc:  # noqa: BLE001 - registration must never break a launch.
        if key not in _warned_registration_failures:
            _warned_registration_failures.add(key)
            log.warning("managed tmp root registration failed for %s: %s", key, exc)


def _registered_managed_tmp_roots(
    *,
    sase_home: Path | str,
) -> list[Path]:
    """Return registered roots that still exist as directories.

    A missing or unreadable registry reads as empty; callers always union
    this with the effective root.
    """
    try:
        _require_roots_wire_schema()
        binding = require_rust_binding("managed_tmp_roots_list")
        raw = binding(str(sase_home))
        snapshot = _snapshot_from_wire(raw)
    except Exception:  # noqa: BLE001 - readers fall back to the effective root.
        return []
    roots: list[Path] = []
    for entry in snapshot["roots"]:
        candidate = Path(entry["path"])
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def effective_managed_tmp_roots(
    *,
    effective_root: Path | str,
    sase_home: Path | str,
) -> list[Path]:
    """Return the roots one reaper pass covers, de-duplicated and folded.

    The union of the *effective_root* this process resolves, every
    registered root that still exists, and ``$SASE_HOME/tmp`` when it
    exists. Each pass also (fail-open) registers the effective root and an
    existing ``$SASE_HOME/tmp`` so writers that predate the registry are
    picked up.

    Candidates are first de-duplicated by resolved path, then a candidate
    whose resolved path sits strictly inside another candidate's resolved
    path is dropped: the outer root's reaper already owns that nested tree
    at launch-key granularity, so covering both double-reaps and
    double-counts it. The outermost root is kept, in original order.
    """
    home = Path(sase_home)
    effective = Path(effective_root)
    candidates: list[Path] = [effective]
    default_root = home / "tmp"
    if default_root.is_dir():
        candidates.append(default_root)
    candidates.extend(_registered_managed_tmp_roots(sase_home=home))
    for candidate in candidates:
        if candidate.is_dir():
            try_register_managed_tmp_root(candidate, sase_home=home)
    deduped: list[Path] = []
    resolved_paths: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(candidate)
        resolved_paths.append(resolved)
    folded: list[Path] = []
    for candidate, resolved in zip(deduped, resolved_paths, strict=True):
        nested_in_another = any(
            resolved != other and resolved.is_relative_to(other)
            for other in resolved_paths
        )
        if not nested_in_another:
            folded.append(candidate)
    return folded


def _require_roots_wire_schema() -> None:
    binding = require_rust_binding("managed_tmp_roots_wire_schema_version")
    version = int(binding())
    if version != MANAGED_TMP_ROOTS_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs managed-temp-roots wire is stale: expected "
            f"{MANAGED_TMP_ROOTS_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _snapshot_from_wire(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    if raw["schema_version"] != MANAGED_TMP_ROOTS_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs returned an incompatible managed-temp-roots result: "
            f"schema_version must be {MANAGED_TMP_ROOTS_WIRE_SCHEMA_VERSION}"
        )
    roots = tuple(
        {
            "path": str(entry["path"]),
            "first_seen_epoch": float(entry["first_seen_epoch"]),
            "last_seen_epoch": float(entry["last_seen_epoch"]),
        }
        for entry in raw["roots"]
    )
    return {"schema_version": int(raw["schema_version"]), "roots": roots}


__all__ = [
    "MANAGED_TMP_ROOTS_WIRE_SCHEMA_VERSION",
    "effective_managed_tmp_roots",
    "try_register_managed_tmp_root",
]
