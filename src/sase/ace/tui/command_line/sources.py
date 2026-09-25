"""Completion sources for the ``:`` Command Line popup.

Priority order per the epic plan:

1. The TUI's in-memory entities (agents, procs, projects, Patches):
   instant, fresh, and read from app state without I/O.
2. Static spec data (subcommands, options, choices): ranked in Rust.
3. ``candidates_for`` providers in a debounced worker, cached per
   ``(kind, project)`` with a short per-kind TTL (volatile kinds such as
   ``pending_plan`` expire sooner). The provider limit is applied before
   ranking, so callers fetch wide and rank in Rust.
4. Paths: completed natively by the shell slots, never via a provider.

All readers here are defensive: missing or half-initialized app state
yields empty lists rather than raising on the keystroke path.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

#: Debounce delay before a provider fetch starts, in seconds.
PROVIDER_DEBOUNCE_SECONDS = 0.08
#: How long a provider result stays fresh, in seconds, unless the kind is
#: volatile (see ``VOLATILE_KIND_TTL_SECONDS``).
PROVIDER_CACHE_TTL_SECONDS = 15.0
#: Width of the provider fetch: rank in Rust, so fetch wide.
PROVIDER_FETCH_LIMIT = 2000
#: Value kinds completed natively; they never reach a provider.
NATIVE_VALUE_KINDS = frozenset({"path", "dir"})
#: In-memory entity kinds served synchronously from app state.
IN_MEMORY_VALUE_KINDS = frozenset({"agent", "proc", "project", "patch"})

__all__ = [
    "NATIVE_VALUE_KINDS",
    "IN_MEMORY_VALUE_KINDS",
    "collect_dynamic_candidates",
    "PROVIDER_CACHE_TTL_SECONDS",
    "PROVIDER_DEBOUNCE_SECONDS",
    "PROVIDER_FETCH_LIMIT",
    "ProviderCache",
    "needs_provider_fetch",
    "selected_entity_values",
]


@dataclass(frozen=True, slots=True)
class _SourceCandidate:
    """One caller-supplied dynamic candidate for the Rust ranker."""

    value: str
    display: str | None = None
    description: str | None = None
    badge: str | None = None
    source: str | None = None

    def to_dynamic(self) -> dict[str, Any]:
        """Render as a dynamic-candidate dict for ``complete()``."""
        payload: dict[str, Any] = {"value": self.value}
        if self.display is not None:
            payload["display"] = self.display
        if self.description is not None:
            payload["description"] = self.description
        if self.badge is not None:
            payload["badge"] = self.badge
        if self.source is not None:
            payload["source"] = self.source
        return payload


def _text(value: Any) -> str:
    return str(value) if value is not None else ""


def _agent_candidates(app: Any) -> list[_SourceCandidate]:
    agents = getattr(app, "_agents", None) or getattr(app, "agents", None) or []
    candidates: list[_SourceCandidate] = []
    try:
        rows = list(agents)
    except TypeError:
        return []
    for agent in rows:
        name = _text(getattr(agent, "agent_name", None) or getattr(agent, "name", None))
        if not name:
            continue
        status = _text(getattr(agent, "status", None))
        candidates.append(
            _SourceCandidate(
                value=name,
                description=status,
                badge="agent",
                source="tui",
            )
        )
    return candidates


def _proc_candidates(app: Any) -> list[_SourceCandidate]:
    observer = getattr(app, "_proc_observer", None)
    rows: list[Any] = []
    for accessor in ("visible_procs", "procs", "list_procs"):
        candidate = getattr(observer, accessor, None)
        if callable(candidate):
            try:
                rows = list(candidate())
                break
            except Exception:  # noqa: BLE001 - proc listing is best effort.
                continue
        elif isinstance(candidate, (list, tuple)):
            rows = list(candidate)
            break
    candidates: list[_SourceCandidate] = []
    for proc in rows:
        proc_id = _text(getattr(proc, "proc_id", None) or getattr(proc, "id", None))
        if not proc_id:
            continue
        label = _text(
            getattr(proc, "display_name", None) or getattr(proc, "command", None)
        )
        candidates.append(
            _SourceCandidate(
                value=proc_id,
                display=proc_id if not label else None,
                description=label,
                badge="proc",
                source="tui",
            )
        )
    return candidates


def _project_candidates(app: Any) -> list[_SourceCandidate]:
    projects = (
        getattr(app, "_projects", None)
        or getattr(app, "projects", None)
        or getattr(app, "_project_names", None)
        or []
    )
    candidates: list[_SourceCandidate] = []
    try:
        rows = list(projects)
    except TypeError:
        return []
    for project in rows:
        name = _text(
            project
            if isinstance(project, str)
            else getattr(project, "project_name", None)
            or getattr(project, "name", None)
        )
        if name:
            candidates.append(
                _SourceCandidate(value=name, badge="project", source="tui")
            )
    return candidates


def _patch_candidates(app: Any) -> list[_SourceCandidate]:
    patches = getattr(app, "patches", None) or getattr(app, "changespecs", None) or []
    candidates: list[_SourceCandidate] = []
    try:
        rows = list(patches)
    except TypeError:
        return []
    for patch in rows:
        if isinstance(patch, str):
            if patch:
                candidates.append(
                    _SourceCandidate(value=patch, badge="patch", source="tui")
                )
            continue
        patch_id = _text(
            getattr(patch, "patch_id", None)
            or getattr(patch, "id", None)
            or getattr(patch, "name", None)
        )
        if not patch_id:
            continue
        title = _text(
            getattr(patch, "title", None) or getattr(patch, "description", None)
        )
        candidates.append(
            _SourceCandidate(
                value=patch_id,
                description=title,
                badge="patch",
                source="tui",
            )
        )
    return candidates


_IN_MEMORY_READERS = {
    "agent": _agent_candidates,
    "proc": _proc_candidates,
    "project": _project_candidates,
    "patch": _patch_candidates,
}


def _in_memory_candidates(app: Any, kind: str) -> list[_SourceCandidate]:
    """Return instant in-memory candidates for entity *kind*, if any."""
    reader = _IN_MEMORY_READERS.get(kind)
    if reader is None:
        return []
    try:
        return reader(app)
    except Exception:  # noqa: BLE001 - keystroke path never raises.
        return []


def needs_provider_fetch(value_kind: str | None) -> bool:
    """Return True when *value_kind* needs a debounced provider fetch."""
    if not value_kind:
        return False
    if value_kind in NATIVE_VALUE_KINDS:
        return False
    return value_kind not in IN_MEMORY_VALUE_KINDS


def collect_dynamic_candidates(
    app: Any,
    value_kind: str,
    project: str | None,
    cache: ProviderCache,
) -> list[dict[str, Any]]:
    """Merge in-memory entity sources with fresh provider cache entries.

    Returns dynamic-candidate dicts ready for ``complete(dynamic=…)``:
    instant TUI entities first, then the cached provider rows for the
    slot kind (provider fetches happen in the screen's debounced worker).
    """
    dynamic = [
        candidate.to_dynamic() for candidate in _in_memory_candidates(app, value_kind)
    ]
    if needs_provider_fetch(value_kind):
        cached = cache.cached(value_kind, project)
        if cached is not None:
            dynamic.extend(cached)
    return dynamic


def selected_entity_values(app: Any) -> list[str]:
    """Return the selected entity (and linked-bead) values, selection first.

    The selected agent/Patch/axe item and the bead linked through it rank
    first in the popup and are marked ``sel``. Read through
    ``extract_command_context`` so the palette and the panel agree on
    what "selected" means; every step is defensive.
    """
    values: list[str] = []

    def _push(value: Any) -> None:
        text = _text(value).strip()
        if text and text not in values:
            values.append(text)

    try:
        from sase.ace.tui.commands.context import extract_command_context

        context = extract_command_context(app)
    except Exception:  # noqa: BLE001 - selection is best effort.
        return values
    agent = getattr(context, "agent", None)
    if agent is not None:
        agent_name = getattr(agent, "agent_name", None) or getattr(agent, "name", None)
        _push(agent_name)
        for linked in (
            getattr(agent, "phase_bead_id", None),
            getattr(agent, "bead_id", None),
        ):
            _push(linked)
        try:
            from sase.agent.bead_display import derive_agent_bead_id_from_name

            _push(derive_agent_bead_id_from_name(_text(agent_name) or None))
        except Exception:  # noqa: BLE001 - bead link is best effort.
            pass
    patch = getattr(context, "patch", None)
    if patch is not None:
        _push(
            getattr(patch, "patch_id", None)
            or getattr(patch, "id", None)
            or getattr(patch, "name", None)
        )
        _push(getattr(patch, "bead_id", None))
    axe_item = getattr(context, "axe_item", None)
    if axe_item is not None:
        _push(
            getattr(axe_item, "agent_session", None)
            or getattr(axe_item, "name", None)
            or getattr(axe_item, "id", None)
        )
    return values


#: Outcome of one provider fetch: rows found, nothing found, or a failure.
ProviderHealth = Literal["ok", "empty", "failed"]


@dataclass
class _ProviderEntry:
    expires_at: float = 0.0
    items: list[dict[str, Any]] = field(default_factory=list)
    health: ProviderHealth = "ok"


def _kind_ttl_seconds(kind: str, default: float) -> float:
    """Return the freshness window for *kind*, honoring volatile kinds."""
    from sase.completion.kinds import VOLATILE_KIND_TTL_SECONDS, ValueKind

    try:
        return float(VOLATILE_KIND_TTL_SECONDS.get(ValueKind(kind), default))
    except ValueError:  # Not a catalog kind: keep the default window.
        return default


class ProviderCache:
    """Debounced, last-wins provider cache keyed by ``(kind, project)``.

    The screen bumps :meth:`next_generation` whenever it schedules a fetch
    and hands the worker its generation. :meth:`commit` stores the result
    only when the generation is still the latest, so a slow fetch for a
    stale line is dropped instead of flashing over fresher results. Each
    entry lives for its kind's TTL (``VOLATILE_KIND_TTL_SECONDS`` overrides
    the default) and remembers whether the fetch found rows, found none, or
    failed so the footer can tell those apart.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = PROVIDER_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: dict[tuple[str, str | None], _ProviderEntry] = {}
        self._generation = 0

    def next_generation(self) -> int:
        """Advance the keystroke generation and return the new token."""
        self._generation += 1
        return self._generation

    def is_current(self, generation: int) -> bool:
        """Return True when *generation* is still the latest keystroke."""
        return generation == self._generation

    def cached(self, kind: str, project: str | None) -> list[dict[str, Any]] | None:
        """Return the cached items for ``(kind, project)``, if still fresh."""
        entry = self._fresh_entry(kind, project)
        if entry is None:
            return None
        return list(entry.items)

    def health(self, kind: str, project: str | None) -> ProviderHealth | None:
        """Return the fresh entry's fetch outcome, or ``None`` when uncached."""
        entry = self._fresh_entry(kind, project)
        return None if entry is None else entry.health

    def commit(
        self,
        generation: int,
        kind: str,
        project: str | None,
        items: list[dict[str, Any]],
    ) -> bool:
        """Store a worker result; False means it was stale and dropped."""
        if not self.is_current(generation):
            return False
        self._store(kind, project, items, "ok" if items else "empty")
        return True

    def note_unavailable(self, kind: str, project: str | None) -> None:
        """Cache a failed fetch so a failing provider does not spin."""
        self._store(kind, project, [], "failed")

    def invalidate(self) -> None:
        """Forget every entry (a finished command may have changed them)."""
        self._entries.clear()

    def _fresh_entry(self, kind: str, project: str | None) -> _ProviderEntry | None:
        entry = self._entries.get((kind, project))
        if entry is None or entry.expires_at < self._clock():
            return None
        return entry

    def _store(
        self,
        kind: str,
        project: str | None,
        items: list[dict[str, Any]],
        health: ProviderHealth,
    ) -> None:
        self._entries[(kind, project)] = _ProviderEntry(
            expires_at=self._clock() + _kind_ttl_seconds(kind, self._ttl_seconds),
            items=list(items),
            health=health,
        )
