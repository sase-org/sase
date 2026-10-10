"""Process-wide shared archive corpus cache for the TUI and the CLI.

One compiled corpus answers "which archived runs match, in what order,
grouped how" for both frontends. The cache key is the ``(index signature,
link-facet signature, agents-archive profile digest)`` triple, so a changed
index, changed artifact links, or changed query dialect always rebuilds.

The cache is lazy: importing this module builds nothing, and nothing here
runs as a side effect of inbox startup. Callers must call
:func:`get_agent_archive_corpus` off the Textual event loop (the TUI wraps
it in :func:`asyncio.to_thread`); the compile itself runs on a short-lived
worker thread while the Rust binding releases the GIL. When the key changes
while a worker runs, the stale worker's result is dropped and the newest
build wins.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.core.agent_archive_facade import (
    AgentArchiveCorpus,
    agents_archive_profile,
    compile_agent_archive_corpus,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sase.ace.dismissed_bundle_index._models import (
        DismissedBundleIndexProgress,
    )
    from sase.ace.query_profile import CompiledQueryProfile


@dataclass(frozen=True, slots=True)
class AgentArchiveCorpusCacheKey:
    """Exact cache key for one compiled archive corpus."""

    index_signature: tuple[int, int, int, int] | None
    link_facet_signature: str
    profile_digest: str


@dataclass(frozen=True, slots=True)
class CachedAgentArchiveCorpus:
    """One cached corpus plus the profile its key was built from."""

    key: AgentArchiveCorpusCacheKey
    corpus: AgentArchiveCorpus
    profile: CompiledQueryProfile


_LOCK = threading.Lock()
_CACHED: CachedAgentArchiveCorpus | None = None
_GENERATION = 0


def link_facet_signature(link_facets: Mapping[str, Any]) -> str:
    """Return a stable digest for one link-facet mapping."""
    canonical = {
        str(name): {
            "relations": sorted(
                str(value) for value in _facet_values(facets, "relations")
            ),
            "artifacts": sorted(
                str(value) for value in _facet_values(facets, "artifacts")
            ),
            "count": _facet_count(facets),
        }
        for name, facets in link_facets.items()
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def archive_corpus_cache_key(
    *,
    index_signature: tuple[int, int, int, int] | None,
    link_facets: Mapping[str, Any],
    profile_digest: str,
) -> AgentArchiveCorpusCacheKey:
    """Build the exact cache key for one corpus build's inputs."""
    return AgentArchiveCorpusCacheKey(
        index_signature=index_signature,
        link_facet_signature=link_facet_signature(link_facets),
        profile_digest=profile_digest,
    )


def get_agent_archive_corpus(
    *,
    root: Path | str | None = None,
    progress: DismissedBundleIndexProgress | None = None,
    link_facets: Mapping[str, Any] | None = None,
    profile: CompiledQueryProfile | None = None,
) -> CachedAgentArchiveCorpus:
    """Return the cached corpus for *root*, rebuilding when the key changed.

    Must be called off the Textual event loop: index probing, link-facet
    resolution, and the corpus compile all run here (the compile itself on
    a worker thread). *progress* is the caller's already-probed
    :class:`DismissedBundleIndexProgress`; when omitted it is probed here.
    *link_facets* maps agent names to
    :class:`~sase.agents.catalog.AgentCatalogLinkFacets` (or plain
    ``relations`` / ``artifacts`` / ``count`` mappings); when omitted the
    facets are built here with
    :func:`~sase.agents.catalog.build_agent_catalog_link_facets` over the
    current catalog snapshot and link snapshot.
    """
    global _CACHED
    resolved_profile = profile if profile is not None else agents_archive_profile()
    if link_facets is not None:
        fast_key = archive_corpus_cache_key(
            index_signature=_probe_index_signature(root),
            link_facets=link_facets,
            profile_digest=resolved_profile.digest,
        )
        with _LOCK:
            if _CACHED is not None and _CACHED.key == fast_key:
                return _CACHED
    with _LOCK:
        generation = _bump_generation_locked()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="archive-corpus") as pool:
        built = pool.submit(
            _build_snapshot, root, progress, link_facets, resolved_profile
        ).result()
    with _LOCK:
        if _CACHED is not None and generation != _GENERATION:
            return _CACHED
        _CACHED = built
        return built


def invalidate_agent_archive_corpus_cache() -> None:
    """Drop the cached corpus, forcing the next accessor call to rebuild."""
    global _CACHED
    with _LOCK:
        _CACHED = None
        _bump_generation_locked()


def _bump_generation_locked() -> int:
    global _GENERATION
    _GENERATION += 1
    return _GENERATION


def _build_snapshot(
    root: Path | str | None,
    progress: DismissedBundleIndexProgress | None,
    link_facets: Mapping[str, Any] | None,
    profile: CompiledQueryProfile,
) -> CachedAgentArchiveCorpus:
    from sase.ace.dismissed_bundle_index import index_signature

    resolved_root = _resolve_root(root)
    resolved_progress = (
        progress if progress is not None else _probe_progress(resolved_root)
    )
    resolved_facets = (
        link_facets if link_facets is not None else _build_fallback_facets()
    )
    key = archive_corpus_cache_key(
        index_signature=index_signature(resolved_root),
        link_facets=resolved_facets,
        profile_digest=profile.digest,
    )
    with _LOCK:
        if _CACHED is not None and _CACHED.key == key:
            return _CACHED
    corpus = compile_agent_archive_corpus(
        root=resolved_root,
        index_status=_index_status_wire(resolved_root, resolved_progress),
        link_facets=resolved_facets,
    )
    return CachedAgentArchiveCorpus(key=key, corpus=corpus, profile=profile)


def _resolve_root(root: Path | str | None) -> Path:
    from pathlib import Path as _Path

    if root is not None:
        return root if isinstance(root, _Path) else _Path(str(root))
    from sase.ace import dismissed_agents

    return dismissed_agents.dismissed_bundles_dir()


def _probe_index_signature(
    root: Path | str | None,
) -> tuple[int, int, int, int] | None:
    from sase.ace.dismissed_bundle_index import index_signature

    return index_signature(_resolve_root(root))


def _probe_progress(root: Path) -> DismissedBundleIndexProgress:
    from sase.ace.dismissed_bundle_index import dismissed_bundle_index_progress

    return dismissed_bundle_index_progress(root)


def _index_status_wire(
    root: Path,
    progress: DismissedBundleIndexProgress,
) -> dict[str, Any]:
    from sase.ace.dismissed_bundle_index import archive_index_exists

    if not archive_index_exists(root):
        return {"status": "missing"}
    if progress.rebuilding:
        return {
            "status": "rebuilding",
            "indexed_rows": int(progress.indexed_rows or 0),
        }
    return {"status": "ok"}


def _build_fallback_facets() -> Mapping[str, Any]:
    from sase.ace.tui.relations.artifact_links import load_artifact_links_snapshot
    from sase.agents.catalog import (
        build_agent_catalog_link_facets,
        build_agent_catalog_snapshot,
    )

    snapshot = build_agent_catalog_snapshot()
    link_snapshot = load_artifact_links_snapshot(None)
    return build_agent_catalog_link_facets(snapshot.rows, link_snapshot.rows)


def _facet_values(facets: Any, field: str) -> tuple[Any, ...]:
    if isinstance(facets, Mapping):
        values = facets.get(field, ())
    else:
        values = getattr(facets, field, ())
    if isinstance(values, (str, bytes)):
        return (values,)
    try:
        return tuple(values)
    except TypeError:
        return ()


def _facet_count(facets: Any) -> int:
    if isinstance(facets, Mapping):
        return int(facets.get("count", 0))
    return int(getattr(facets, "count", 0))


__all__ = [
    "AgentArchiveCorpusCacheKey",
    "CachedAgentArchiveCorpus",
    "archive_corpus_cache_key",
    "get_agent_archive_corpus",
    "invalidate_agent_archive_corpus_cache",
    "link_facet_signature",
]
