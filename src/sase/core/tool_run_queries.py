"""ToolRun query, retention, receipt, and typed-view calls.

Split from :mod:`sase.core.tool_run` to keep every file under the 500-line
cap. Rust owns the runs table, retention selection, receipts, and the typed
view wires; this module is a wire-only facade over those bindings. Typed
view rows live in ``sase.core.tool_run_views``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.tool_run_paths import tool_run_store_path
from sase.core.tool_run_views import (
    ToolRunBriefs,
    ToolRunDetail,
    ToolRunLiveGlance,
    ToolRunNodeSummaries,
)


def _binding() -> Any:
    """Return the live Rust binding resolver.

    Looked up on the ``sase.core.tool_run`` facade at call time so tests
    patching that seam keep working after the split.
    """

    from sase.core.tool_run import require_rust_binding

    return require_rust_binding


def tool_run_list(
    request: Mapping[str, Any] | None = None,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    payload = {"schema_version": 1, "limit": 50}
    if request:
        payload.update(dict(request))
    return dict(
        _binding()("tool_run_list")(
            store_path or str(tool_run_store_path()),
            payload,
            busy_timeout_ms,
        )
    )


def tool_run_show(
    run_id: str,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_show")(
            store_path or str(tool_run_store_path()),
            {"schema_version": 1, "run_id": run_id},
            busy_timeout_ms,
        )
    )


def tool_run_summary(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_summary")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_retention_preview(
    request: Mapping[str, Any] | None = None,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    payload = {"schema_version": 1, "dry_run": True}
    if request:
        payload.update(dict(request))
    payload["dry_run"] = True
    return dict(
        _binding()("tool_run_retention_preview")(
            store_path or str(tool_run_store_path()),
            payload,
            busy_timeout_ms,
        )
    )


def tool_run_retention_apply(
    request: Mapping[str, Any] | None = None,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    payload = {"schema_version": 1, "dry_run": False}
    if request:
        payload.update(dict(request))
    payload["dry_run"] = False
    return dict(
        _binding()("tool_run_retention_apply")(
            store_path or str(tool_run_store_path()),
            payload,
            busy_timeout_ms,
        )
    )


def tool_run_store_stats(
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_store_stats")(
            store_path or str(tool_run_store_path()),
            busy_timeout_ms,
        )
    )


def tool_run_receipt_settle(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_receipt_settle")(
            store_path or str(tool_run_store_path()),
            {"schema_version": 1, **dict(request)},
            busy_timeout_ms,
        )
    )


def tool_run_receipt_lookup(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_receipt_lookup")(
            store_path or str(tool_run_store_path()),
            {"schema_version": 1, **dict(request)},
            busy_timeout_ms,
        )
    )


def tool_run_receipts_report(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_receipts_report")(
            store_path or str(tool_run_store_path()),
            {"schema_version": 1, **dict(request)},
            busy_timeout_ms,
        )
    )


def tool_run_stats_report(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    """Return the read-only ToolRun stats report over the runs table."""

    return dict(
        _binding()("tool_run_stats_report")(
            store_path or str(tool_run_store_path()),
            {"schema_version": 1, **dict(request)},
            busy_timeout_ms,
        )
    )


def tool_run_record_demand(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    """Merge per-run demand context, usage, and worker grants into a run."""

    return dict(
        _binding()("tool_run_record_demand")(
            store_path or str(tool_run_store_path()),
            {"schema_version": 1, **dict(request)},
            busy_timeout_ms,
        )
    )


def tool_run_live_glance(
    request: Mapping[str, Any] | None = None,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> ToolRunLiveGlance:
    """Return every unsettled run on the machine as typed glance rows."""

    payload = {"schema_version": 1}
    if request:
        payload.update(dict(request))
    return ToolRunLiveGlance.from_wire(
        dict(
            _binding()("tool_run_live_glance")(
                store_path or str(tool_run_store_path()),
                payload,
                busy_timeout_ms,
            )
        )
    )


def tool_run_briefs(
    request: Mapping[str, Any] | None = None,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> ToolRunBriefs:
    """Return the lean filtered run list as typed brief rows."""

    payload = {"schema_version": 1, "limit": 100}
    if request:
        payload.update(dict(request))
    return ToolRunBriefs.from_wire(
        dict(
            _binding()("tool_run_briefs")(
                store_path or str(tool_run_store_path()),
                payload,
                busy_timeout_ms,
            )
        )
    )


def tool_run_node_summaries(
    request: Mapping[str, Any] | None = None,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> ToolRunNodeSummaries:
    """Return per-node history for the requested selectors as typed rows."""

    payload: dict[str, Any] = {"schema_version": 1, "per_node_limit": 20}
    if request:
        payload.update(dict(request))
    return ToolRunNodeSummaries.from_wire(
        dict(
            _binding()("tool_run_node_summaries")(
                store_path or str(tool_run_store_path()),
                payload,
                busy_timeout_ms,
            )
        )
    )


def tool_run_detail(
    run_id: str,
    request: Mapping[str, Any] | None = None,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> ToolRunDetail:
    """Return one run's card-block detail as typed rows.

    Only ``display_argv`` reaches the caller; ``private_argv`` never
    leaves core.
    """

    payload: dict[str, Any] = {"schema_version": 1, "run_id": run_id}
    if request:
        payload.update(dict(request))
    return ToolRunDetail.from_wire(
        dict(
            _binding()("tool_run_detail")(
                store_path or str(tool_run_store_path()),
                payload,
                busy_timeout_ms,
            )
        )
    )


__all__ = [
    "tool_run_briefs",
    "tool_run_detail",
    "tool_run_list",
    "tool_run_live_glance",
    "tool_run_node_summaries",
    "tool_run_receipt_lookup",
    "tool_run_receipt_settle",
    "tool_run_receipts_report",
    "tool_run_record_demand",
    "tool_run_retention_apply",
    "tool_run_retention_preview",
    "tool_run_show",
    "tool_run_stats_report",
    "tool_run_store_stats",
    "tool_run_summary",
]
