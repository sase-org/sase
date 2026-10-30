"""ToolRun catalog normalization and budgeting helpers.

Split from :mod:`sase.core.tool_run` to keep every file under the 500-line
cap. Rust owns catalog normalization, fingerprints, and the sync-wait
budget; this module is a wire-only facade over those bindings. The private
``_duration_payload`` builder stays in this file because no other new
module needs it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _binding() -> Any:
    """Return the live Rust binding resolver.

    Looked up on the ``sase.core.tool_run`` facade at call time so tests
    patching that seam keep working after the split.
    """

    from sase.core.tool_run import require_rust_binding

    return require_rust_binding


def tool_run_wire_schema_version() -> int:
    return int(_binding()("tool_run_wire_schema_version")())


def tool_run_normalize_definition(definition: Mapping[str, Any]) -> dict[str, Any]:
    return dict(_binding()("tool_run_normalize_definition")(dict(definition)))


def tool_run_canonicalize_fingerprint(
    fingerprint: Mapping[str, Any],
) -> dict[str, Any]:
    return dict(_binding()("tool_run_canonicalize_fingerprint")(dict(fingerprint)))


def tool_run_unknown_evidence(reason: str) -> dict[str, Any]:
    return dict(_binding()("tool_run_unknown_evidence")(reason))


def _duration_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build a v1 duration request without owning any duration policy."""

    return {"schema_version": 1, **dict(request)}


def tool_run_duration_fit(request: Mapping[str, Any]) -> dict[str, Any]:
    return dict(_binding()("tool_run_duration_fit")(_duration_payload(request)))


def tool_run_duration_calibration(request: Mapping[str, Any]) -> dict[str, Any]:
    return dict(_binding()("tool_run_duration_calibration")(_duration_payload(request)))


def tool_run_sync_wait_budget(request: Mapping[str, Any]) -> dict[str, Any]:
    """Budget a synchronous wait against hard and soft kill ceilings.

    Rust owns the margin formula and constants; this facade passes the
    validated positive-integer ceilings through unchanged.
    """

    return dict(_binding()("tool_run_sync_wait_budget")(dict(request)))


__all__ = [
    "tool_run_canonicalize_fingerprint",
    "tool_run_duration_calibration",
    "tool_run_duration_fit",
    "tool_run_normalize_definition",
    "tool_run_sync_wait_budget",
    "tool_run_unknown_evidence",
    "tool_run_wire_schema_version",
]
