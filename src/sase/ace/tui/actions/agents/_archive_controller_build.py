"""Off-thread Archive corpus probe, compile, and handle queries."""

from __future__ import annotations

import logging
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter_ns
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
from ...models.agent_archive_list import archive_row_key
from ...util.trace import is_enabled as tui_trace_enabled, tui_trace

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
    """Return the stable Archive identity for one core light row."""
    return archive_row_key(row)


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


def _non_link_tokens_match(
    held: ArchiveRevalidationTokens | None,
    current: ArchiveRevalidationTokens,
) -> bool:
    if held is None:
        return False
    return (
        held.index_exists == current.index_exists
        and held.index_stat == current.index_stat
        and held.profile_digest == current.profile_digest
        and held.rebuilding == current.rebuilding
        and held.indexed_rows == current.indexed_rows
    )


def _same_link_snapshot_content(held: Any, current: Any) -> bool:
    return (
        held is not None
        and current is not None
        and getattr(held, "rows", None) == getattr(current, "rows", None)
        and getattr(held, "errors", None) == getattr(current, "errors", None)
    )


def _changed_link_project_count(held: Any, current: Any) -> int:
    old_key = getattr(held, "source_key", ()) if held is not None else ()
    new_key = getattr(current, "source_key", ()) if current is not None else ()
    old = {str(item[0]): tuple(item[1:]) for item in old_key}
    new = {str(item[0]): tuple(item[1:]) for item in new_key}
    return sum(old.get(key) != new.get(key) for key in old.keys() | new.keys())


def _catalog_link_identity_from_rows(rows: Any, identity: Any) -> str:
    owner = getattr(identity, "owner", None)
    owner_key = (
        (str(owner.username), str(owner.machine_name)) if owner is not None else None
    )
    payload = {
        "rows": sorted(
            (
                str(getattr(row, "name", "")),
                str(getattr(row, "canonical_global_name", None) or ""),
            )
            for row in rows
        ),
        "owner": owner_key,
        "sibling_machines": tuple(
            str(value) for value in getattr(identity, "sibling_machines", ())
        ),
        "known_owner_roots": tuple(
            str(value) for value in getattr(identity, "known_owner_roots", ())
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _catalog_link_identity(owner: Any) -> str | None:
    probe = getattr(owner, "_archive_catalog_link_identity", None)
    if callable(probe):
        value = probe()
        return str(value) if value is not None else None
    if callable(getattr(owner, "_archive_load_facets", None)):
        return None

    from sase.agent.names import load_name_registry
    from sase.core.agent_identity_facade import AgentIdentitySnapshot

    registry = load_name_registry()
    entries = registry.get("entries", {})
    if not isinstance(entries, Mapping):
        raise RuntimeError("agent-name registry entries are unavailable")
    pairs = tuple(
        sorted(
            (
                str(name),
                str(entry.get("canonical_global_name") or ""),
            )
            for name, entry in entries.items()
            if isinstance(entry, Mapping)
        )
    )
    identity = AgentIdentitySnapshot.current()
    payload = {
        "rows": pairs,
        "owner": (
            (identity.owner.username, identity.owner.machine_name)
            if identity.owner is not None
            else None
        ),
        "sibling_machines": identity.sibling_machines,
        "known_owner_roots": identity.known_owner_roots,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _elapsed_ms(start: int) -> float:
    return round((perf_counter_ns() - start) / 1_000_000, 3)


def _add_duration(telemetry: dict[str, Any] | None, name: str, start: int) -> None:
    if telemetry is not None:
        telemetry[name] = float(telemetry.get(name, 0.0)) + _elapsed_ms(start)


def _load_link_snapshot_traced(owner: Any, telemetry: dict[str, Any] | None) -> Any:
    if telemetry is not None:
        telemetry["link_snapshot_probe_count"] += 1
    started = perf_counter_ns() if telemetry is not None else 0
    try:
        return _load_link_snapshot(owner)
    finally:
        _add_duration(telemetry, "link_snapshot_duration_ms", started)


def _build_facets_traced(
    owner: Any,
    link_snapshot: Any,
    telemetry: dict[str, Any] | None,
) -> tuple[Mapping[str, Any], Any, str | None]:
    if telemetry is not None:
        telemetry["facet_load_count"] += 1
    started = perf_counter_ns() if telemetry is not None else 0
    try:
        return _build_facets(owner, link_snapshot)
    finally:
        _add_duration(telemetry, "facet_load_duration_ms", started)


def build_archive_result(
    owner: Any,
    snapshot: ArchiveRequestSnapshot,
) -> dict[str, Any]:
    """Probe, compile or reuse the handle, and query still-requested windows."""
    with tui_trace(
        "agents.archive_build",
        request_kind=snapshot.kind,
    ) as telemetry:
        try:
            result = _build_archive_result(
                owner,
                snapshot,
                telemetry=telemetry if tui_trace_enabled() else None,
            )
        except Exception:
            log.debug("archive corpus probe failed", exc_info=True)
            result = {"kind": "error"}
        if tui_trace_enabled():
            telemetry["outcome"] = str(result.get("kind", "error"))
            telemetry["unchanged_reason"] = str(result.get("unchanged_reason") or "")
        return result


def _build_archive_result(
    owner: Any,
    snapshot: ArchiveRequestSnapshot,
    *,
    telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if telemetry is not None:
        telemetry["idle_probe_count"] = int(snapshot.kind == ARCHIVE_REQUEST_IDLE)
        telemetry["link_snapshot_probe_count"] = 0
        telemetry["link_aggregate_drift_count"] = 0
        telemetry["link_snapshot_unchanged_count"] = 0
        telemetry["catalog_identity_probe_count"] = 0
        telemetry["facet_projection_compare_count"] = 0
        telemetry["facet_projection_unchanged_count"] = 0
        telemetry["corpus_handle_reuse_count"] = 0
        telemetry["facet_load_count"] = 0
        telemetry["corpus_lookup_count"] = 0
        telemetry["corpus_compile_count"] = 0
        telemetry["corpus_summary_query_count"] = 0
        telemetry["corpus_window_query_count"] = 0
        telemetry["corpus_count_query_count"] = 0
        for name in (
            "token_probe_duration_ms",
            "link_snapshot_duration_ms",
            "catalog_identity_duration_ms",
            "facet_load_duration_ms",
            "display_snapshot_duration_ms",
            "corpus_lookup_duration_ms",
            "corpus_query_duration_ms",
        ):
            telemetry[name] = 0.0
    started = perf_counter_ns() if telemetry is not None else 0
    try:
        tokens = _probe_tokens(owner)
    finally:
        _add_duration(telemetry, "token_probe_duration_ms", started)
    if telemetry is not None:
        telemetry["changed_token_components"] = list(
            _changed_token_components(snapshot.tokens, tokens)
        )
    if (
        snapshot.kind == ARCHIVE_REQUEST_IDLE
        and not snapshot.pending_exact_name
        and _idle_tokens_match(snapshot, tokens)
    ):
        return {
            "kind": "unchanged",
            "tokens": tokens,
            "unchanged_reason": "tokens_match",
        }

    facets = snapshot.link_facets
    link_snapshot = snapshot.link_snapshot
    catalog_link_identity = snapshot.catalog_link_identity
    link_rows_unchanged = False
    link_changed = _link_signature_changed(snapshot.tokens, tokens)

    if link_changed:
        candidate_link_snapshot = _load_link_snapshot_traced(owner, telemetry)
        if telemetry is not None:
            telemetry["link_aggregate_drift_count"] = _changed_link_project_count(
                link_snapshot, candidate_link_snapshot
            )
        if _same_link_snapshot_content(link_snapshot, candidate_link_snapshot):
            link_snapshot = candidate_link_snapshot
            link_rows_unchanged = True
            if telemetry is not None:
                telemetry["link_snapshot_unchanged_count"] = 1

            if catalog_link_identity is not None:
                if telemetry is not None:
                    telemetry["catalog_identity_probe_count"] = 1
                stage_started = perf_counter_ns() if telemetry is not None else 0
                try:
                    current_catalog_identity = _catalog_link_identity(owner)
                finally:
                    _add_duration(
                        telemetry, "catalog_identity_duration_ms", stage_started
                    )
                if current_catalog_identity == catalog_link_identity:
                    catalog_link_identity = current_catalog_identity
                else:
                    facets, link_snapshot, catalog_link_identity = _build_facets_traced(
                        owner, candidate_link_snapshot, telemetry
                    )
            else:
                facets, link_snapshot, catalog_link_identity = _build_facets_traced(
                    owner, candidate_link_snapshot, telemetry
                )
        else:
            facets, link_snapshot, catalog_link_identity = _build_facets_traced(
                owner, candidate_link_snapshot, telemetry
            )
    elif facets is None:
        link_snapshot = _load_link_snapshot_traced(owner, telemetry)
        facets, link_snapshot, catalog_link_identity = _build_facets_traced(
            owner, link_snapshot, telemetry
        )

    stage_started = perf_counter_ns() if telemetry is not None else 0
    try:
        display_snapshot = _load_display_snapshot(owner)
    finally:
        _add_duration(telemetry, "display_snapshot_duration_ms", stage_started)

    facet_projection_unchanged = (
        snapshot.link_facets is not None
        and facets is not None
        and facets == snapshot.link_facets
    )
    can_reuse_inputs = _non_link_tokens_match(snapshot.tokens, tokens)
    if telemetry is not None and link_changed and not link_rows_unchanged:
        telemetry["facet_projection_compare_count"] = 1
        telemetry["facet_projection_unchanged_count"] = int(facet_projection_unchanged)
    if (
        snapshot.kind == ARCHIVE_REQUEST_IDLE
        and not snapshot.pending_exact_name
        and snapshot.corpus is not None
        and can_reuse_inputs
        and facet_projection_unchanged
    ):
        return {
            "kind": "unchanged",
            "tokens": tokens,
            "link_snapshot": link_snapshot,
            "catalog_link_identity": catalog_link_identity,
            "display_snapshot": display_snapshot,
            "unchanged_reason": (
                "link_metadata_only"
                if link_rows_unchanged
                else "facet_projection_unchanged"
            ),
        }

    reuse_handle = (
        snapshot.corpus is not None
        and snapshot.kind != ARCHIVE_REQUEST_PREWARM
        and can_reuse_inputs
        and facet_projection_unchanged
    )
    if telemetry is not None:
        telemetry["corpus_handle_reuse_count"] = int(reuse_handle)
    if reuse_handle:
        corpus = snapshot.corpus
        profile = snapshot.profile
    else:
        if facets is None:
            facets, link_snapshot, catalog_link_identity = _build_facets_traced(
                owner, link_snapshot, telemetry
            )
        if telemetry is not None:
            telemetry["corpus_lookup_count"] = 1
        stage_started = perf_counter_ns() if telemetry is not None else 0
        try:
            cached = _get_corpus(owner, tokens, facets, telemetry=telemetry)
        finally:
            _add_duration(telemetry, "corpus_lookup_duration_ms", stage_started)
        if cached is None:
            return {
                "kind": "unreadable",
                "tokens": tokens,
                "facets": facets,
                "link_snapshot": link_snapshot,
                "catalog_link_identity": catalog_link_identity,
                "display_snapshot": display_snapshot,
                "lookup_row": _lookup_pending(snapshot.pending_exact_name, None),
            }
        corpus = getattr(cached, "corpus", None)
        profile = getattr(cached, "profile", None)
        if telemetry is not None:
            telemetry["corpus_handle_reuse_count"] = int(
                corpus is not None and corpus is snapshot.corpus
            )
    status_name, indexed_rows, error_message = _status_from_corpus(corpus, tokens)
    stage_started = perf_counter_ns() if telemetry is not None else 0
    try:
        summary, windows, identities, count = _query_handle(
            corpus, profile, snapshot, telemetry=telemetry
        )
    finally:
        _add_duration(telemetry, "corpus_query_duration_ms", stage_started)
    return {
        "kind": "built",
        "tokens": tokens,
        "facets": facets,
        "link_snapshot": link_snapshot,
        "catalog_link_identity": catalog_link_identity,
        "corpus": corpus,
        "profile": profile,
        "status": status_name,
        "indexed_rows": indexed_rows,
        "error_message": error_message,
        "summary": summary,
        "windows": windows,
        "identities": identities,
        "count": count,
        "display_snapshot": display_snapshot,
        "lookup_row": _lookup_pending(snapshot.pending_exact_name, corpus),
    }


def _changed_token_components(
    held: ArchiveRevalidationTokens | None,
    current: ArchiveRevalidationTokens,
) -> tuple[str, ...]:
    """Name changed archive inputs without including paths or project keys."""
    if held is None:
        return ("initial",)
    components = (
        ("index_exists", held.index_exists != current.index_exists),
        ("index_stat", held.index_stat != current.index_stat),
        ("link_signature", held.link_signature != current.link_signature),
        ("profile_digest", held.profile_digest != current.profile_digest),
        ("rebuilding", held.rebuilding != current.rebuilding),
        ("indexed_rows", held.indexed_rows != current.indexed_rows),
    )
    return tuple(name for name, changed in components if changed)


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


def _load_link_snapshot(owner: Any) -> Any:
    loader = getattr(owner, "_archive_load_link_snapshot", None)
    if callable(loader):
        return loader()
    if callable(getattr(owner, "_archive_load_facets", None)):
        return None
    from sase.ace.tui.relations.artifact_links import load_artifact_links_snapshot

    return load_artifact_links_snapshot(None)


def _build_facets(
    owner: Any,
    link_snapshot: Any,
) -> tuple[Mapping[str, Any], Any, str | None]:
    loader = getattr(owner, "_archive_load_facets", None)
    if callable(loader):
        loaded = loader()
        facets = loaded if isinstance(loaded, Mapping) else {}
        return facets, link_snapshot, _catalog_link_identity(owner)

    if link_snapshot is None:
        link_snapshot = _load_link_snapshot(owner)
    from sase.ace.tui.relations.artifact_links import load_artifact_links_snapshot
    from sase.agents.catalog import (
        build_agent_catalog_link_facets,
        build_agent_catalog_snapshot,
    )
    from sase.core.agent_identity_facade import AgentIdentitySnapshot

    catalog = build_agent_catalog_snapshot()
    resolved_links = link_snapshot or load_artifact_links_snapshot(None)
    identity = AgentIdentitySnapshot.current()
    facets = build_agent_catalog_link_facets(
        catalog.rows,
        getattr(resolved_links, "rows", ()),
        identity=identity,
    )
    return (
        facets,
        resolved_links,
        _catalog_link_identity_from_rows(catalog.rows, identity),
    )


def _get_corpus(
    owner: Any,
    tokens: ArchiveRevalidationTokens,
    facets: Mapping[str, Any] | None,
    *,
    telemetry: dict[str, Any] | None = None,
) -> Any:
    from sase.ace.dismissed_bundle_index._models import DismissedBundleIndexProgress

    getter = getattr(owner, "_archive_get_corpus", None)
    progress = DismissedBundleIndexProgress(
        rebuilding=tokens.rebuilding,
        indexed_rows=tokens.indexed_rows,
    )
    try:
        kwargs = {
            "root": _archive_root(owner),
            "progress": progress,
            "link_facets": facets if facets is not None else {},
            "profile": _resolved_profile(owner),
        }
        if getter is not None:
            if telemetry is not None:
                telemetry["corpus_compile_count"] = None
            return getter(**kwargs)
        if telemetry is not None:
            from sase.core.agent_archive_corpus_cache import (
                get_agent_archive_corpus_with_compile_status,
            )

            cached, compiled = get_agent_archive_corpus_with_compile_status(**kwargs)
            telemetry["corpus_compile_count"] = int(compiled)
            return cached
        from sase.core.agent_archive_corpus_cache import get_agent_archive_corpus

        return get_agent_archive_corpus(**kwargs)
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


def _match_query(query: str) -> str | None:
    """Strip the host ``in:`` scope token: it selects the view, not rows.

    The core corpus only knows row fields, so the scope must be extracted
    before every summary, rows, and count call (the CLI does the same).
    """
    from sase.ace.query.profile_reference_support import ProfileQueryError
    from sase.ace.query.scope_token import ScopeTokenError, extract_scope

    try:
        remainder, _scope = extract_scope(query)
    except (ScopeTokenError, ProfileQueryError, ValueError):
        log.debug("archive query scope rejected: %r", query, exc_info=True)
        return None
    return remainder


def _query_handle(
    corpus: Any,
    profile: Any,
    snapshot: ArchiveRequestSnapshot,
    *,
    telemetry: dict[str, Any] | None = None,
) -> tuple[
    Mapping[str, Any] | None,
    tuple[ArchiveLoadedWindow, ...],
    tuple[str, ...],
    int,
]:
    if corpus is None:
        return None, (), (), 0
    query = _match_query(snapshot.query)
    if query is None:
        return None, (), (), 0
    summary: Mapping[str, Any] | None = None
    if telemetry is not None:
        telemetry["corpus_summary_query_count"] = 1
    try:
        summary = corpus.summary(query, group_by=snapshot.grouping, profile=profile)
    except Exception:
        log.debug("archive corpus summary failed", exc_info=True)
        summary = None
    windows: list[ArchiveLoadedWindow] = []
    identities: list[str] = []
    for window in snapshot.windows:
        if telemetry is not None:
            telemetry["corpus_window_query_count"] += 1
        try:
            payload = corpus.rows(
                query,
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
    if telemetry is not None:
        telemetry["corpus_count_query_count"] = 1
    try:
        count = int(corpus.count(query, profile=profile))
    except Exception:
        if isinstance(summary, Mapping):
            count = int(summary.get("total", 0) or 0)
    return summary, tuple(windows), tuple(identities), count


def _load_display_snapshot(owner: Any) -> Any:
    """Warm the project-display snapshot off-thread for project banners."""
    loader = getattr(owner, "_archive_load_display_snapshot", None)
    if callable(loader):
        return loader()
    from sase.project_display_names import load_project_display_snapshot

    return load_project_display_snapshot()


def _lookup_pending(name: str | None, corpus: Any) -> Mapping[str, Any] | None:
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
