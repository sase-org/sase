"""Rust-routed corpus facade: parity with the Python reference evaluator."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.ace.query.profile_reference import (
    canonical_query_for_profile,
    evaluate_query_many_for_profile,
    parse_query_for_profile,
)
from sase.ace.query_profile import compile_query_profile
from sase.ace.query_profile.profiles import (
    beads_query_schema,
    files_query_schema,
    patches_query_schema,
    provider_query_schema,
)
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryCacheKey,
    compile_artifact_query_index,
    evaluate_artifact_query_many,
    parse_artifact_query,
)

_BEADS_ROWS = [
    {
        "stable_id": "open-task",
        "fields": {
            "type": "task",
            "status": "open",
            "project": "sase",
            "assignee": "Alice Smith",
            "title": "Load filter profile",
            "body": "Reference evaluator",
        },
    },
    {
        "stable_id": "closed-phase",
        "fields": {
            "type": "phase",
            "status": "closed",
            "project": "sase",
            "assignee": "Bob",
            "title": "Load filter profile",
            "body": "Reference evaluator",
        },
    },
    {
        "stable_id": "open-plan",
        "fields": {
            "type": "plan",
            "status": "open",
            "project": "sase",
            "assignee": "Carol",
            "title": "Unrelated",
            "body": "Reference evaluator",
        },
    },
]


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


@pytest.mark.parametrize(
    ("schema_builder", "rows", "queries"),
    [
        (
            beads_query_schema,
            _BEADS_ROWS,
            ("type:task type:phase -status:closed load", "assignee:ali", "unrelated"),
        ),
        (
            files_query_schema,
            [
                {
                    "stable_id": "a",
                    "fields": {"kind": "chat", "origin": "created", "label": "run one"},
                },
                {
                    "stable_id": "b",
                    "fields": {"kind": "file", "origin": "ref", "label": "run two"},
                },
            ],
            ("kind:chat", "origin:ref two", "run"),
        ),
        (
            patches_query_schema,
            [
                {
                    "stable_id": "patch:one",
                    "fields": {"project": "sase", "status": "READY", "name": "one"},
                    "searchable_text": "needle text",
                    "predicates": ("running_agent",),
                },
                {
                    "stable_id": "patch:two",
                    "fields": {"project": "sase", "status": "WIP", "name": "two"},
                    "searchable_text": "needle text",
                    "predicates": (),
                },
            ],
            ("+sase AND %y AND @@@ AND needle", "!!", "*"),
        ),
    ],
)
def test_rust_facade_matches_python_reference_evaluator(
    schema_builder,
    rows: list[dict[str, object]],
    queries: tuple[str, ...],
) -> None:
    profile = compile_query_profile(schema_builder())
    index = compile_artifact_query_index(
        pane_id=profile.pane_id, generation=1, profile=profile, entries=rows
    )
    for query in queries:
        rust_matched = set(evaluate_artifact_query_many(query, index).matched_row_ids)
        reference_matches = evaluate_query_many_for_profile(query, rows, profile)
        reference_matched = {
            row["stable_id"]
            for row, matched in zip(rows, reference_matches, strict=True)
            if matched
        }
        assert rust_matched == reference_matched, query


def test_substring_vs_exact_field_match_mode_through_rust() -> None:
    """``assignee`` matches by substring; ``project`` requires an exact value."""

    profile = compile_query_profile(beads_query_schema())
    index = compile_artifact_query_index(
        pane_id="beads", generation=1, profile=profile, entries=_BEADS_ROWS
    )
    assert evaluate_artifact_query_many("assignee:ali", index).matched_row_ids == (
        "open-task",
    )
    assert evaluate_artifact_query_many("project:sas", index).matched_row_ids == ()
    assert evaluate_artifact_query_many("project:sase", index).matched_row_ids == (
        "open-task",
        "closed-phase",
        "open-plan",
    )


def test_since_until_date_fields_use_range_comparison_through_rust() -> None:
    """A row's one timestamp is duplicated under both the ``since`` and
    ``until`` field keys, matching how the legacy Beads matcher compares a
    single ``record.timestamp`` against both bound directions
    (``beads_filtering.py``): so either query direction can find it under
    its own field key.
    """

    profile = compile_query_profile(beads_query_schema())
    rows = [
        {
            "stable_id": "old",
            "fields": {"since": "2020-01-01T00:00:00", "until": "2020-01-01T00:00:00"},
        },
        {
            "stable_id": "recent",
            "fields": {"since": "2024-06-15T00:00:00", "until": "2024-06-15T00:00:00"},
        },
    ]
    index = compile_artifact_query_index(
        pane_id="beads", generation=1, profile=profile, entries=rows
    )
    since_result = evaluate_artifact_query_many("since:2023-01-01", index)
    assert since_result.matched_row_ids == ("recent",)
    until_result = evaluate_artifact_query_many("until:2023-01-01", index)
    assert until_result.matched_row_ids == ("old",)
    assert evaluate_query_many_for_profile("since:2023-01-01", rows, profile) == [
        False,
        True,
    ]


def test_provider_profile_index_matches_python_reference() -> None:
    profile = compile_query_profile(
        provider_query_schema(
            "notes",
            {
                "ref": {
                    "properties": {
                        "tags": {"type": "string_list", "searchable": True},
                        "title": {"type": "string", "searchable": True},
                    }
                }
            },
        )
    )
    rows = [
        {
            "stable_id": "one",
            "properties": {"tags": '["alpha", "beta"]', "title": "Shared note"},
        },
        {"stable_id": "two", "properties": {"tags": "gamma", "title": "Other note"}},
    ]
    index = compile_artifact_query_index(
        pane_id=profile.pane_id, generation=1, profile=profile, entries=rows
    )
    result = evaluate_artifact_query_many("tags:beta shared", index)
    assert result.matched_row_ids == ("one",)
    assert evaluate_query_many_for_profile("tags:beta shared", rows, profile) == [
        True,
        False,
    ]


@pytest.mark.parametrize("query", ['"example"', "%w", "name:example", "!!", "+sase"])
def test_parse_through_rust_matches_python_reference(query: str) -> None:
    profile = compile_query_profile(patches_query_schema())
    assert parse_artifact_query(query, profile) == parse_query_for_profile(
        query, profile
    )


@pytest.mark.parametrize(
    ("query", "flat"),
    [("status:open", True), ("kind:file", False)],
)
def test_flat_parse_through_rust_matches_python_reference(
    query: str,
    flat: bool,
) -> None:
    profile = compile_query_profile(
        beads_query_schema() if flat else files_query_schema()
    )
    assert parse_artifact_query(query, profile) == parse_query_for_profile(
        query, profile
    )
