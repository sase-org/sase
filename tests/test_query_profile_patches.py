"""Prove the patches query profile matches the boolean parser dialect."""

from __future__ import annotations

import pytest

from sase.ace.query import canonical_query_for_profile
from sase.ace.query.types import to_canonical_string
from sase.ace.query_profile import compile_query_profile, patches_query_schema
from sase.core.query_facade import parse_query


def test_patches_profile_is_boolean_with_the_six_property_keys() -> None:
    profile = compile_query_profile(patches_query_schema())
    assert profile.pane_id == "patches"
    assert profile.boolean is True
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == {
        "status",
        "project",
        "ancestor",
        "name",
        "sibling",
        "origin",
    }
    # None of Patch's property keys are enum-validated at parse time.
    assert all(
        item.value_kind == "string" for item in profile.fields if item.filterable
    )
    assert profile.identity_field == "name"


def test_patches_profile_searchable_fields_match_the_haystack() -> None:
    profile = compile_query_profile(patches_query_schema())
    assert set(profile.searchable_fields()) == {
        "status",
        "project",
        "name",
        "origin",
        "description",
        "refs",
        "parent",
        "pr_url",
        "notes",
    }


def test_patches_profile_sigils_match_the_tokenizer() -> None:
    profile = compile_query_profile(patches_query_schema())
    sigil_map = {item.sigil: item.field for item in profile.sigils}
    assert sigil_map == {"+": "project", "^": "ancestor", "~": "sibling", "&": "name"}
    for sigil, field in sigil_map.items():
        expr = parse_query(f"{sigil}widget")
        assert to_canonical_string(expr) == f"{field}:widget"


def test_patches_profile_macros_match_the_status_shorthands() -> None:
    profile = compile_query_profile(patches_query_schema())
    macro_map = {(item.trigger, item.letter): item.value for item in profile.macros}
    expected = {
        "d": "DRAFT",
        "m": "MAILED",
        "r": "REVERTED",
        "s": "SUBMITTED",
        "w": "WIP",
        "y": "READY",
    }
    assert macro_map == {("%", letter): value for letter, value in expected.items()}
    for letter, value in expected.items():
        expr = parse_query(f"%{letter}")
        assert to_canonical_string(expr) == f"status:{value}"


def test_patches_profile_predicates_match_the_zero_arg_shorthands() -> None:
    profile = compile_query_profile(patches_query_schema())
    assert set(profile.predicates) == {
        "error_suffix",
        "running_agent",
        "running_process",
    }
    assert profile.any_special is True
    for spelling in ("!!!", "@@@", "$$$"):
        expr = parse_query(spelling)
        # Round-trips through canonicalization without raising; exact
        # spelling is pinned by the frozen query goldens, not duplicated
        # here.
        to_canonical_string(expr)
    star_expr = parse_query("*")
    assert to_canonical_string(star_expr) == "!!! OR @@@ OR $$$"


def test_patches_profile_dotted_name_canonical_round_trip_is_parseable() -> None:
    profile = compile_query_profile(patches_query_schema())

    canonical = canonical_query_for_profile('name:"sase-r8.9"', profile)
    assert canonical == "name:sase-r8.9"
    assert canonical_query_for_profile(canonical, profile) == canonical


@pytest.mark.parametrize(
    ("source", "canonical"),
    [
        ('"feature"', '"feature"'),
        ("%w", "status:WIP"),
        ("+sase", "project:sase"),
        ("^grand", "ancestor:grand"),
        ("~kid", "sibling:kid"),
        ("&kid__1", "name:kid__1"),
        ("!!!", "!!!"),
        ("@@@", "@@@"),
        ("$$$", "$$$"),
        ("+sase AND (%w OR %y)", "project:sase AND (status:WIP OR status:READY)"),
    ],
)
def test_patches_profile_existing_boolean_queries_keep_canonical_form(
    source: str, canonical: str
) -> None:
    profile = compile_query_profile(patches_query_schema())

    assert canonical_query_for_profile(source, profile) == canonical
    assert canonical_query_for_profile(canonical, profile) == canonical
