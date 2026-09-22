"""Rust-routed corpus facade: index lifecycle (compile, facets, cache key)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.ace.query.profile_evaluator import (
    coerce_artifact_query_rows,
    coerce_artifact_query_rows_with_wire,
)
from sase.ace.query.profile_reference import canonical_query_for_profile
from sase.ace.query_profile import compile_query_profile
from sase.ace.query_profile.profiles import beads_query_schema
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryCacheKey,
    compile_artifact_query_index,
    evaluate_artifact_query_many,
)
from tests._query_profile_corpus_facade_helpers import _BEADS_ROWS


def test_compile_index_and_evaluate_matches_expected_rows() -> None:
    profile = compile_query_profile(beads_query_schema())
    index = compile_artifact_query_index(
        pane_id="beads",
        generation=1,
        profile=profile,
        entries=_BEADS_ROWS,
    )
    assert len(index) == 3
    assert index.row_ids == ("open-task", "closed-phase", "open-plan")

    result = evaluate_artifact_query_many(
        "type:task type:phase -status:closed load", index
    )
    assert result.matched_row_ids == ("open-task",)
    assert result.cache_key == ArtifactQueryCacheKey(
        pane_id="beads",
        generation=1,
        profile_digest=profile.digest,
        canonical_query=canonical_query_for_profile(
            "type:task type:phase -status:closed load", profile
        ),
    )


def test_observed_facets_report_distinct_filterable_values() -> None:
    profile = compile_query_profile(beads_query_schema())
    index = compile_artifact_query_index(
        pane_id="beads",
        generation=1,
        profile=profile,
        entries=_BEADS_ROWS,
    )
    assert index.facets["type"] == ("phase", "plan", "task")
    assert index.facets["status"] == ("closed", "open")
    # Non-filterable (search-only) fields never appear in facets.
    assert "title" not in index.facets
    assert "body" not in index.facets


def test_coerce_rows_with_wire_preserves_rust_row_wire_shape() -> None:
    profile = compile_query_profile(beads_query_schema())
    entries = [
        {
            "stable_id": "open-task",
            "fields": {
                "type": "task",
                "status": ("open", "blocked"),
                "project": ("gh_sase-org__sase", "sase"),
                "title": "Load filter profile",
            },
            "searchable_text": "Load filter profile",
            "predicates": ("running_agent",),
        }
    ]

    rows, wire_rows = coerce_artifact_query_rows_with_wire(profile, entries)

    assert rows == coerce_artifact_query_rows(profile, entries)
    assert wire_rows == [
        {
            "fields": {
                "type": ["task"],
                "status": ["open", "blocked"],
                "project": ["gh_sase-org__sase", "sase"],
                "title": ["Load filter profile"],
            },
            "searchable_text": "Load filter profile",
            "predicates": {
                "error_suffix": False,
                "running_agent": True,
                "running_process": False,
            },
        }
    ]


def test_cache_key_is_sensitive_to_generation_profile_and_query() -> None:
    profile = compile_query_profile(beads_query_schema())
    index = compile_artifact_query_index(
        pane_id="beads", generation=1, profile=profile, entries=_BEADS_ROWS
    )
    a = evaluate_artifact_query_many("status:open", index)
    b = evaluate_artifact_query_many("status:closed", index)
    assert a.cache_key != b.cache_key

    other_generation = compile_artifact_query_index(
        pane_id="beads", generation=2, profile=profile, entries=_BEADS_ROWS
    )
    c = evaluate_artifact_query_many("status:open", other_generation)
    assert a.cache_key != c.cache_key
    assert a.matched_row_ids == c.matched_row_ids


def test_stale_index_validation_raises_on_row_count_mismatch() -> None:
    profile = compile_query_profile(beads_query_schema())
    index = compile_artifact_query_index(
        pane_id="beads", generation=1, profile=profile, entries=_BEADS_ROWS
    )
    stale = replace(index, row_ids=(*index.row_ids, "phantom"))
    with pytest.raises(ValueError, match="stale query index"):
        evaluate_artifact_query_many("status:open", stale)
