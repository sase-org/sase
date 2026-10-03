"""Thin facade over the Rust ``memory_history`` bindings.

Every helper calls ``sase_core_rs`` directly through
:func:`sase.core.rust.require_rust_binding` and passes plain ``dict``
values both ways: scope inputs are built with
:mod:`sase.core.memory_history_wire`, and every query response is
returned unchanged so ``sase memory history --format json`` can emit the
Rust wire verbatim. Python never re-implements lineage, classification,
cause attribution, or diffing.

All helpers release the GIL inside the binding, so ACE worker threads
never stall the event loop; nevertheless callers must still keep these
calls off the keystroke and render paths (see the epic design
``plan:202609/memory_history.md`` §5.4).
"""

from __future__ import annotations

from typing import Any

from sase.core.memory_history_wire import (
    MEMORY_HISTORY_WIRE_SCHEMA_VERSION,
    MemoryHistoryScope,
)
from sase.core.rust import require_rust_binding


def wire_schema_version() -> int:
    """Return the Rust memory-history wire schema version."""
    binding = require_rust_binding("memory_history_wire_schema_version")
    return int(binding())


def _call(binding_name: str, request: dict[str, Any]) -> dict[str, Any]:
    """Invoke one ``memory_history_*`` binding with a wire dict."""
    binding = require_rust_binding(binding_name)
    return dict(binding(request))


def sync_scope(scope: MemoryHistoryScope) -> dict[str, Any]:
    """Sync one scope and return the sync record."""
    return _call("memory_history_sync", {"scope": scope.to_dict()})


def list_subjects(scope: MemoryHistoryScope) -> dict[str, Any]:
    """Sync one scope and list its subjects without version bodies."""
    return _call("memory_history_subjects", {"scope": scope.to_dict()})


def resolve_subject(
    scope: MemoryHistoryScope,
    selector: str,
    *,
    at_commit: str | None = None,
) -> dict[str, Any]:
    """Resolve a selector to its subject, with the newest or as-of version."""
    request: dict[str, Any] = {"scope": scope.to_dict(), "selector": selector}
    if at_commit is not None:
        request["at_commit"] = at_commit
    return _call("memory_history_resolve", request)


def get_timeline(
    scope: MemoryHistoryScope,
    selector: str,
    *,
    include_hidden: bool = False,
) -> dict[str, Any]:
    """Return one subject's history with worktree pseudo-versions first."""
    return _call(
        "memory_history_timeline",
        {
            "scope": scope.to_dict(),
            "selector": selector,
            "include_hidden": include_hidden,
        },
    )


def get_version(
    scope: MemoryHistoryScope,
    selector: str,
    version: str,
    *,
    include_body: bool = False,
) -> dict[str, Any]:
    """Return one version by ordinal, ``~N``, SHA prefix, ``blob:OID``, or ``now``."""
    return _call(
        "memory_history_version",
        {
            "scope": scope.to_dict(),
            "selector": selector,
            "version": version,
            "include_body": include_body,
        },
    )


def compare_versions(
    scope: MemoryHistoryScope,
    base_selector: str,
    base_version: str,
    target_selector: str,
    target_version: str,
) -> dict[str, Any]:
    """Compare two versions with both blobs fetched inside core."""
    return _call(
        "memory_history_compare",
        {
            "scope": scope.to_dict(),
            "base_selector": base_selector,
            "base_version": base_version,
            "target_selector": target_selector,
            "target_version": target_version,
        },
    )


def get_feed(
    scopes: list[MemoryHistoryScope],
    *,
    since: int | None = None,
    limit: int | None = None,
    include_hidden: bool = False,
) -> dict[str, Any]:
    """Sync scopes and merge their changesets into one feed."""
    request: dict[str, Any] = {
        "scopes": [scope.to_dict() for scope in scopes],
        "include_hidden": include_hidden,
    }
    if since is not None:
        request["since"] = since
    if limit is not None:
        request["limit"] = limit
    return _call("memory_history_feed", request)


def review_state(
    scopes: list[MemoryHistoryScope],
    *,
    state_dir: str,
) -> dict[str, Any]:
    """Return per-scope review watermarks, N-new counts, and newest commits."""
    return _call(
        "memory_history_review_state",
        {
            "scopes": [scope.to_dict() for scope in scopes],
            "state_dir": state_dir,
        },
    )


def mark_reviewed(
    scope: MemoryHistoryScope,
    *,
    through_commit: str,
    state_dir: str,
) -> dict[str, Any]:
    """Record one scope's review watermark through a commit."""
    return _call(
        "memory_history_mark_reviewed",
        {
            "scope": scope.to_dict(),
            "through_commit": through_commit,
            "state_dir": state_dir,
        },
    )


__all__ = [
    "MEMORY_HISTORY_WIRE_SCHEMA_VERSION",
    "compare_versions",
    "get_feed",
    "get_timeline",
    "get_version",
    "list_subjects",
    "mark_reviewed",
    "resolve_subject",
    "review_state",
    "sync_scope",
    "wire_schema_version",
]
