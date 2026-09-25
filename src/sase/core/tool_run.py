"""Thin ToolRun ledger adapter over ``sase_core_rs``.

Rust owns catalog normalization, fingerprints, the SQLite store, retention
selection, and queries. This module is a wire-only facade: it resolves
``sase_home()/tools``, releases the GIL inside the bindings, and never keeps
a Python store.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding

_STORE_FILENAME = "runs.sqlite"


def tools_dir() -> Path:
    """Return the machine-local ToolRun root ``sase_home()/tools``."""

    return sase_home() / "tools"


def tool_run_store_path() -> Path:
    """Return the SQLite path Rust receives for the ToolRun ledger."""

    return tools_dir() / _STORE_FILENAME


def tool_run_wire_schema_version() -> int:
    return int(require_rust_binding("tool_run_wire_schema_version")())


def tool_run_normalize_definition(definition: Mapping[str, Any]) -> dict[str, Any]:
    return dict(require_rust_binding("tool_run_normalize_definition")(dict(definition)))


def tool_run_canonicalize_fingerprint(
    fingerprint: Mapping[str, Any],
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_canonicalize_fingerprint")(dict(fingerprint))
    )


def tool_run_unknown_evidence(reason: str) -> dict[str, Any]:
    return dict(require_rust_binding("tool_run_unknown_evidence")(reason))


def _triage_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build a v1 triage request without owning any triage policy."""

    return {"schema_version": 1, **dict(request)}


def tool_run_triage_extract(request: Mapping[str, Any]) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_triage_extract")(_triage_payload(request))
    )


def tool_run_triage_classify(request: Mapping[str, Any]) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_triage_classify")(_triage_payload(request))
    )


def tool_run_triage_verdict(request: Mapping[str, Any]) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_triage_verdict")(_triage_payload(request))
    )


def tool_run_triage_record(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_triage_record")(
            store_path or str(tool_run_store_path()),
            _triage_payload(request),
            busy_timeout_ms,
        )
    )


def tool_run_triage_show(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_triage_show")(
            store_path or str(tool_run_store_path()),
            _triage_payload(request),
            busy_timeout_ms,
        )
    )


def tool_run_triage_stage(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_triage_stage")(
            store_path or str(tool_run_store_path()),
            _triage_payload(request),
            busy_timeout_ms,
        )
    )


def tool_run_triage_settle(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_triage_settle")(
            store_path or str(tool_run_store_path()),
            _triage_payload(request),
            busy_timeout_ms,
        )
    )


def tool_run_failures(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_failures")(
            store_path or str(tool_run_store_path()),
            _triage_payload(request),
            busy_timeout_ms,
        )
    )


def tool_run_begin(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_begin")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_append_event(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_append_event")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_finish(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_finish")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_observe(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Persist a running run's child pid, pgid, and process-start identity.

    Called once after a successful spawn, before the output pumps start, so
    a run killed seconds later still records a reapable group.
    """

    return dict(
        require_rust_binding("tool_run_observe")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_reconcile(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_reconcile")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_claim(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Atomically claim a reserved hand-off run for its owner."""

    return dict(
        require_rust_binding("tool_run_claim")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_request_stop(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Record a durable stop request for a ToolRun."""

    return dict(
        require_rust_binding("tool_run_request_stop")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_list(
    request: Mapping[str, Any] | None = None,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    payload = {"schema_version": 1, "limit": 50}
    if request:
        payload.update(dict(request))
    return dict(
        require_rust_binding("tool_run_list")(
            store_path or str(tool_run_store_path()),
            payload,
            busy_timeout_ms,
        )
    )


def tool_run_show(
    run_id: str,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_show")(
            store_path or str(tool_run_store_path()),
            {"schema_version": 1, "run_id": run_id},
            busy_timeout_ms,
        )
    )


def tool_run_summary(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_summary")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_retention_preview(
    request: Mapping[str, Any] | None = None,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    payload = {"schema_version": 1, "dry_run": True}
    if request:
        payload.update(dict(request))
    payload["dry_run"] = True
    return dict(
        require_rust_binding("tool_run_retention_preview")(
            store_path or str(tool_run_store_path()),
            payload,
            busy_timeout_ms,
        )
    )


def tool_run_retention_apply(
    request: Mapping[str, Any] | None = None,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    payload = {"schema_version": 1, "dry_run": False}
    if request:
        payload.update(dict(request))
    payload["dry_run"] = False
    return dict(
        require_rust_binding("tool_run_retention_apply")(
            store_path or str(tool_run_store_path()),
            payload,
            busy_timeout_ms,
        )
    )


def tool_run_store_stats(
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    return dict(
        require_rust_binding("tool_run_store_stats")(
            store_path or str(tool_run_store_path()),
            busy_timeout_ms,
        )
    )


__all__ = [
    "tool_run_append_event",
    "tool_run_begin",
    "tool_run_canonicalize_fingerprint",
    "tool_run_claim",
    "tool_run_finish",
    "tool_run_list",
    "tool_run_normalize_definition",
    "tool_run_observe",
    "tool_run_reconcile",
    "tool_run_request_stop",
    "tool_run_retention_apply",
    "tool_run_retention_preview",
    "tool_run_failures",
    "tool_run_show",
    "tool_run_store_path",
    "tool_run_store_stats",
    "tool_run_summary",
    "tool_run_triage_classify",
    "tool_run_triage_extract",
    "tool_run_triage_record",
    "tool_run_triage_settle",
    "tool_run_triage_show",
    "tool_run_triage_stage",
    "tool_run_triage_verdict",
    "tool_run_unknown_evidence",
    "tool_run_wire_schema_version",
    "tools_dir",
]
