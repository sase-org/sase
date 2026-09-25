"""Completion sources for the ``:`` Command Line popup.

Priority order per the epic plan:

1. The TUI's in-memory entities (agents, procs, projects, Patches):
   instant, fresh, and read from app state without I/O.
2. Static spec data (subcommands, options, choices): ranked in Rust.
3. ``candidates_for`` providers in a debounced worker, cached per
   ``(kind, project)`` with a short per-kind TTL (volatile kinds such as
   ``pending_plan`` expire sooner). The provider limit is applied before
   ranking, so callers fetch wide and rank in Rust.
4. Paths: scanned by the panel's debounced worker and cached per directory.

All readers here are defensive: missing or half-initialized app state
yields empty lists rather than raising on the keystroke path.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Literal

#: Debounce delay before a provider fetch starts, in seconds.
PROVIDER_DEBOUNCE_SECONDS = 0.08
#: How long a provider result stays fresh, in seconds, unless the kind is
#: volatile (see ``VOLATILE_KIND_TTL_SECONDS``).
PROVIDER_CACHE_TTL_SECONDS = 15.0
#: Width of the provider fetch: rank in Rust, so fetch wide.
PROVIDER_FETCH_LIMIT = 2000
#: A directory scan is intentionally much shorter lived than provider rows.
PATH_CACHE_TTL_SECONDS = 1.0
#: Keep one slow directory from turning the completion menu into an unbounded list.
PATH_COMPLETION_LIMIT = 200
#: In-memory entity kinds served synchronously from app state.
IN_MEMORY_VALUE_KINDS = frozenset({"agent", "proc", "project", "patch"})

__all__ = [
    "IN_MEMORY_VALUE_KINDS",
    "collect_dynamic_candidates",
    "path_candidates",
    "path_completion_request",
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
    """Read the observer's most recently delivered projection, never its store."""
    try:
        effective = getattr(app, "_effective_proc_projection", None)
        projection = (
            effective()
            if callable(effective)
            else getattr(app, "_proc_projection", None)
        )
        rows = list(getattr(projection, "rows", ()) or ())
    except Exception:  # noqa: BLE001 - a half-initialized app has no projection.
        return []
    candidates: list[_SourceCandidate] = []
    for proc in rows:
        proc_id = _text(getattr(proc, "proc_id", None) or getattr(proc, "id", None))
        if not proc_id:
            continue
        label = _text(
            getattr(proc, "label", None)
            or getattr(proc, "display_name", None)
            or getattr(proc, "command", None)
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
    """Return project names already represented by the live ACE state."""
    projects: list[Any] = []
    for attr in ("_projects", "projects", "_project_names"):
        value = getattr(app, attr, None)
        if value:
            try:
                projects.extend(value)
            except TypeError:
                pass
    for attr in ("_agents_with_children", "_agents"):
        value = getattr(app, attr, None) or ()
        try:
            projects.extend(value)
        except TypeError:
            continue
    current = getattr(app, "_current_project", None)
    if current is not None:
        projects.append(current)
    candidates: list[_SourceCandidate] = []
    for project in projects:
        name = _text(
            project
            if isinstance(project, str)
            else getattr(project, "project_name", None)
            or getattr(project, "project_display_name", None)
            or getattr(project, "name", None)
            or getattr(project, "key", None)
        )
        if not name and not isinstance(project, str):
            project_file = _text(getattr(project, "project_file", None))
            if project_file:
                name = Path(project_file).parent.name
        if name:
            candidate = _SourceCandidate(value=name, badge="project", source="tui")
            if candidate not in candidates:
                candidates.append(candidate)
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


def needs_provider_fetch(value_kind: str | None, app: Any | None = None) -> bool:
    """Return True when a slot needs its debounced provider/scan fallback.

    Entity readers are authoritative only while they have live rows.  Empty or
    unavailable app state must not turn a valid command slot into a dead end.
    ``app=None`` retains the cheap classification used by non-UI callers.
    """
    if not value_kind:
        return False
    if value_kind not in IN_MEMORY_VALUE_KINDS:
        return True
    return app is not None and not _in_memory_candidates(app, value_kind)


def collect_dynamic_candidates(
    app: Any,
    value_kind: str,
    project: str | None,
    cache: ProviderCache,
    *,
    source_key: str | None = None,
) -> list[dict[str, Any]]:
    """Merge in-memory entity sources with fresh provider cache entries.

    Returns dynamic-candidate dicts ready for ``complete(dynamic=…)``:
    instant TUI entities first, then the cached provider rows for the
    slot kind (provider fetches happen in the screen's debounced worker).
    """
    dynamic = [
        candidate.to_dynamic() for candidate in _in_memory_candidates(app, value_kind)
    ]
    cached = cache.cached(value_kind, project, source_key=source_key)
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
        try:
            from sase.plan_names import plan_name

            plan_path = getattr(agent, "plan_path", None)
            if plan_path:
                _push(plan_name(plan_path))
        except Exception:  # noqa: BLE001 - plan metadata is optional.
            pass
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


@dataclass(frozen=True, slots=True)
class PathCompletionRequest:
    """The pure UI-thread result used to scan one path directory off-thread."""

    scan_directory: str
    display_prefix: str
    source_key: str


def path_completion_request(prefix: str, cwd: str) -> PathCompletionRequest:
    """Resolve a typed path to its scan directory without touching the disk."""
    typed = prefix or ""
    separator = "/"
    if typed.endswith(separator):
        display_prefix = typed
    else:
        parent, _name = (
            typed.rsplit(separator, 1) if separator in typed else ("", typed)
        )
        display_prefix = f"{parent}{separator}" if parent else ""
    scan_input = display_prefix or "."
    expanded = os.path.expanduser(scan_input)
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd or ".", expanded)
    # Keep this transformation lexical: even ``Path.resolve(strict=False)``
    # can touch the filesystem, and this function runs for every keypress.
    scan_directory = os.path.abspath(os.path.normpath(expanded))
    return PathCompletionRequest(
        scan_directory=scan_directory,
        display_prefix=display_prefix,
        source_key=f"path:{scan_directory}:{display_prefix}",
    )


def path_candidates(
    request: PathCompletionRequest,
    *,
    directories_only: bool,
    limit: int = PATH_COMPLETION_LIMIT,
) -> list[dict[str, Any]]:
    """Scan exactly one directory for completion rows (worker-thread only)."""
    rows: list[tuple[str, bool]] = []
    # ``os.scandir`` is deliberately below the worker boundary in
    # ``_provider_fetch_task``.  Do not call this helper from a key handler.
    try:
        with os.scandir(request.scan_directory) as entries:
            for entry in entries:
                name = entry.name
                if name.startswith("."):
                    continue
                try:
                    is_directory = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if directories_only and not is_directory:
                    continue
                rows.append((name, is_directory))
    except OSError:
        return []
    rows.sort(key=lambda row: (not row[1], row[0].casefold()))
    return [
        {
            "value": f"{request.display_prefix}{name}{'/' if is_directory else ''}",
            "badge": "dir" if is_directory else "path",
            "source": "path",
        }
        for name, is_directory in rows[: max(0, limit)]
    ]


#: Outcome of one provider fetch: rows found, nothing found, or a failure.
ProviderHealth = Literal["ok", "empty", "failed"]


@dataclass
class _ProviderEntry:
    expires_at: float = 0.0
    items: list[dict[str, Any]] = field(default_factory=list)
    health: ProviderHealth = "ok"


def _kind_ttl_seconds(kind: str, default: float) -> float:
    """Return the freshness window for *kind*, honoring volatile kinds."""
    if kind in {"path", "dir"}:
        return PATH_CACHE_TTL_SECONDS
    from sase.completion.kinds import VOLATILE_KIND_TTL_SECONDS, ValueKind

    try:
        return float(VOLATILE_KIND_TTL_SECONDS.get(ValueKind(kind), default))
    except ValueError:  # Not a catalog kind: keep the default window.
        return default


class ProviderCache:
    """Debounced, last-wins provider cache keyed by ``(kind, project, source)``.

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
        self._entries: dict[tuple[str, str | None, str | None], _ProviderEntry] = {}
        self._generation = 0

    def next_generation(self) -> int:
        """Advance the keystroke generation and return the new token."""
        self._generation += 1
        return self._generation

    def is_current(self, generation: int) -> bool:
        """Return True when *generation* is still the latest keystroke."""
        return generation == self._generation

    def cached(
        self, kind: str, project: str | None, *, source_key: str | None = None
    ) -> list[dict[str, Any]] | None:
        """Return the cached items for this slot source, if still fresh."""
        entry = self._fresh_entry(kind, project, source_key=source_key)
        if entry is None:
            return None
        return list(entry.items)

    def health(
        self, kind: str, project: str | None, *, source_key: str | None = None
    ) -> ProviderHealth | None:
        """Return the fresh entry's fetch outcome, or ``None`` when uncached."""
        entry = self._fresh_entry(kind, project, source_key=source_key)
        return None if entry is None else entry.health

    def commit(
        self,
        generation: int,
        kind: str,
        project: str | None,
        items: list[dict[str, Any]],
        *,
        source_key: str | None = None,
    ) -> bool:
        """Store a worker result; False means it was stale and dropped."""
        if not self.is_current(generation):
            return False
        self._store(
            kind, project, items, "ok" if items else "empty", source_key=source_key
        )
        return True

    def note_unavailable(
        self, kind: str, project: str | None, *, source_key: str | None = None
    ) -> None:
        """Cache a failed fetch so a failing provider does not spin."""
        self._store(kind, project, [], "failed", source_key=source_key)

    def invalidate(self) -> None:
        """Forget every entry (a finished command may have changed them)."""
        self._entries.clear()

    def _fresh_entry(
        self, kind: str, project: str | None, *, source_key: str | None = None
    ) -> _ProviderEntry | None:
        entry = self._entries.get((kind, project, source_key))
        if entry is None or entry.expires_at < self._clock():
            return None
        return entry

    def _store(
        self,
        kind: str,
        project: str | None,
        items: list[dict[str, Any]],
        health: ProviderHealth,
        *,
        source_key: str | None = None,
    ) -> None:
        self._entries[(kind, project, source_key)] = _ProviderEntry(
            expires_at=self._clock() + _kind_ttl_seconds(kind, self._ttl_seconds),
            items=list(items),
            health=health,
        )
