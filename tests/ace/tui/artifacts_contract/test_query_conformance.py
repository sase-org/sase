"""Cross-language query conformance for every healthy Artifacts dialect."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pytest

from sase.ace.query.profile_reference import (
    ProfileQueryError,
    canonical_query_for_profile,
    evaluate_query_many_for_profile,
    parse_query_for_profile,
)
from sase.ace.query_profile import CompiledQueryProfile
from sase.ace.query_profile.pane_registry import compiled_profile_for_builtin_pane
from sase.ace.tui._artifact_tab_contract import compile_provider_contract
from sase.ace.tui.artifact_tabs import resolve_artifacts_subtabs
from sase.core.query_profile_corpus_facade import (
    _canonicalize_artifact_query,
    compile_artifact_query_index,
    evaluate_artifact_query_many,
)

_GOLDEN = Path(__file__).resolve().parent / "goldens" / "query" / "profile_cases.json"
_FIXED_NOW = datetime(2026, 8, 25, 12, 0, 0)
_REQUIRED_PROFILE_PANES = {
    "agents",
    "patches",
    "stitches",
    "beads",
    "ref:plan",
    "files",
    "ref:notes",
}


@pytest.fixture(autouse=True)
def _freeze_profile_reference_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.core.time import get_timezone

    fixed = _FIXED_NOW.replace(tzinfo=get_timezone())

    def normalize(now: datetime | None = None) -> datetime:
        if now is None:
            return fixed
        if now.tzinfo is None:
            return now.replace(tzinfo=fixed.tzinfo)
        return now.astimezone(fixed.tzinfo)

    monkeypatch.setattr(
        "sase.ace.query.profile_evaluator.normalize_reference_time",
        normalize,
    )
    monkeypatch.setattr(
        "sase.ace.query.profile_reference_support.normalize_reference_time",
        normalize,
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


def _golden() -> dict[str, Any]:
    data = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _golden_panes() -> dict[str, dict[str, Any]]:
    panes = _golden()["panes"]
    assert isinstance(panes, dict)
    return panes


def _profile_by_pane_id() -> dict[str, CompiledQueryProfile]:
    return dict(_profiles())


def _profiles() -> Iterator[tuple[str, CompiledQueryProfile]]:
    builtin_ids = {"patches", "stitches", "beads", "ref:plan", "agents", "files"}
    builtins = [
        descriptor
        for descriptor in resolve_artifacts_subtabs()
        if descriptor.id in builtin_ids and not descriptor.is_degraded
    ]
    descriptor_ids = {descriptor.id for descriptor in builtins}
    assert descriptor_ids <= builtin_ids
    for descriptor in builtins:
        yield descriptor.id, descriptor.resolved_contract.query_profile
    for pane_id in sorted(builtin_ids - descriptor_ids):
        profile = compiled_profile_for_builtin_pane(pane_id)
        assert profile is not None
        yield pane_id, profile

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


def _rust_canonical_for_golden_source(
    source: str,
    canonical: str,
    profile: CompiledQueryProfile,
) -> str:
    if any(item.filterable and item.value_kind == "date" for item in profile.fields):
        return _canonicalize_artifact_query(canonical, profile)
    return _canonicalize_artifact_query(source, profile)


def test_profile_query_golden_corpus_covers_every_migrated_pane() -> None:
    assert set(_golden_panes()) == _REQUIRED_PROFILE_PANES
    assert set(_profile_by_pane_id()) == _REQUIRED_PROFILE_PANES


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
    assert _canonicalize_artifact_query(query, profile) == canonical

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
        assert _canonicalize_artifact_query(
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


@pytest.mark.parametrize("pane_id", sorted(_REQUIRED_PROFILE_PANES))
def test_profile_query_goldens_match_python_reference_and_rust_batch(
    pane_id: str,
) -> None:
    panes = _golden_panes()
    profile = _profile_by_pane_id()[pane_id]
    rows = panes[pane_id]["rows"]
    assert isinstance(rows, list)
    index = compile_artifact_query_index(
        pane_id=pane_id,
        generation=17,
        profile=profile,
        entries=rows,
    )
    query_cases = panes[pane_id]["queries"]
    assert isinstance(query_cases, dict)

    for source, expected in query_cases.items():
        assert isinstance(expected, dict)
        canonical = expected["canonical"]
        matches = tuple(expected["matches"])

        assert canonical_query_for_profile(source, profile) == canonical
        assert (
            _rust_canonical_for_golden_source(source, canonical, profile) == canonical
        )

        python_matches = evaluate_query_many_for_profile(source, rows, profile)
        assert (
            tuple(
                row["stable_id"]
                for row, matched in zip(rows, python_matches, strict=True)
                if matched
            )
            == matches
        )
        rust_result = evaluate_artifact_query_many(source, index)
        assert rust_result.matched_row_ids == matches
        assert rust_result.cache_key == (
            pane_id,
            17,
            profile.digest,
            canonical,
        )


@pytest.mark.parametrize("pane_id", sorted(_REQUIRED_PROFILE_PANES))
def test_profile_invalid_query_goldens_have_stable_reference_errors(
    pane_id: str,
) -> None:
    panes = _golden_panes()
    profile = _profile_by_pane_id()[pane_id]
    error_cases = panes[pane_id]["errors"]
    assert isinstance(error_cases, dict)

    for source, expected in error_cases.items():
        assert isinstance(expected, dict)
        with pytest.raises(ProfileQueryError) as python_exc:
            parse_query_for_profile(source, profile)
        assert getattr(python_exc.value, "position", None) == expected["position"]
        assert str(python_exc.value) == expected["message"]

        with pytest.raises(ValueError):
            _canonicalize_artifact_query(source, profile)


def test_patch_artifacts_query_path_no_longer_uses_query_edit_modal() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    guarded_roots = (
        repo_root / "src/sase/ace/tui/actions/patch",
        repo_root / "src/sase/ace/tui/widgets/artifacts",
    )
    offenders = {
        path.relative_to(repo_root).as_posix(): path.read_text(encoding="utf-8")
        for root in guarded_roots
        for path in root.rglob("*.py")
        if "QueryEditModal" in path.read_text(encoding="utf-8")
    }
    assert offenders == {}

    agents_filter_actions = (
        repo_root / "src/sase/ace/tui/actions/agents/_filter_actions.py"
    )
    assert "QueryEditModal" in agents_filter_actions.read_text(encoding="utf-8")
