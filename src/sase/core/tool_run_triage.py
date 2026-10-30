"""ToolRun triage ledger calls.

Split from :mod:`sase.core.tool_run` to keep every file under the 500-line
cap. Rust owns triage extraction, classification, verdicts, and the triage
store; this module is a wire-only facade over those bindings. The private
``_triage_payload`` builder stays in this file because no other new module
needs it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.tool_run_paths import tool_run_store_path


def _binding() -> Any:
    """Return the live Rust binding resolver.

    Looked up on the ``sase.core.tool_run`` facade at call time so tests
    patching that seam keep working after the split.
    """

    from sase.core.tool_run import require_rust_binding

    return require_rust_binding


def _triage_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build a v1 triage request without owning any triage policy."""

    return {"schema_version": 1, **dict(request)}


def tool_run_triage_extract(request: Mapping[str, Any]) -> dict[str, Any]:
    return dict(_binding()("tool_run_triage_extract")(_triage_payload(request)))


def tool_run_triage_classify(request: Mapping[str, Any]) -> dict[str, Any]:
    return dict(_binding()("tool_run_triage_classify")(_triage_payload(request)))


def tool_run_triage_verdict(request: Mapping[str, Any]) -> dict[str, Any]:
    return dict(_binding()("tool_run_triage_verdict")(_triage_payload(request)))


def tool_run_triage_record(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_triage_record")(
            store_path or str(tool_run_store_path()),
            _triage_payload(request),
            busy_timeout_ms,
        )
    )


def tool_run_triage_show(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_triage_show")(
            store_path or str(tool_run_store_path()),
            _triage_payload(request),
            busy_timeout_ms,
        )
    )


def tool_run_triage_stage(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_triage_stage")(
            store_path or str(tool_run_store_path()),
            _triage_payload(request),
            busy_timeout_ms,
        )
    )


def tool_run_triage_settle(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_triage_settle")(
            store_path or str(tool_run_store_path()),
            _triage_payload(request),
            busy_timeout_ms,
        )
    )


def tool_run_failures(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_failures")(
            store_path or str(tool_run_store_path()),
            _triage_payload(request),
            busy_timeout_ms,
        )
    )


__all__ = [
    "tool_run_failures",
    "tool_run_triage_classify",
    "tool_run_triage_extract",
    "tool_run_triage_record",
    "tool_run_triage_settle",
    "tool_run_triage_show",
    "tool_run_triage_stage",
    "tool_run_triage_verdict",
]
