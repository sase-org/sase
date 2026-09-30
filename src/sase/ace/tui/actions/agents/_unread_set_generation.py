"""Unread-set generation and generation-keyed jump/footer caches.

Phase ``unread-jump-fast-path`` (epic ``sase-1d7``): the unread jump
candidate list and the footer probe are keyed by cheap generations
instead of O(N) scans. The roster generation (see
:mod:`._roster_generation`) covers status and roster assignment; this
module owns the unread-set generation bumped on every
``_unread_completed_agent_ids`` mutation, plus the fold/tab/query
pieces of the jump key. Acking one identity surgically filters the
cached ordered list and advances its key so the next ``,j`` hits.
"""

from __future__ import annotations

from typing import Any

_UNREAD_GEN_ATTR = "_unread_set_generation"
_JUMP_CACHE_ATTR = "_unread_jump_candidates_cache"
_PROBE_CACHE_ATTR = "_has_unread_probe_cache"


def get_unread_set_generation(app: Any) -> int:
    """Return the unread-set generation (0 when never bumped)."""
    try:
        return int(getattr(app, _UNREAD_GEN_ATTR, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _fold_snapshot_key(app: Any) -> tuple[Any, ...]:
    """Return a cheap fold signature (empty tuple when unavailable)."""
    fold_manager = getattr(app, "_fold_manager", None)
    snapshot = getattr(fold_manager, "snapshot", None)
    if not callable(snapshot):
        return ()
    try:
        items = snapshot()
    except Exception:
        return ()
    try:
        if isinstance(items, dict):
            return tuple(sorted((k, getattr(v, "value", v)) for k, v in items.items()))
        return tuple(items)
    except Exception:
        try:
            return tuple(sorted(items))  # type: ignore[arg-type]
        except Exception:
            return ()


def _group_fold_key(app: Any) -> tuple[Any, ...]:
    """Return a cheap group-fold/panel signature for the jump cache key."""
    registry = getattr(app, "_group_fold_registry", None)
    try:
        version = int(getattr(registry, "version", 0) or 0)
    except (TypeError, ValueError):
        version = 0
    collapsed: tuple[Any, ...] = ()
    collapsed_keys = getattr(app, "_collapsed_panel_keys", None)
    if isinstance(collapsed_keys, (set, frozenset, list, tuple)):
        try:
            collapsed = tuple(sorted(collapsed_keys, key=repr))
        except Exception:
            collapsed = ()
    return (
        id(registry),
        version,
        collapsed,
        getattr(app, "_grouping_mode", None),
        bool(getattr(app, "_agent_panels_grouped", False)),
    )


def _query_key(app: Any) -> tuple[Any, ...]:
    """Return the cheap committed-query piece of the jump cache key."""
    try:
        query = getattr(app, "_agent_search_query", "") or ""
    except Exception:
        query = ""
    try:
        query_gen = int(getattr(app, "_agent_search_query_generation", 0) or 0)
    except (TypeError, ValueError):
        query_gen = 0
    return (query, query_gen)


def _tab_key(app: Any) -> str:
    """Return the active-tab scope token (empty string when unavailable)."""
    try:
        from ._tab_scope import current_agent_tab_scope_token

        return str(current_agent_tab_scope_token(app))
    except Exception:
        try:
            return str(getattr(app, "_active_agent_tab", "") or "")
        except Exception:
            return ""


def unread_jump_cache_key(app: Any) -> tuple[Any, ...]:
    """Return the cheap generation key for the unread jump candidate cache.

    Keyed by roster generation, unread-set generation plus unread length,
    fold/group/panel generations, the active tab, and the committed
    query. Object identities for the roster lists and query facades are
    O(1) guards against missed bumps. Never scans agents or builds a
    frozenset of unread ids.
    """
    from ._roster_generation import get_roster_generation

    try:
        agents = getattr(app, "_agents", None)
        agents_id = id(agents)
        try:
            agents_len = len(agents) if agents is not None else 0
        except TypeError:
            agents_len = 0
    except Exception:
        agents_id, agents_len = 0, 0
    try:
        complete = getattr(app, "_agents_with_children", None)
        complete_id = id(complete)
    except Exception:
        complete_id = 0
    try:
        unread = getattr(app, "_unread_completed_agent_ids", None)
        unread_len = len(unread) if unread is not None else 0
    except TypeError:
        unread_len = 0
    return (
        get_roster_generation(app),
        get_unread_set_generation(app),
        unread_len,
        _fold_snapshot_key(app),
        _group_fold_key(app),
        _tab_key(app),
        _query_key(app),
        agents_id,
        complete_id,
        agents_len,
        id(getattr(app, "_agents_live_query_facade", None)),
        id(getattr(app, "_agent_content_search_index", None)),
    )


def _key_without_unread(key: tuple[Any, ...]) -> tuple[Any, ...]:
    """Return *key* with the unread generation/length slots masked out."""
    if len(key) < 3:
        return key
    return (key[0],) + ("*", "*") + key[3:]


def bump_unread_set_generation(app: Any, *, removed: Any = None) -> int:
    """Bump the unread-set generation and keep the jump cache in step.

    When *removed* names acked identities and the cached jump list was
    built under the same roster/fold/tab/query, filter those identities
    out of the cached ordered list and rekey it to the new generation
    so the next ``,j`` hits. Otherwise invalidate the jump cache and
    let the next jump rebuild. Always drops the O(1) footer probe
    cache; it recomputes from ``bool(unread)`` on next read.
    """
    generation = get_unread_set_generation(app) + 1
    try:
        setattr(app, _UNREAD_GEN_ATTR, generation)
    except (AttributeError, TypeError):
        pass
    try:
        setattr(app, _PROBE_CACHE_ATTR, None)
    except (AttributeError, TypeError):
        pass
    if removed is None:
        return generation
    try:
        removed_set = set(removed)
    except TypeError:
        try:
            removed_set = {removed}
        except TypeError:
            return generation
    if not removed_set:
        return generation
    cached = getattr(app, _JUMP_CACHE_ATTR, None)
    if not isinstance(cached, tuple) or len(cached) != 2:
        return generation
    old_key, old_list = cached
    try:
        new_key = unread_jump_cache_key(app)
    except Exception:
        return generation
    try:
        same_scope = _key_without_unread(old_key) == _key_without_unread(new_key)
    except Exception:
        same_scope = False
    if not same_scope:
        try:
            setattr(app, _JUMP_CACHE_ATTR, None)
        except (AttributeError, TypeError):
            pass
        return generation
    try:
        filtered = [c for c in list(old_list) if c.identity not in removed_set]
    except Exception:
        return generation
    try:
        setattr(app, _JUMP_CACHE_ATTR, (new_key, filtered))
    except (AttributeError, TypeError):
        pass
    return generation


def note_unread_set_changed(app: Any, *, removed: Any = None) -> int:
    """Bump the unread generation after an unread-set mutation (alias)."""
    return bump_unread_set_generation(app, removed=removed)


def has_unread_probe_cache_key(app: Any) -> tuple[Any, ...]:
    """Return the cheap key for the O(1) footer unread probe."""
    from ._roster_generation import get_roster_generation

    try:
        unread = getattr(app, "_unread_completed_agent_ids", None)
        unread_len = len(unread) if unread is not None else 0
    except TypeError:
        unread_len = 0
    return (
        get_roster_generation(app),
        get_unread_set_generation(app),
        unread_len,
    )


def cached_has_unread_probe(app: Any) -> bool:
    """Return the O(1) footer probe without building jump candidates.

    ``True`` when the unread set is non-empty. Keyed by roster and
    unread generations plus unread length; recomputation is a single
    ``bool()`` so the footer never pays for candidate discovery.
    """
    key = has_unread_probe_cache_key(app)
    cached = getattr(app, _PROBE_CACHE_ATTR, None)
    if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == key:
        return bool(cached[1])
    try:
        unread = getattr(app, "_unread_completed_agent_ids", None)
        value = bool(unread)
    except Exception:
        value = False
    try:
        setattr(app, _PROBE_CACHE_ATTR, (key, value))
    except (AttributeError, TypeError):
        pass
    return value


__all__ = [
    "bump_unread_set_generation",
    "cached_has_unread_probe",
    "get_unread_set_generation",
    "has_unread_probe_cache_key",
    "note_unread_set_changed",
    "unread_jump_cache_key",
]
