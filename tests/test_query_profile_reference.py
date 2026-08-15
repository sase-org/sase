"""Profile-driven Python reference evaluator for Artifacts queries."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.query.profile_reference import (
    ProfileQueryError,
    canonical_query_for_profile,
    evaluate_query_many_for_profile,
    parse_query_for_profile,
)
from sase.ace.query_profile import (
    ArtifactQuerySchema,
    QueryFieldSpec,
    compile_query_profile,
    patches_query_schema,
)
from sase.ace.query_profile.profiles import (
    beads_query_schema,
    files_query_schema,
    provider_query_schema,
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


def test_flat_profile_groups_repeatable_fields_with_or_and_negates() -> None:
    profile = compile_query_profile(beads_query_schema())
    rows = [
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

    assert evaluate_query_many_for_profile(
        "type:task type:phase -status:closed load", rows, profile
    ) == [True, False, False]
    assert evaluate_query_many_for_profile("assignee:ali", rows, profile) == [
        True,
        False,
        False,
    ]


def test_flat_canonical_form_stays_flat_parseable_for_repeated_fields() -> None:
    """Same-key repeats not typed as a comma-list must still canonicalize to
    a flat, comma-joined token -- never boolean ``OR`` syntax, which the
    flat (``boolean=False``) grammar (including the Rust flat parser) can't
    parse back in.
    """

    profile = compile_query_profile(beads_query_schema())
    canonical = canonical_query_for_profile("type:task type:phase", profile)
    assert canonical == "type:task,phase"
    # Round-trips: canonicalizing twice is a fixed point.
    assert canonical_query_for_profile(canonical, profile) == canonical
    # And it still means the same thing as the original.
    assert parse_query_for_profile(canonical, profile) == parse_query_for_profile(
        "type:task type:phase", profile
    )


def test_flat_profile_validates_enum_values_and_negation_support() -> None:
    beads = compile_query_profile(beads_query_schema())
    files = compile_query_profile(files_query_schema())

    with pytest.raises(ProfileQueryError, match="must be one of"):
        parse_query_for_profile("status:not-real", beads)
    assert parse_query_for_profile("-kind:file -free", files)


def test_profile_coerces_typed_fields_and_degrades_malformed_rows() -> None:
    profile = compile_query_profile(
        ArtifactQuerySchema(
            pane_id="typed",
            boolean=False,
            fields=(
                QueryFieldSpec(key="flag", value_kind="bool"),
                QueryFieldSpec(key="count", value_kind="int"),
                QueryFieldSpec(key="since", value_kind="date"),
                QueryFieldSpec(key="title", filterable=False, searchable=True),
            ),
        )
    )
    rows = [
        {
            "stable_id": "good",
            "fields": {
                "flag": "true",
                "count": "3",
                "since": "1970-01-03T00:00:00+00:00",
                "title": "Typed profile",
            },
        },
        {
            "stable_id": "bad",
            "fields": {
                "flag": "not-bool",
                "count": "not-int",
                "since": "not-a-date",
                "title": "Typed profile",
            },
        },
    ]

    assert evaluate_query_many_for_profile(
        "flag:true count:3 since:1970-01-02 typed", rows, profile
    ) == [True, False]


def test_provider_profile_coerces_repeated_string_properties() -> None:
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
            "properties": {
                "tags": '["alpha", "beta"]',
                "title": "Shared evaluator note",
            },
        },
        {
            "stable_id": "two",
            "properties": {"tags": "gamma", "title": "Other note"},
        },
    ]

    assert evaluate_query_many_for_profile("tags:beta shared", rows, profile) == [
        True,
        False,
    ]


def test_query_facade_exposes_profile_reference_entry_points() -> None:
    profile = compile_query_profile(
        ArtifactQuerySchema(
            pane_id="facade",
            boolean=False,
            fields=(QueryFieldSpec(key="title", filterable=False, searchable=True),),
        )
    )
    rows = [{"stable_id": "one", "fields": {"title": "Facade profile"}}]

    expr = query_facade.parse_artifact_query("facade", profile)
    ctx = query_facade.build_artifact_query_context(profile, rows)

    assert query_facade.evaluate_artifact_query(expr, rows[0], profile) is True
    assert query_facade.evaluate_artifact_query_with_context(expr, ctx.rows[0], ctx)
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
