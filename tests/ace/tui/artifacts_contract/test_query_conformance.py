"""Cross-language query conformance for every healthy Artifacts dialect."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sase.ace.query.profile_reference import (
    canonical_query_for_profile,
    evaluate_query_many_for_profile,
)
from sase.ace.query_profile import CompiledQueryProfile
from sase.ace.tui._artifact_tab_contract import compile_provider_contract
from sase.ace.tui.artifact_tabs import resolve_artifacts_subtabs
from sase.core.query_profile_corpus_facade import (
    canonicalize_artifact_query,
    compile_artifact_query_index,
    evaluate_artifact_query_many,
)


def _provider_spec() -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider": "notes",
        "ref": {
            "kind": "notes",
            "properties": {
                "title": {"type": "string", "searchable": True},
                "status": {"type": "string"},
            },
            "detail": {"fields": ["title", "status"]},
            "identity": {},
            "inventory": {"globs": ["**/*.md"]},
        },
    }


def _profiles() -> Iterator[tuple[str, CompiledQueryProfile]]:
    builtin_ids = {"patches", "stitches", "beads", "ref:plan", "files"}
    builtins = [
        descriptor
        for descriptor in resolve_artifacts_subtabs()
        if descriptor.id in builtin_ids and not descriptor.is_degraded
    ]
    for descriptor in builtins:
        yield descriptor.id, descriptor.resolved_contract.query_profile

    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_provider_spec(),
        provider_spec_digest="fixture",
    )
    assert result.error is None
    yield "ref:notes", result.contract.query_profile


def _field_case(profile: CompiledQueryProfile) -> tuple[str, str]:
    field = next(
        item
        for item in profile.fields
        if item.filterable and item.value_kind not in {"date", "bool", "int"}
    )
    value = field.static_values[0] if field.static_values else "alpha"
    return field.key, value


@pytest.mark.parametrize("pane_id,profile", list(_profiles()))
def test_profile_python_rust_canonical_match_predicate_and_cache_parity(
    pane_id: str,
    profile: CompiledQueryProfile,
) -> None:
    key, value = _field_case(profile)
    query = f"{key}:{value}"
    rows = (
        {
            "stable_id": "matching",
            "fields": {key: value},
            "searchable_text": "alpha document",
            "predicates": ("running_agent",),
        },
        {
            "stable_id": "ordinary",
            "fields": {},
            "searchable_text": "ordinary document",
            "predicates": (),
        },
    )

    canonical = canonical_query_for_profile(query, profile)
    assert canonicalize_artifact_query(query, profile) == canonical

    index = compile_artifact_query_index(
        pane_id=pane_id,
        generation=11,
        profile=profile,
        entries=rows,
    )
    python_matches = evaluate_query_many_for_profile(query, rows, profile)
    rust_result = evaluate_artifact_query_many(query, index)
    assert rust_result.matched_row_ids == tuple(
        row["stable_id"]
        for row, matches in zip(rows, python_matches, strict=True)
        if matches
    )
    assert value in index.facets[key]

    for predicate_query, expected in (
        ("@@@", ("matching",)),
        ("!@", ("ordinary",)),
        ("*", ("matching",)),
    ):
        assert canonicalize_artifact_query(
            predicate_query, profile
        ) == canonical_query_for_profile(predicate_query, profile)
        python_predicates = evaluate_query_many_for_profile(
            predicate_query, rows, profile
        )
        rust_predicates = evaluate_artifact_query_many(predicate_query, index)
        assert rust_predicates.matched_row_ids == expected
        assert rust_predicates.matched_row_ids == tuple(
            row["stable_id"]
            for row, matches in zip(rows, python_predicates, strict=True)
            if matches
        )

    next_generation = compile_artifact_query_index(
        pane_id=pane_id,
        generation=12,
        profile=profile,
        entries=rows,
    )
    next_result = evaluate_artifact_query_many(query, next_generation)
    assert rust_result.cache_key == (
        pane_id,
        11,
        profile.digest,
        canonical,
    )
    assert next_result.cache_key == (
        pane_id,
        12,
        profile.digest,
        canonical,
    )


def test_synthetic_provider_malformed_properties_degrade_per_row() -> None:
    result = compile_provider_contract(
        kind="notes",
        label="Note",
        icon="¶",
        accent="#5FAFFF",
        spec=_provider_spec(),
        provider_spec_digest="fixture",
    )
    profile = result.contract.query_profile
    rows = (
        {
            "stable_id": "valid",
            "properties": {"title": "Alpha", "status": "draft"},
        },
        {
            "stable_id": "malformed",
            "properties": {"title": {"not": "scalar"}, "status": [object()]},
        },
    )
    index = compile_artifact_query_index(
        pane_id="ref:notes",
        generation=3,
        profile=profile,
        entries=rows,
    )

    assert index.row_ids == ("valid", "malformed")
    assert evaluate_artifact_query_many("title:alpha", index).matched_row_ids == (
        "valid",
    )
    assert index.facets["title"] == ("Alpha",)
