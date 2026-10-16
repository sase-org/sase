"""Cached instruction-bundle pages for the Agents-tab Files deck.

Done loaders store paths on ``Agent.instruction_bundle_files``. Running
agents fill this module's cache from a worker (the detail-header
enrichment pass), so :func:`desired_file_pages` and deck availability
never do I/O.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock

from ...models.agent import Agent

_BUNDLE_CACHE_MAX = 128

_bundle_cache: OrderedDict[tuple[object, ...], tuple[str, ...]] = OrderedDict()
_bundle_cache_lock = Lock()


def _get_cached_instruction_bundle_files(agent: Agent) -> tuple[str, ...]:
    """Return cached bundle paths for *agent* without doing I/O."""
    identity = getattr(agent, "identity", None)
    if not isinstance(identity, tuple):
        return ()
    with _bundle_cache_lock:
        result = _bundle_cache.get(identity, ())
        if identity in _bundle_cache:
            _bundle_cache.move_to_end(identity)
        return result


def compute_instruction_bundle_files(agent: Agent) -> tuple[str, ...]:
    """List recorded bundle paths for *agent* and store them in the cache.

    Runs off the event loop. Failures store an empty tuple so the Files
    deck does not retry on every paint.
    """
    identity = getattr(agent, "identity", None)
    if not isinstance(identity, tuple):
        return ()
    paths: tuple[str, ...] = ()
    try:
        artifacts_dir = agent.get_artifacts_dir()
    except Exception:
        artifacts_dir = None
    if artifacts_dir:
        try:
            from sase.instructions.manifests import run_bundle_paths

            paths = run_bundle_paths(artifacts_dir)
        except Exception:
            paths = ()
    with _bundle_cache_lock:
        _bundle_cache[identity] = paths
        _bundle_cache.move_to_end(identity)
        while len(_bundle_cache) > _BUNDLE_CACHE_MAX:
            _bundle_cache.popitem(last=False)
    return paths


def instruction_bundle_pages(agent: Agent) -> list[str]:
    """Return Files-deck pages for recorded bundles without doing I/O."""
    field = list(getattr(agent, "instruction_bundle_files", None) or ())
    if field:
        return field
    return list(_get_cached_instruction_bundle_files(agent))


def clear_instruction_bundle_cache(agent: Agent | None = None) -> None:
    """Drop cached bundle paths (tests)."""
    with _bundle_cache_lock:
        if agent is None:
            _bundle_cache.clear()
            return
        identity = getattr(agent, "identity", None)
        if isinstance(identity, tuple):
            _bundle_cache.pop(identity, None)


__all__ = [
    "clear_instruction_bundle_cache",
    "compute_instruction_bundle_files",
    "instruction_bundle_pages",
]
