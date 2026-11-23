"""Coordinate off-thread Archive corpus probes, builds, and queries."""

from __future__ import annotations

import logging
from time import perf_counter_ns
from typing import Any

from ...models.agent_archive_controller import (
    ARCHIVE_REQUEST_IDLE,
    ARCHIVE_REQUEST_PREWARM,
    ArchiveRequestSnapshot,
)
from ...util.trace import is_enabled as tui_trace_enabled, tui_trace
from ._archive_controller_build_query import query_handle
from ._archive_controller_build_support import (
    add_duration,
    build_facets_traced,
    catalog_link_identity as resolve_catalog_link_identity,
    changed_link_project_count,
    changed_token_components,
    get_corpus,
    idle_tokens_match,
    link_signature_changed,
    load_display_snapshot,
    load_link_snapshot_traced,
    lookup_pending,
    non_link_tokens_match,
    probe_tokens,
    same_link_snapshot_content,
    status_from_corpus,
)

log = logging.getLogger(__name__)


def build_archive_result_pipeline(
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
        tokens = probe_tokens(owner)
    finally:
        add_duration(telemetry, "token_probe_duration_ms", started)
    if telemetry is not None:
        telemetry["changed_token_components"] = list(
            changed_token_components(snapshot.tokens, tokens)
        )
    if (
        snapshot.kind == ARCHIVE_REQUEST_IDLE
        and not snapshot.pending_exact_name
        and idle_tokens_match(snapshot, tokens)
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
    link_changed = link_signature_changed(snapshot.tokens, tokens)

    if link_changed:
        candidate_link_snapshot = load_link_snapshot_traced(owner, telemetry)
        if telemetry is not None:
            telemetry["link_aggregate_drift_count"] = changed_link_project_count(
                link_snapshot, candidate_link_snapshot
            )
        if same_link_snapshot_content(link_snapshot, candidate_link_snapshot):
            link_snapshot = candidate_link_snapshot
            link_rows_unchanged = True
            if telemetry is not None:
                telemetry["link_snapshot_unchanged_count"] = 1

            if catalog_link_identity is not None:
                if telemetry is not None:
                    telemetry["catalog_identity_probe_count"] = 1
                stage_started = perf_counter_ns() if telemetry is not None else 0
                try:
                    current_catalog_identity = resolve_catalog_link_identity(owner)
                finally:
                    add_duration(
                        telemetry, "catalog_identity_duration_ms", stage_started
                    )
                if current_catalog_identity == catalog_link_identity:
                    catalog_link_identity = current_catalog_identity
                else:
                    facets, link_snapshot, catalog_link_identity = build_facets_traced(
                        owner, candidate_link_snapshot, telemetry
                    )
            else:
                facets, link_snapshot, catalog_link_identity = build_facets_traced(
                    owner, candidate_link_snapshot, telemetry
                )
        else:
            facets, link_snapshot, catalog_link_identity = build_facets_traced(
                owner, candidate_link_snapshot, telemetry
            )
    elif facets is None:
        link_snapshot = load_link_snapshot_traced(owner, telemetry)
        facets, link_snapshot, catalog_link_identity = build_facets_traced(
            owner, link_snapshot, telemetry
        )

    stage_started = perf_counter_ns() if telemetry is not None else 0
    try:
        display_snapshot = load_display_snapshot(owner)
    finally:
        add_duration(telemetry, "display_snapshot_duration_ms", stage_started)

    facet_projection_unchanged = (
        snapshot.link_facets is not None
        and facets is not None
        and facets == snapshot.link_facets
    )
    can_reuse_inputs = non_link_tokens_match(snapshot.tokens, tokens)
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
            facets, link_snapshot, catalog_link_identity = build_facets_traced(
                owner, link_snapshot, telemetry
            )
        if telemetry is not None:
            telemetry["corpus_lookup_count"] = 1
        stage_started = perf_counter_ns() if telemetry is not None else 0
        try:
            cached = get_corpus(owner, tokens, facets, telemetry=telemetry)
        finally:
            add_duration(telemetry, "corpus_lookup_duration_ms", stage_started)
        if cached is None:
            return {
                "kind": "unreadable",
                "tokens": tokens,
                "facets": facets,
                "link_snapshot": link_snapshot,
                "catalog_link_identity": catalog_link_identity,
                "display_snapshot": display_snapshot,
                "lookup_row": lookup_pending(snapshot.pending_exact_name, None),
            }
        corpus = getattr(cached, "corpus", None)
        profile = getattr(cached, "profile", None)
        if telemetry is not None:
            telemetry["corpus_handle_reuse_count"] = int(
                corpus is not None and corpus is snapshot.corpus
            )
    status_name, indexed_rows, error_message = status_from_corpus(corpus, tokens)
    stage_started = perf_counter_ns() if telemetry is not None else 0
    try:
        summary, windows, identities, count = query_handle(
            corpus, profile, snapshot, telemetry=telemetry
        )
    finally:
        add_duration(telemetry, "corpus_query_duration_ms", stage_started)
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
        "lookup_row": lookup_pending(snapshot.pending_exact_name, corpus),
    }


__all__ = ["build_archive_result_pipeline"]
