"""Compatibility coverage for profile-driven Artifacts query evaluation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.patch import Patch
from sase.ace.query.profile_reference import (
    ProfileQueryError,
    coerce_artifact_query_rows,
    evaluate_query_many_for_profile,
    patch_query_stable_id,
    parse_query_for_profile,
)
from sase.ace.query_profile import (
    ArtifactQuerySchema,
    QueryFieldSpec,
    compile_query_profile,
    patches_query_schema,
)
from sase.core import parser_facade, query_facade

_SAMPLE_PROJECT_TEXT = """\
NAME: example
DESCRIPTION: Example feature.
PARENT:
PR:
STATUS: WIP

NAME: child
DESCRIPTION: Child of example.
PARENT: example
PR:
STATUS: WIP
"""


def test_patch_profile_coerces_transitive_ancestor_chain() -> None:
    profile = compile_query_profile(patches_query_schema())
    patches = [
        Patch("grand", "root", None, status="WIP", file_path="/tmp/proj/proj.sase"),
        Patch("mid", "mid", "grand", status="WIP", file_path="/tmp/proj/proj.sase"),
        Patch("kid", "kid", "mid", status="WIP", file_path="/tmp/proj/proj.sase"),
    ]

    assert evaluate_query_many_for_profile("ancestor:grand", patches, profile) == [
        True,
        True,
        True,
    ]
    assert evaluate_query_many_for_profile("ancestor:mid", patches, profile) == [
        False,
        True,
        True,
    ]


def test_patch_profile_stable_id_is_project_qualified() -> None:
    profile = compile_query_profile(patches_query_schema())
    patches = [
        Patch("same", "one", None, status="WIP", file_path="/tmp/one/one.sase"),
        Patch("same", "two", None, status="WIP", file_path="/tmp/two/two.sase"),
    ]

    rows = coerce_artifact_query_rows(profile, patches)

    assert rows[0].stable_id == patch_query_stable_id(patches[0])
    assert rows[1].stable_id == patch_query_stable_id(patches[1])
    assert rows[0].stable_id != rows[1].stable_id


def test_query_facade_keeps_profile_batch_compatibility_helper() -> None:
    profile = compile_query_profile(
        ArtifactQuerySchema(
            pane_id="facade",
            boolean=False,
            fields=(QueryFieldSpec(key="title", filterable=False, searchable=True),),
        )
    )
    rows = [{"stable_id": "one", "fields": {"title": "Facade profile"}}]

    assert query_facade.evaluate_artifact_query_many("facade", rows, profile) == [True]


def test_boolean_profile_honors_sigils_macros_predicates_and_search_text() -> None:
    profile = compile_query_profile(patches_query_schema())
    rows = [
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
    ]

    assert evaluate_query_many_for_profile(
        "+sase AND %y AND @@@ AND needle", rows, profile
    ) == [
        True,
        False,
    ]
    assert evaluate_query_many_for_profile("!!", rows, profile) == [True, True]
    assert evaluate_query_many_for_profile("*", rows, profile) == [True, False]


@pytest.mark.parametrize("query", ['"example"', "%w", "name:example", "!!"])
def test_patch_profile_reference_matches_current_rust_batch(
    tmp_path: Path,
    query: str,
) -> None:
    sample_project = tmp_path / "sample.sase"
    sample_project.write_text(_SAMPLE_PROJECT_TEXT, encoding="utf-8")
    specs = parser_facade.parse_project_file(str(sample_project))
    profile = compile_query_profile(patches_query_schema())

    assert evaluate_query_many_for_profile(query, specs, profile) == (
        query_facade.evaluate_query_many(query, specs)
    )


@pytest.mark.parametrize(
    ("query", "position"),
    [("unknown:value", 0), ("status:", 7)],
)
def test_patch_profile_reference_error_positions_match_legacy_parser(
    query: str,
    position: int,
) -> None:
    profile = compile_query_profile(patches_query_schema())
    with pytest.raises(ValueError):
        query_facade.parse_query(query)
    with pytest.raises(ProfileQueryError) as python_exc:
        parse_query_for_profile(query, profile)

    assert python_exc.value.position == position
