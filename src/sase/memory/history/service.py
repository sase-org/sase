"""Thread-safe history service over the memory-history bindings.

The CLI, the pager provider, and the Memory panel all query through
:class:`HistoryService`. It keeps an in-process memo of built scopes so
repeated calls do not re-walk the agent-docs inventory, and it never
runs on the event loop: every binding releases the GIL, but callers
must still query off the keystroke and render paths (epic design
``plan:202609/memory_history.md`` §5.4).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from sase.core.memory_history_facade import (
    compare_versions,
    get_feed,
    get_timeline,
    get_version,
    list_subjects,
    resolve_subject,
    sync_scope,
    wire_schema_version,
)
from sase.core.memory_history_wire import (
    MEMORY_HISTORY_WIRE_SCHEMA_VERSION,
    MemoryHistoryScope,
)
from sase.memory.history.scopes import (
    HistoryScopeError,
    build_home_scope,
    build_project_scope,
)


class HistoryNotFoundError(HistoryScopeError):
    """Raised when a selector resolves in no enabled scope."""


class HistoryAmbiguityError(HistoryScopeError):
    """Raised when a selector matches more than one subject."""

    def __init__(self, selector: str, candidates: tuple[str, ...]) -> None:
        super().__init__(
            f"history selector {selector!r} matches {len(candidates)} subjects: "
            + ", ".join(candidates)
        )
        self.selector = selector
        self.candidates = candidates


class HistoryService:
    """Memoized, thread-safe wrapper around the history bindings."""

    def __init__(self) -> None:
        reported = wire_schema_version()
        if reported != MEMORY_HISTORY_WIRE_SCHEMA_VERSION:
            raise HistoryScopeError(
                "memory-history wire schema drift: Python expects "
                f"{MEMORY_HISTORY_WIRE_SCHEMA_VERSION}, "
                f"the Rust core reports {reported}"
            )
        self._lock = threading.RLock()
        self._project_scopes: dict[str, MemoryHistoryScope] = {}
        self._home_scope: MemoryHistoryScope | None = None
        self._home_known_missing = False

    def project_scope(self, project_root: Path | str) -> MemoryHistoryScope:
        """Return the memoized project scope for a checkout root."""
        key = str(project_root)
        with self._lock:
            cached = self._project_scopes.get(key)
            if cached is not None:
                return cached
            scope = build_project_scope(Path(project_root))
            self._project_scopes[key] = scope
            return scope

    def home_scope(self) -> MemoryHistoryScope | None:
        """Return the memoized home scope, or ``None`` (NO VCS)."""
        with self._lock:
            if self._home_scope is not None:
                return self._home_scope
            if self._home_known_missing:
                return None
            scope = build_home_scope()
            if scope is None:
                self._home_known_missing = True
                return None
            self._home_scope = scope
            return scope

    def forget_scopes(self) -> None:
        """Drop memoized scopes so the next call rebuilds them."""
        with self._lock:
            self._project_scopes.clear()
            self._home_scope = None
            self._home_known_missing = False

    def scopes_for(
        self,
        scope_arg: str,
        project_root: Path | str,
    ) -> list[MemoryHistoryScope]:
        """Return the enabled scopes named by a ``-S/--scope`` value."""
        if scope_arg == "project":
            return [self.project_scope(project_root)]
        if scope_arg == "home":
            scope = self.home_scope()
            if scope is None:
                raise HistoryScopeError(
                    "home memory is not in git (NO VCS): enable chezmoi "
                    "with a git-backed source to read home history"
                )
            return [scope]
        if scope_arg == "all":
            scopes = [self.project_scope(project_root)]
            home = self.home_scope()
            if home is not None:
                scopes.append(home)
            return scopes
        raise HistoryScopeError(
            f"unknown history scope {scope_arg!r}: expected all, home, or project"
        )

    def sync(self, scope: MemoryHistoryScope) -> dict[str, Any]:
        """Sync one scope and return the sync record."""
        return sync_scope(scope)

    def subjects(self, scope: MemoryHistoryScope) -> dict[str, Any]:
        """List one scope's subjects without version bodies."""
        return list_subjects(scope)

    def resolve(
        self,
        scope: MemoryHistoryScope,
        selector: str,
        *,
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a selector within one scope."""
        return resolve_subject(scope, selector, at_commit=at_commit)

    def timeline(
        self,
        scope: MemoryHistoryScope,
        selector: str,
        *,
        include_hidden: bool = False,
    ) -> dict[str, Any]:
        """Return one subject's history with pseudo-versions first."""
        return get_timeline(scope, selector, include_hidden=include_hidden)

    def version(
        self,
        scope: MemoryHistoryScope,
        selector: str,
        version: str,
        *,
        include_body: bool = False,
    ) -> dict[str, Any]:
        """Return one version, optionally with its body."""
        return get_version(scope, selector, version, include_body=include_body)

    def compare(
        self,
        scope: MemoryHistoryScope,
        base_selector: str,
        base_version: str,
        target_selector: str,
        target_version: str,
    ) -> dict[str, Any]:
        """Compare two versions with blobs fetched inside core."""
        return compare_versions(
            scope, base_selector, base_version, target_selector, target_version
        )

    def feed(
        self,
        scopes: list[MemoryHistoryScope],
        *,
        since: int | None = None,
        limit: int | None = None,
        include_hidden: bool = False,
    ) -> dict[str, Any]:
        """Merge scopes' changesets into one feed."""
        return get_feed(scopes, since=since, limit=limit, include_hidden=include_hidden)

    def resolve_in_scopes(
        self,
        scopes: list[MemoryHistoryScope],
        selector: str,
        *,
        at_commit: str | None = None,
    ) -> tuple[MemoryHistoryScope, dict[str, Any]]:
        """Resolve a selector across scopes.

        Returns the single scope whose resolve succeeds paired with its
        resolve wire. Raises :class:`HistoryNotFoundError` when no scope
        resolves the selector and :class:`HistoryAmbiguityError` when
        more than one does.
        """
        matches: list[tuple[MemoryHistoryScope, dict[str, Any]]] = []
        failures: list[str] = []
        for scope in scopes:
            try:
                resolved = self.resolve(scope, selector, at_commit=at_commit)
            except Exception as exc:  # noqa: BLE001 — one scope's miss is routine
                failures.append(f"{scope.scope_key}: {exc}")
                continue
            matches.append((scope, resolved))
        if not matches:
            detail = "; ".join(failures) if failures else "no scopes enabled"
            raise HistoryNotFoundError(
                f"history selector {selector!r} resolved to no subject ({detail})"
            )
        if len(matches) > 1:
            raise HistoryAmbiguityError(
                selector,
                tuple(
                    str(match[1].get("subject", {}).get("id", match[0].scope_key))
                    for match in matches
                ),
            )
        return matches[0]


_SHARED_LOCK = threading.Lock()
_SHARED_SERVICE: HistoryService | None = None


def shared_history_service() -> HistoryService:
    """Return the process-wide shared :class:`HistoryService`, building it lazily.

    Thread-safe: concurrent callers share the one built instance. A
    construction failure is never cached, so the next call retries.
    The pager provider factory and ACE both use this instead of
    building a service per lookup (epic design
    ``plan:202610/memory_history_tui.md`` §5.2).
    """
    global _SHARED_SERVICE
    with _SHARED_LOCK:
        if _SHARED_SERVICE is not None:
            return _SHARED_SERVICE
        service = HistoryService()
        _SHARED_SERVICE = service
        return service


__all__ = [
    "HistoryAmbiguityError",
    "HistoryNotFoundError",
    "HistoryService",
    "shared_history_service",
]
