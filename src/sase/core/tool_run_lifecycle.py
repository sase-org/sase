"""ToolRun lifecycle ledger calls.

Split from :mod:`sase.core.tool_run` to keep every file under the 500-line
cap. Rust owns the runs table and join reservations; this module is a
wire-only facade over those bindings.
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


def tool_run_begin(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_begin")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_append_event(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_append_event")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_finish(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_finish")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_observe(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    """Persist a running run's child pid, pgid, and process-start identity.

    Called once after a successful spawn, before the output pumps start, so
    a run killed seconds later still records a reapable group.
    """

    return dict(
        _binding()("tool_run_observe")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_reconcile(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    return dict(
        _binding()("tool_run_reconcile")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_claim(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    """Atomically claim a reserved hand-off run for its owner."""

    return dict(
        _binding()("tool_run_claim")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_request_stop(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    """Record a durable stop request for a ToolRun."""

    return dict(
        _binding()("tool_run_request_stop")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_join(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    """Record a monitor join on a starter-scoped detached run."""

    return dict(
        _binding()("tool_run_join")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_release_join(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    """Release a monitor join when kind and id match; allowed in any state."""

    return dict(
        _binding()("tool_run_release_join")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_reserve_staged_join(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    """Reserve a detached run for one staged monitor.

    The reservation is identified by staged ID plus monitor ID, validates
    the starter agent, and prevents another joiner from taking the run.
    """

    return dict(
        _binding()("tool_run_reserve_staged_join")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_activate_staged_join(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    """Activate a staged-join reservation into the ordinary monitor join."""

    return dict(
        _binding()("tool_run_activate_staged_join")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


def tool_run_release_staged_join(
    request: Mapping[str, Any],
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 0,
) -> dict[str, Any]:
    """Release one stage's join reservation; safe to repeat after settling."""

    return dict(
        _binding()("tool_run_release_staged_join")(
            store_path or str(tool_run_store_path()),
            dict(request),
            busy_timeout_ms,
        )
    )


__all__ = [
    "tool_run_activate_staged_join",
    "tool_run_append_event",
    "tool_run_begin",
    "tool_run_claim",
    "tool_run_finish",
    "tool_run_join",
    "tool_run_observe",
    "tool_run_reconcile",
    "tool_run_release_join",
    "tool_run_release_staged_join",
    "tool_run_request_stop",
    "tool_run_reserve_staged_join",
]
