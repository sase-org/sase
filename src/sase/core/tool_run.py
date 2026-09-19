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
    "tool_run_finish",
    "tool_run_list",
    "tool_run_normalize_definition",
    "tool_run_reconcile",
    "tool_run_retention_apply",
    "tool_run_retention_preview",
    "tool_run_show",
    "tool_run_store_path",
    "tool_run_store_stats",
    "tool_run_summary",
    "tool_run_unknown_evidence",
    "tool_run_wire_schema_version",
    "tools_dir",
]
