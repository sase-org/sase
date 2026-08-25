"""Profile-driven Python reference evaluator for Artifacts queries."""

from __future__ import annotations

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
)
from sase.ace.query_profile.profiles import (
    beads_query_schema,
    files_query_schema,
    provider_query_schema,
    stitches_query_schema,
)


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


def test_flat_profile_accepts_bare_boolean_flags_and_canonicalizes_long_form() -> None:
    profile = compile_query_profile(
        ArtifactQuerySchema(
            pane_id="flags",
            boolean=False,
            fields=(
                QueryFieldSpec(key="flag", value_kind="bool", negatable=True),
                QueryFieldSpec(key="title", filterable=False, searchable=True),
            ),
        )
    )
    rows = [
        {"stable_id": "true", "fields": {"flag": True}, "searchable_text": "plain"},
        {"stable_id": "false", "fields": {"flag": False}, "searchable_text": "flag"},
    ]

    assert canonical_query_for_profile("flag", profile) == "flag:true"
    assert canonical_query_for_profile("-flag", profile) == "-flag:true"
    assert evaluate_query_many_for_profile("flag", rows, profile) == [True, False]
    assert evaluate_query_many_for_profile("-flag", rows, profile) == [False, True]


def test_flat_profile_quoted_boolean_key_remains_free_text() -> None:
    profile = compile_query_profile(
        ArtifactQuerySchema(
            pane_id="flags",
            boolean=False,
            fields=(
                QueryFieldSpec(key="flag", value_kind="bool", negatable=True),
                QueryFieldSpec(key="title", filterable=False, searchable=True),
            ),
        )
    )
    rows = [
        {"stable_id": "true", "fields": {"flag": True}, "searchable_text": "plain"},
        {"stable_id": "text", "fields": {"flag": False}, "searchable_text": "flag"},
    ]

    assert canonical_query_for_profile('"flag"', profile) == '"flag"'
    assert canonical_query_for_profile('-"flag"', profile) == '-"flag"'
    assert evaluate_query_many_for_profile('"flag"', rows, profile) == [False, True]
    assert evaluate_query_many_for_profile('-"flag"', rows, profile) == [True, False]


def test_flat_profile_bare_boolean_flags_keep_existing_field_guards() -> None:
    profile = compile_query_profile(
        ArtifactQuerySchema(
            pane_id="flags",
            boolean=False,
            fields=(
                QueryFieldSpec(key="flag", value_kind="bool", negatable=True),
                QueryFieldSpec(key="locked", value_kind="bool"),
            ),
        )
    )

    with pytest.raises(ProfileQueryError, match="flag: may only appear once"):
        parse_query_for_profile("flag -flag", profile)
    with pytest.raises(ProfileQueryError, match="locked: may not be negated"):
        parse_query_for_profile("-locked", profile)


def test_stitches_sidecar_bare_token_is_a_boolean_flag() -> None:
    profile = compile_query_profile(stitches_query_schema())
    rows = [
        {"stable_id": "sidecar", "fields": {"sidecar": True}, "searchable_text": ""},
        {
            "stable_id": "text",
            "fields": {"sidecar": False},
            "searchable_text": "sidecar",
        },
    ]

    assert canonical_query_for_profile("sidecar", profile) == "sidecar:true"
    assert evaluate_query_many_for_profile("sidecar", rows, profile) == [True, False]


def test_flat_profile_date_and_duration_bound_keys_compare_by_host_direction() -> None:
    profile = compile_query_profile(
        ArtifactQuerySchema(
            pane_id="bounds",
            boolean=False,
            fields=(
                QueryFieldSpec(key="after", value_kind="date"),
                QueryFieldSpec(key="before", value_kind="date"),
                QueryFieldSpec(key="since", value_kind="date"),
                QueryFieldSpec(key="until", value_kind="date"),
                QueryFieldSpec(key="created", value_kind="date"),
                QueryFieldSpec(key="min", value_kind="int"),
                QueryFieldSpec(key="max", value_kind="int"),
                QueryFieldSpec(key="exit", value_kind="int"),
            ),
        )
    )
    canonical_after = canonical_query_for_profile("after:2026-08-20T12:00", profile)
    after_epoch = int(canonical_after.removeprefix("after:"))
    rows = [
        {
            "stable_id": "low",
            "fields": {
                "after": after_epoch - 1,
                "before": after_epoch - 1,
                "since": after_epoch - 1,
                "until": after_epoch - 1,
                "created": after_epoch - 1,
                "min": 299,
                "max": 299,
                "exit": 299,
            },
        },
        {
            "stable_id": "equal",
            "fields": {
                "after": after_epoch,
                "before": after_epoch,
                "since": after_epoch,
                "until": after_epoch,
                "created": after_epoch,
                "min": 300,
                "max": 300,
                "exit": 300,
            },
        },
        {
            "stable_id": "high",
            "fields": {
                "after": after_epoch + 1,
                "before": after_epoch + 1,
                "since": after_epoch + 1,
                "until": after_epoch + 1,
                "created": after_epoch + 1,
                "min": 301,
                "max": 301,
                "exit": 301,
            },
        },
    ]

    assert evaluate_query_many_for_profile("after:2026-08-20T12:00", rows, profile) == [
        False,
        True,
        True,
    ]
    assert evaluate_query_many_for_profile("since:2026-08-20T12:00", rows, profile) == [
        False,
        True,
        True,
    ]
    assert evaluate_query_many_for_profile(
        "before:2026-08-20T12:00", rows, profile
    ) == [True, True, False]
    assert evaluate_query_many_for_profile("until:2026-08-20T12:00", rows, profile) == [
        True,
        True,
        False,
    ]
    assert evaluate_query_many_for_profile(
        "created:2026-08-20T12:00", rows, profile
    ) == [False, True, False]
    assert evaluate_query_many_for_profile("min:5m", rows, profile) == [
        False,
        True,
        True,
    ]
    assert evaluate_query_many_for_profile("max:5m", rows, profile) == [
        True,
        True,
        False,
    ]
    assert evaluate_query_many_for_profile("exit:300", rows, profile) == [
        False,
        True,
        False,
    ]


def test_flat_profile_date_and_duration_values_normalize_canonically() -> None:
    profile = compile_query_profile(
        ArtifactQuerySchema(
            pane_id="bounds",
            boolean=False,
            fields=(
                QueryFieldSpec(key="before", value_kind="date"),
                QueryFieldSpec(key="until", value_kind="date"),
                QueryFieldSpec(key="after", value_kind="date"),
                QueryFieldSpec(key="since", value_kind="date"),
                QueryFieldSpec(key="min", value_kind="int"),
                QueryFieldSpec(key="max", value_kind="int"),
                QueryFieldSpec(key="exit", value_kind="int"),
            ),
        )
    )

    before_epoch = canonical_query_for_profile("before:2026-08-20", profile).split(":")[
        1
    ]
    until_epoch = canonical_query_for_profile("until:2026-08-20", profile).split(":")[1]
    after_epoch = canonical_query_for_profile("after:2026-08-20", profile).split(":")[1]
    since_epoch = canonical_query_for_profile("since:2026-08-20", profile).split(":")[1]
    assert before_epoch == until_epoch
    assert after_epoch == since_epoch
    assert int(before_epoch) > int(after_epoch)
    assert canonical_query_for_profile("min:30s max:2h", profile) == ("max:7200 min:30")
    assert canonical_query_for_profile("min:1d", profile) == "min:86400"
    with pytest.raises(ProfileQueryError, match="composite durations"):
        parse_query_for_profile("min:1h30m", profile)
    with pytest.raises(ProfileQueryError, match="must be an integer"):
        parse_query_for_profile("exit:5m", profile)


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


def test_non_repeatable_row_sequences_keep_every_value() -> None:
    profile = compile_query_profile(
        ArtifactQuerySchema(
            pane_id="rows",
            boolean=False,
            fields=(QueryFieldSpec(key="tag", exact_match=True),),
        )
    )
    rows = [{"stable_id": "one", "fields": {"tag": ["alpha", "beta"]}}]

    assert evaluate_query_many_for_profile("tag:beta", rows, profile) == [True]
