"""Off-thread Archive corpus probe, compile, and handle queries."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...models.agent_archive_controller import (
    ARCHIVE_CORPUS_MISSING,
    ARCHIVE_CORPUS_REBUILDING,
    ARCHIVE_CORPUS_UNREADABLE,
    ARCHIVE_CORPUS_WARM,
    ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
    ARCHIVE_REQUEST_IDLE,
    ARCHIVE_REQUEST_PREWARM,
    ArchiveLoadedWindow,
    ArchiveRequestSnapshot,
    ArchiveRevalidationTokens,
)

log = logging.getLogger(__name__)


def _archive_root(owner: Any) -> Path | None:
    """Return the injected test root or the process dismissed-bundles dir."""
    root = getattr(owner, "_archive_corpus_root", None)
    if root is not None:
        return root if isinstance(root, Path) else Path(str(root))
    try:
        from sase.ace import dismissed_agents

        return dismissed_agents.dismissed_bundles_dir()
    except Exception:
        return None


def row_identity(row: Mapping[str, Any]) -> str | None:
    """Return the stable Archive identity for one light row."""
    for key in ("name", "cl_name", "agent_name"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    archive_key = row.get("archive_key")
    if isinstance(archive_key, Mapping):
        run_id = archive_key.get("source_run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    return None


def _idle_tokens_match(
    snapshot: ArchiveRequestSnapshot,
    tokens: ArchiveRevalidationTokens,
) -> bool:
    """Return whether cheap idle tokens still match the in-flight snapshot."""
    held = snapshot.tokens
    if held is None:
        return False
    return (
        held.index_exists == tokens.index_exists
        and held.index_stat == tokens.index_stat
        and held.link_signature == tokens.link_signature
        and held.profile_digest == tokens.profile_digest
        and held.rebuilding == tokens.rebuilding
        and held.indexed_rows == tokens.indexed_rows
    )


def build_archive_result(
    owner: Any,
    snapshot: ArchiveRequestSnapshot,
) -> dict[str, Any]:
    """Probe, compile or reuse the handle, and query still-requested windows."""
    tokens = _probe_tokens(owner)
    if snapshot.kind == ARCHIVE_REQUEST_IDLE and _idle_tokens_match(snapshot, tokens):
        return {"kind": "unchanged", "tokens": tokens}

    reuse_handle = (
        snapshot.corpus is not None
        and snapshot.kind != ARCHIVE_REQUEST_PREWARM
        and _idle_tokens_match(snapshot, tokens)
    )
    facets = snapshot.link_facets
    if reuse_handle:
        corpus = snapshot.corpus
        profile = snapshot.profile
    else:
        if facets is None or _link_signature_changed(snapshot.tokens, tokens):
            facets = _load_facets(owner)
        cached = _get_corpus(owner, tokens, facets)
        if cached is None:
            return {
                "kind": "unreadable",
                "tokens": tokens,
                "facets": facets,
            }
        corpus = getattr(cached, "corpus", None)
        profile = getattr(cached, "profile", None)
    status_name, indexed_rows, error_message = _status_from_corpus(corpus, tokens)
    summary, windows, identities, count = _query_handle(corpus, profile, snapshot)
    return {
        "kind": "built",
        "tokens": tokens,
        "facets": facets,
        "corpus": corpus,
        "profile": profile,
        "status": status_name,
        "indexed_rows": indexed_rows,
        "error_message": error_message,
        "summary": summary,
        "windows": windows,
        "identities": identities,
        "count": count,
        "lookup_row": _lookup_pending(owner, corpus),
    }


def _link_signature_changed(
    held: ArchiveRevalidationTokens | None,
    tokens: ArchiveRevalidationTokens,
) -> bool:
    if held is None:
        return True
    return held.link_signature != tokens.link_signature


def _probe_tokens(owner: Any) -> ArchiveRevalidationTokens:
    probe = getattr(owner, "_archive_probe_tokens", None)
    if callable(probe):
        return probe()
    root = _archive_root(owner)
    index_exists = False
    index_stat: tuple[int, int] | None = None
    rebuilding = False
    indexed_rows = 0
    if root is not None:
        from sase.ace.dismissed_bundle_index import (
            INDEX_FILENAME,
            archive_index_exists,
            dismissed_bundle_index_progress,
        )

        index_exists = archive_index_exists(root)
        if index_exists:
            path = root / INDEX_FILENAME
            try:
                stat = path.stat()
                index_stat = (int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                index_stat = None
        progress = dismissed_bundle_index_progress(root)
        rebuilding = bool(progress.rebuilding)
        indexed_rows = int(progress.indexed_rows or 0)
    profile = _resolved_profile(owner)
    digest = str(getattr(profile, "digest", "") or "")
    return ArchiveRevalidationTokens(
        index_exists=index_exists,
        index_stat=index_stat,
        link_signature=_cheap_link_signature(),
        profile_digest=digest,
        rebuilding=rebuilding,
        indexed_rows=indexed_rows,
    )


def _cheap_link_signature() -> tuple[tuple[str, int | None, int | None], ...]:
    from sase.core.paths import sase_projects_dir
    from sase.sdd.artifact_link_store import artifact_link_aggregate_path

    try:
        keys = tuple(
            sorted(path.name for path in sase_projects_dir().iterdir() if path.is_dir())
        )
    except OSError:
        keys = ()
    signatures: list[tuple[str, int | None, int | None]] = []
    for key in keys:
        path = artifact_link_aggregate_path(key)
        try:
            stat = path.stat()
            signatures.append((key, int(stat.st_mtime_ns), int(stat.st_size)))
        except OSError:
            signatures.append((key, None, None))
    return tuple(signatures)


def _resolved_profile(owner: Any) -> Any:
    profile = getattr(owner, "_archive_profile", None)
    if profile is not None:
        return profile
    from sase.core.agent_archive_facade import agents_archive_profile

    return agents_archive_profile()


def _load_facets(owner: Any) -> Mapping[str, Any]:
    loader = getattr(owner, "_archive_load_facets", None)
    if callable(loader):
        loaded = loader()
        return loaded if isinstance(loaded, Mapping) else {}
    from sase.ace.tui.relations.artifact_links import load_artifact_links_snapshot
    from sase.agents.catalog import (
        build_agent_catalog_link_facets,
        build_agent_catalog_snapshot,
    )

    snapshot = build_agent_catalog_snapshot()
    link_snapshot = load_artifact_links_snapshot(None)
    return build_agent_catalog_link_facets(snapshot.rows, link_snapshot.rows)


def _get_corpus(
    owner: Any,
    tokens: ArchiveRevalidationTokens,
    facets: Mapping[str, Any] | None,
) -> Any:
    from sase.ace.dismissed_bundle_index._models import DismissedBundleIndexProgress

    getter = getattr(owner, "_archive_get_corpus", None)
    if getter is None:
        from sase.core.agent_archive_corpus_cache import get_agent_archive_corpus

        getter = get_agent_archive_corpus
    progress = DismissedBundleIndexProgress(
        rebuilding=tokens.rebuilding,
        indexed_rows=tokens.indexed_rows,
    )
    try:
        return getter(
            root=_archive_root(owner),
            progress=progress,
            link_facets=facets if facets is not None else {},
            profile=_resolved_profile(owner),
        )
    except Exception:
        log.debug("archive corpus compile failed", exc_info=True)
        return None


def _status_from_corpus(
    corpus: Any,
    tokens: ArchiveRevalidationTokens,
) -> tuple[str, int, str | None]:
    if tokens.index_exists and tokens.index_stat is None and not tokens.rebuilding:
        return (
            ARCHIVE_CORPUS_UNREADABLE,
            tokens.indexed_rows,
            ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
        )
    raw = str(getattr(corpus, "status", "") or "")
    indexed_rows = tokens.indexed_rows
    wire_status = getattr(corpus, "wire", None)
    if isinstance(wire_status, Mapping):
        nested = wire_status.get("status")
        if isinstance(nested, Mapping):
            indexed_rows = int(nested.get("indexed_rows", indexed_rows) or indexed_rows)
            raw = str(nested.get("status") or raw)
    if raw == "missing" or (not tokens.index_exists and not tokens.rebuilding):
        return (
            ARCHIVE_CORPUS_MISSING,
            indexed_rows,
            ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
        )
    if raw == "rebuilding" or tokens.rebuilding:
        return ARCHIVE_CORPUS_REBUILDING, indexed_rows, None
    if raw in {"unsupported", "unreadable", "error"}:
        return (
            ARCHIVE_CORPUS_UNREADABLE,
            indexed_rows,
            ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
        )
    return ARCHIVE_CORPUS_WARM, indexed_rows, None


def _query_handle(
    corpus: Any,
    profile: Any,
    snapshot: ArchiveRequestSnapshot,
) -> tuple[
    Mapping[str, Any] | None,
    tuple[ArchiveLoadedWindow, ...],
    tuple[str, ...],
    int,
]:
    if corpus is None:
        return None, (), (), 0
    summary: Mapping[str, Any] | None = None
    try:
        summary = corpus.summary(
            snapshot.query, group_by=snapshot.grouping, profile=profile
        )
    except Exception:
        log.debug("archive corpus summary failed", exc_info=True)
        summary = None
    windows: list[ArchiveLoadedWindow] = []
    identities: list[str] = []
    for window in snapshot.windows:
        try:
            payload = corpus.rows(
                snapshot.query,
                group_by=snapshot.grouping,
                group_key=window.group_key,
                offset=window.offset,
                limit=window.limit,
                expanded_container_keys=snapshot.expanded_containers,
                profile=profile,
            )
        except Exception:
            log.debug("archive corpus rows failed", exc_info=True)
            continue
        rows = tuple(
            dict(row) for row in payload.get("rows", ()) if isinstance(row, Mapping)
        )
        windows.append(
            ArchiveLoadedWindow(
                group_key=window.group_key,
                offset=window.offset,
                limit=window.limit,
                rows=rows,
                total=int(payload.get("total", len(rows)) or 0),
            )
        )
        for row in rows:
            identity = row_identity(row)
            if identity is not None:
                identities.append(identity)
    count = 0
    try:
        count = int(corpus.count(snapshot.query, profile=profile))
    except Exception:
        if isinstance(summary, Mapping):
            count = int(summary.get("total", 0) or 0)
    return summary, tuple(windows), tuple(identities), count


def _lookup_pending(owner: Any, corpus: Any) -> Mapping[str, Any] | None:
    view = getattr(owner, "_agents_archive_view", None)
    archive = getattr(view, "archive", None)
    name = getattr(archive, "pending_exact_name", None)
    if not name or corpus is None:
        return None
    try:
        row = corpus.lookup(str(name))
    except Exception:
        return None
    return dict(row) if isinstance(row, Mapping) else None


__all__ = [
    "build_archive_result",
    "row_identity",
]
