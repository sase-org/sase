"""TUI wrappers for inferring bead metadata from agent records.

The bead display cache expresses three states for a candidate bead id:

* **cache miss** (:data:`BEAD_DISPLAY_CACHE_MISS`) — the candidate has not been
  checked against any bead store yet.
* ``None`` — checked, but no concrete issue exists (do not render bead UI).
* ``str`` — checked, the issue exists, and the display string is ready.

A confirmed issue with no description/title caches the bare bead id string so
``None`` stays reserved for "not confirmed / do not render".
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
import os
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Final

from sase.agent.bead_display import (
    BeadIssueLookupSession,
    derive_agent_bead_id_from_name,
    format_agent_bead_display_for_name,
)

from .agent import Agent, AgentType

BEAD_DISPLAY_CACHE_MISS: Final = object()
_CACHE_TTL_SECONDS = 60.0
_CACHE_MISS_TTL_SECONDS = 300.0
_CACHE_MAX_ENTRIES = 256
BeadDisplayCacheKey = tuple[str, str | None, str | None]


class _BeadDisplayCache:
    """Small TTL-bounded cache for enriched bead display strings."""

    def __init__(
        self,
        *,
        ttl_seconds: float = _CACHE_TTL_SECONDS,
        miss_ttl_seconds: float = _CACHE_MISS_TTL_SECONDS,
        max_entries: int,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._miss_ttl_seconds = miss_ttl_seconds
        self._max_entries = max_entries
        self._entries: OrderedDict[BeadDisplayCacheKey, tuple[float, str | None]] = (
            OrderedDict()
        )
        self._fingerprints: dict[BeadDisplayCacheKey, str] = {}
        self._lock = RLock()

    def get(self, key: BeadDisplayCacheKey) -> str | None | object:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return BEAD_DISPLAY_CACHE_MISS

            _, value = entry
            self._entries.move_to_end(key)
            return value

    def should_resolve(self, key: BeadDisplayCacheKey) -> bool:
        """Return whether *key* has no entry or needs TTL revalidation."""
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return True

            expires_at, _ = entry
            self._entries.move_to_end(key)
            return expires_at <= now

    def resolution_reason(self, key: BeadDisplayCacheKey) -> str | None:
        """Return the bounded cache cause for a needed resolution."""
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return "cold"
            self._entries.move_to_end(key)
            return "ttl" if entry[0] <= now else None

    def set(self, key: BeadDisplayCacheKey, value: str | None) -> None:
        ttl_seconds = self._miss_ttl_seconds if value is None else self._ttl_seconds
        expires_at = monotonic() + ttl_seconds
        with self._lock:
            self._entries[key] = (expires_at, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._fingerprints.clear()

    def fingerprint_for(self, key: BeadDisplayCacheKey) -> str | None:
        """Return the store token seen at the last confirmed resolve."""
        with self._lock:
            return self._fingerprints.get(key)

    def set_fingerprint(
        self, key: BeadDisplayCacheKey, fingerprint: str | None
    ) -> None:
        """Record the store token for *key*; ``None`` clears it to fail open."""
        with self._lock:
            if fingerprint is None:
                self._fingerprints.pop(key, None)
            else:
                self._fingerprints[key] = fingerprint
                while len(self._fingerprints) > self._max_entries:
                    self._fingerprints.pop(next(iter(self._fingerprints)))


_BEAD_DISPLAY_CACHE = _BeadDisplayCache(max_entries=_CACHE_MAX_ENTRIES)


def _store_token_for_beads_dir(beads_dir: Path) -> str | None:
    """Return a stat-only token for *beads_dir* or ``None`` when unprovable."""
    try:
        from sase.core.bead_read_facade import store_fingerprint

        fingerprint = store_fingerprint(beads_dir)
    except Exception:
        return None
    if fingerprint is not None:
        return fingerprint.token
    try:
        stat = (beads_dir / "issues.jsonl").stat()
    except OSError:
        return None
    return f"mtime:{stat.st_mtime_ns}:{stat.st_size}"


def _bead_display_fingerprint(agent: Agent) -> str | None:
    """Return a stat-only token for the authoritative project bead store.

    Uses the existing canonical project-store locator and Rust-owned store
    fingerprints; workspace fallbacks stay on the legacy lookup path so no
    private backend helper is imported here. Returns ``None`` when no
    authoritative store can be proven (fail open to a full lookup) and a
    ``"MISSING:..."`` sentinel for a stable absent store. Must only be called
    off the Textual event loop.
    """
    tokens: list[str] = []
    project_name = _agent_project_name(agent)
    if project_name is None:
        return None
    try:
        from sase.bead.store_locator import canonical_beads_dir_for_project

        beads_dir = canonical_beads_dir_for_project(project_name)
    except Exception:
        return None
    if beads_dir is None:
        tokens.append(f"MISSING:project:{project_name}")
    else:
        token = _store_token_for_beads_dir(beads_dir)
        if token is None:
            return None
        tokens.append(f"proj:{token}")
    if not tokens:
        return None
    return "|".join(sorted(tokens))


def _derive_agent_bead_id(agent: Agent) -> str | None:
    """Infer a bead id from an agent name written by ``sase bead work``."""
    return derive_agent_bead_id_from_name(
        agent.presented_agent_name or agent.agent_name
    )


def cached_bead_display(agent: Agent) -> str | None | object:
    """Return the cached bead display state for *agent*.

    Returns :data:`BEAD_DISPLAY_CACHE_MISS` when the candidate has not been
    checked, ``None`` when checked but not confirmed, or the display string
    when a concrete issue exists. A non-bead agent name (no candidate id)
    reports ``None`` — there is nothing to confirm.
    """
    key = _bead_display_cache_key(agent)
    if key is None:
        return None
    return _BEAD_DISPLAY_CACHE.get(key)


def agent_has_confirmed_bead(agent: Agent) -> bool:
    """Return whether *agent* has authoritative bead identity metadata.

    Modern phase metadata is authoritative at launch; legacy candidates still
    require a confirmed cached display. This is an O(1), memory-only check.
    """
    if agent.phase_bead_id:
        return True
    return isinstance(cached_bead_display(agent), str)


def should_resolve_bead_display(agent: Agent) -> bool:
    """Return True when the agent's bead display is uncached or expired."""
    key = _bead_display_cache_key(agent)
    if key is None:
        return False
    return _BEAD_DISPLAY_CACHE.should_resolve(key)


def bead_display_resolution_reason(agent: Agent) -> str | None:
    """Return ``cold`` or ``ttl`` when this display candidate needs work."""
    key = _bead_display_cache_key(agent)
    return _BEAD_DISPLAY_CACHE.resolution_reason(key) if key is not None else None


def resolve_bead_display(
    agent: Agent,
    *,
    lookup_session: BeadIssueLookupSession | None = None,
) -> str | None:
    """Resolve and cache the confirmed bead display for *agent*.

    Caches ``None`` when no concrete issue exists (so the TUI renders no bead
    UI) and the display string when the issue is confirmed. This may touch
    bead stores and must only be called off the Textual event loop.
    """
    key = _bead_display_cache_key(agent)
    if key is None:
        return None

    display = format_agent_bead_display_for_name(
        agent.presented_agent_name or agent.agent_name,
        include_description=True,
        require_existing=True,
        project_name=_agent_project_name(agent),
        workspace_dir=agent.workspace_dir,
        local_only=True,
        lookup_session=lookup_session,
    )
    _BEAD_DISPLAY_CACHE.set(key, display)
    if isinstance(display, str):
        _BEAD_DISPLAY_CACHE.set_fingerprint(key, _bead_display_fingerprint(agent))
    else:
        _BEAD_DISPLAY_CACHE.set_fingerprint(key, None)
    return display


def warm_confirmed_bead_displays(
    candidates: Iterable[Agent],
    *,
    telemetry: dict[str, int] | None = None,
) -> dict[tuple[AgentType, str, str | None], bool]:
    """Resolve uncached/expired bead candidates off the event loop.

    Deduplicates the underlying bead-store lookups by cache key so each store
    is read once per warmup even when several visible rows share a candidate.
    Returns a mapping of agent identity to the new confirmed state for
    candidates whose confirmed state changed. Cold/missing candidates that
    resolve missing stay omitted, while expired confirmed candidates whose bead
    was deleted are included with ``False`` so callers patch away their glyph.
    Must only be called off the Textual event loop.
    """
    candidate_list: Iterable[Agent] = candidates
    candidate_count = 0
    if telemetry is not None:
        materialized = list(candidates)
        candidate_list = materialized
        candidate_count = len(materialized)
        telemetry["bead_display_candidates_examined"] = candidate_count
    previous_by_key: dict[BeadDisplayCacheKey, str | None | object] = {}
    resolved_by_key: dict[BeadDisplayCacheKey, str | None] = {}
    results: dict[tuple[AgentType, str, str | None], bool] = {}
    with BeadIssueLookupSession() as lookup_session:
        for agent in candidate_list:
            key = _bead_display_cache_key(agent)
            if key is None:
                continue
            if key not in resolved_by_key:
                previous = _BEAD_DISPLAY_CACHE.get(key)
                previous_by_key[key] = previous
                if isinstance(previous, str):
                    if telemetry is not None:
                        telemetry["bead_display_fingerprint_probes"] = (
                            telemetry.get("bead_display_fingerprint_probes", 0) + 1
                        )
                    current_fingerprint = _bead_display_fingerprint(agent)
                    last_fingerprint = _BEAD_DISPLAY_CACHE.fingerprint_for(key)
                    if (
                        current_fingerprint is not None
                        and current_fingerprint == last_fingerprint
                    ):
                        _BEAD_DISPLAY_CACHE.set(key, previous)
                        resolved_by_key[key] = previous
                        continue
                resolved = resolve_bead_display(
                    agent,
                    lookup_session=lookup_session,
                )
                if telemetry is not None:
                    telemetry["bead_display_heavy_resolutions"] = (
                        telemetry.get("bead_display_heavy_resolutions", 0) + 1
                    )
                resolved_by_key[key] = resolved
                if isinstance(resolved, str):
                    current_fingerprint = _bead_display_fingerprint(agent)
                    _BEAD_DISPLAY_CACHE.set_fingerprint(key, current_fingerprint)
                else:
                    _BEAD_DISPLAY_CACHE.set_fingerprint(key, None)
            previous_confirmed = isinstance(previous_by_key[key], str)
            current_confirmed = resolved_by_key[key] is not None
            if previous_confirmed != current_confirmed:
                results[agent.identity] = current_confirmed
    if telemetry is not None:
        telemetry["bead_display_changed_outcomes"] = len(results)
        telemetry["bead_display_unchanged_outcomes"] = max(
            0, candidate_count - len(results)
        )
    return results


def _agent_project_name(agent: Agent) -> str | None:
    if not agent.project_file:
        return None
    project_name = Path(agent.project_file).parent.name
    return project_name or None


def _agent_workspace_cache_key(agent: Agent) -> str | None:
    if not agent.workspace_dir:
        return None
    return os.path.normpath(os.path.expanduser(agent.workspace_dir))


def _bead_display_cache_key(agent: Agent) -> BeadDisplayCacheKey | None:
    # Modern phase workers derive their display from immutable launch metadata
    # plus validated plan frontmatter. They must never enter the generic
    # bead-confirmation lookup or visible-row warmup paths.
    if agent.phase_bead_id or agent.agent_session_role == "phase":
        return None
    bead_id = _derive_agent_bead_id(agent)
    if bead_id is None:
        return None
    return (bead_id, _agent_project_name(agent), _agent_workspace_cache_key(agent))
