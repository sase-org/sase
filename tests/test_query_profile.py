"""Prove the shared ArtifactQuerySchema/profile preserves every dialect.

Each pane test below exercises the *real* production parser for that
dialect (the Rust-backed Patch parser, or each flat pane's
``parse_*_filter_query``) using exactly the fields/sigils/macros/predicates
declared by the compiled profile, so a profile that drifts from its
dialect's actual behavior fails loudly rather than only diffing against
hand-copied literals.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sase.ace.query.types import to_canonical_string
from sase.ace.query_profile import (
    ArtifactQuerySchema,
    CompiledQueryProfile,
    QueryFieldSpec,
    QueryMacroSpec,
    QueryProfileError,
    QuerySigilSpec,
    beads_query_schema,
    compile_query_profile,
    files_query_schema,
    patches_query_schema,
    plans_query_schema,
    provider_query_schema,
    stitches_query_schema,
)
from sase.ace.query_profile.registry import HOST_PREDICATES
from sase.ace.tui.widgets.artifacts.files_filtering import (
    FilesFilterQueryError,
    parse_files_filter_query,
)
from sase.bead.filter_query import BeadFilterQueryError, parse_bead_filter_query
from sase.core.query_facade import parse_query
from sase.plan_search.filter_query import PlanFilterQueryError, parse_plan_filter_query
from sase.vcs_log.filter_query import CommitFilterQueryError, parse_commit_filter_query


_NOTES_FIXTURE = (
    Path(__file__).parent
    / "ace"
    / "tui"
    / "artifacts_contract"
    / "fixtures"
    / "notes"
    / "provider.yml"
)


# --- Compiler validation -----------------------------------------------------


def _minimal_schema(**overrides: object) -> ArtifactQuerySchema:
    defaults: dict[str, object] = {
        "pane_id": "test",
        "boolean": False,
        "fields": (QueryFieldSpec(key="alpha"),),
    }
    defaults.update(overrides)
    return ArtifactQuerySchema(**defaults)  # type: ignore[arg-type]


def test_compile_rejects_duplicate_field_keys() -> None:
    schema = _minimal_schema(
        fields=(QueryFieldSpec(key="alpha"), QueryFieldSpec(key="alpha"))
    )
    with pytest.raises(QueryProfileError, match="duplicate field key"):
        compile_query_profile(schema)


def test_compile_rejects_enum_without_static_values() -> None:
    schema = _minimal_schema(fields=(QueryFieldSpec(key="alpha", value_kind="enum"),))
    with pytest.raises(QueryProfileError, match="static_values"):
        compile_query_profile(schema)


def test_compile_rejects_negatable_non_filterable_field() -> None:
    schema = _minimal_schema(
        fields=(QueryFieldSpec(key="alpha", filterable=False, negatable=True),)
    )
    with pytest.raises(QueryProfileError, match="filterable"):
        compile_query_profile(schema)


def test_compile_rejects_non_host_sigil() -> None:
    schema = _minimal_schema(sigils=(QuerySigilSpec(sigil="#", field="alpha"),))
    with pytest.raises(QueryProfileError, match="not a host-recognized sigil"):
        compile_query_profile(schema)


def test_compile_rejects_sigil_targeting_undeclared_field() -> None:
    schema = _minimal_schema(sigils=(QuerySigilSpec(sigil="+", field="missing"),))
    with pytest.raises(QueryProfileError, match="undeclared field"):
        compile_query_profile(schema)


def test_compile_rejects_duplicate_sigil() -> None:
    schema = _minimal_schema(
        fields=(QueryFieldSpec(key="alpha"), QueryFieldSpec(key="beta")),
        sigils=(
            QuerySigilSpec(sigil="+", field="alpha"),
            QuerySigilSpec(sigil="+", field="beta"),
        ),
    )
    with pytest.raises(QueryProfileError, match="duplicate sigil"):
        compile_query_profile(schema)


def test_compile_rejects_unknown_predicate() -> None:
    schema = _minimal_schema(predicates=("made_up_predicate",))
    with pytest.raises(QueryProfileError, match="unknown predicate"):
        compile_query_profile(schema)


def test_compile_rejects_any_special_without_full_predicate_set() -> None:
    schema = _minimal_schema(predicates=("error_suffix",), any_special=True)
    with pytest.raises(QueryProfileError, match="any_special requires"):
        compile_query_profile(schema)


def test_compile_accepts_any_special_with_full_predicate_set() -> None:
    schema = _minimal_schema(
        predicates=tuple(sorted(HOST_PREDICATES)), any_special=True
    )
    profile = compile_query_profile(schema)
    assert profile.any_special is True


def test_compile_rejects_macro_with_non_host_trigger() -> None:
    schema = _minimal_schema(
        macros=(QueryMacroSpec(trigger="$", letter="d", field="alpha", value="X"),)
    )
    with pytest.raises(QueryProfileError, match="not host-recognized"):
        compile_query_profile(schema)


def test_compile_rejects_macro_targeting_undeclared_field() -> None:
    schema = _minimal_schema(
        macros=(QueryMacroSpec(trigger="%", letter="d", field="missing", value="X"),)
    )
    with pytest.raises(QueryProfileError, match="undeclared"):
        compile_query_profile(schema)


def test_compile_rejects_duplicate_macro() -> None:
    schema = _minimal_schema(
        macros=(
            QueryMacroSpec(trigger="%", letter="d", field="alpha", value="X"),
            QueryMacroSpec(trigger="%", letter="d", field="alpha", value="Y"),
        )
    )
    with pytest.raises(QueryProfileError, match="duplicate macro"):
        compile_query_profile(schema)


# --- Digest determinism -------------------------------------------------------


def test_digest_is_stable_across_repeated_compiles() -> None:
    schema = patches_query_schema()
    first = compile_query_profile(schema)
    second = compile_query_profile(schema)
    assert first.digest == second.digest
    assert first.to_wire() == second.to_wire()


def test_digest_is_independent_of_authoring_order() -> None:
    forward = _minimal_schema(
        fields=(QueryFieldSpec(key="alpha"), QueryFieldSpec(key="beta")),
        sigils=(
            QuerySigilSpec(sigil="+", field="alpha"),
            QuerySigilSpec(sigil="^", field="beta"),
        ),
    )
    backward = _minimal_schema(
        fields=(QueryFieldSpec(key="beta"), QueryFieldSpec(key="alpha")),
        sigils=(
            QuerySigilSpec(sigil="^", field="beta"),
            QuerySigilSpec(sigil="+", field="alpha"),
        ),
    )
    assert (
        compile_query_profile(forward).digest == compile_query_profile(backward).digest
    )


def test_digest_changes_when_a_field_is_added() -> None:
    base = compile_query_profile(_minimal_schema())
    grown = compile_query_profile(
        _minimal_schema(
            fields=(QueryFieldSpec(key="alpha"), QueryFieldSpec(key="beta"))
        )
    )
    assert base.digest != grown.digest


def test_digest_changes_when_a_field_flag_changes() -> None:
    base = compile_query_profile(_minimal_schema())
    changed = compile_query_profile(
        _minimal_schema(fields=(QueryFieldSpec(key="alpha", searchable=True),))
    )
    assert base.digest != changed.digest


# --- Patches: the boolean dialect --------------------------------------------


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
    for spelling, canonical in (
        ("!!!", "!!!"),
        ("@@@", "@@@"),
        ("$$$", "$$$"),
    ):
        expr = parse_query(spelling)
        # Round-trips through canonicalization without raising; exact
        # spelling is pinned by the frozen query goldens, not duplicated
        # here.
        to_canonical_string(expr)
    star_expr = parse_query("*")
    assert to_canonical_string(star_expr) == "!!! OR @@@ OR $$$"


# --- Stitches: flat, no negation on project, closed host predicates ----------


def _assert_closed_host_predicates(profile: CompiledQueryProfile) -> None:
    assert profile.predicates == tuple(sorted(HOST_PREDICATES))
    assert profile.any_special is True


def test_stitches_profile_has_no_sigils_or_macros() -> None:
    profile = compile_query_profile(stitches_query_schema())
    assert profile.pane_id == "stitches"
    assert profile.boolean is False
    assert profile.sigils == ()
    assert profile.macros == ()
    _assert_closed_host_predicates(profile)


def test_stitches_profile_filterable_fields_are_all_accepted_by_the_parser() -> None:
    profile = compile_query_profile(stitches_query_schema())
    sample_values = {
        "project": "myproj",
        "repo": "myrepo",
        "author": "alice",
        "origin": "stitch",
        "since": "1d",
        "until": "1h",
        "sidecar": "true",
        "merges": "hide",
        "limit": "40",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        parse_commit_filter_query(f"{key}:{value}")  # must not raise


def test_stitches_profile_negatable_fields_match_the_parser() -> None:
    profile = compile_query_profile(stitches_query_schema())
    negatable = set(profile.negatable_fields())
    assert negatable == {"repo", "author", "origin"}
    for key in negatable:
        value = {"repo": "myrepo", "author": "alice", "origin": "stitch"}[key]
        parse_commit_filter_query(f"-{key}:{value}")  # must not raise
    for key in {item.key for item in profile.fields if item.filterable} - negatable:
        value = {
            "project": "myproj",
            "since": "1d",
            "until": "1h",
            "sidecar": "true",
            "merges": "hide",
            "limit": "40",
        }[key]
        with pytest.raises(CommitFilterQueryError):
            parse_commit_filter_query(f"-{key}:{value}")


def test_stitches_profile_project_field_is_not_repeatable() -> None:
    profile = compile_query_profile(stitches_query_schema())
    assert profile.field("project") is not None
    assert profile.field("project").repeatable is False
    with pytest.raises(CommitFilterQueryError, match="does not accept comma"):
        parse_commit_filter_query("project:a,b")


def test_stitches_profile_repeatable_fields_accept_comma_lists() -> None:
    profile = compile_query_profile(stitches_query_schema())
    for key in profile.negatable_fields():
        assert profile.field(key).repeatable is True
    values = parse_commit_filter_query("repo:a,b")
    assert values.repos == ("a", "b")


def test_stitches_profile_search_only_field_is_subject() -> None:
    profile = compile_query_profile(stitches_query_schema())
    search_only = {item.key for item in profile.fields if not item.filterable}
    assert search_only == {"subject"}
    assert profile.field("subject").searchable is True


# --- Beads: every key repeatable and negatable, several closed enums --------


def test_beads_profile_filterable_fields_are_all_accepted_by_the_parser() -> None:
    profile = compile_query_profile(beads_query_schema())
    assert profile.pane_id == "beads"
    assert profile.boolean is False
    assert profile.sigils == () and profile.macros == ()
    _assert_closed_host_predicates(profile)
    sample_values = {
        "type": "task",
        "tier": "epic",
        "status": "open",
        "size": "medium",
        "due": "soon",
        "project": "myproj",
        "assignee": "alice",
        "owner": "alice@example.com",
        "model": "sonnet",
        "has": "plan",
        "bug": "none",
        "label": "bug",
        "since": "1d",
        "until": "1h",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        parse_bead_filter_query(f"{key}:{value}")  # must not raise


def test_beads_profile_every_field_is_repeatable_and_negatable() -> None:
    profile = compile_query_profile(beads_query_schema())
    filterable = tuple(item for item in profile.fields if item.filterable)
    assert all(item.repeatable for item in filterable)
    assert all(item.negatable for item in filterable)
    for key in ("type", "assignee", "since"):
        value = {"type": "task", "assignee": "alice", "since": "1d"}[key]
        parse_bead_filter_query(f"-{key}:{value}")  # must not raise


def test_beads_profile_enum_fields_reject_out_of_vocabulary_values() -> None:
    profile = compile_query_profile(beads_query_schema())
    enum_keys = {item.key for item in profile.fields if item.value_kind == "enum"}
    assert enum_keys == {"type", "tier", "status", "size", "due", "has"}
    for key in enum_keys:
        with pytest.raises(BeadFilterQueryError):
            parse_bead_filter_query(f"{key}:not-a-real-value")


def test_beads_profile_string_fields_accept_arbitrary_values() -> None:
    profile = compile_query_profile(beads_query_schema())
    string_keys = {
        item.key
        for item in profile.fields
        if item.filterable and item.value_kind == "string"
    }
    assert string_keys == {"project", "assignee", "owner", "model", "bug", "label"}
    for key in string_keys:
        parse_bead_filter_query(f"{key}:anything-goes")  # must not raise


def test_beads_profile_search_only_fields_match_the_free_text_hint() -> None:
    profile = compile_query_profile(beads_query_schema())
    search_only = {item.key for item in profile.fields if not item.filterable}
    assert search_only == {"id", "title", "body", "refs"}
    assert profile.free_text_hint == "id, title, body, refs (AND)"


# --- Plans: nothing enum-enforced, since/until are singles -------------------


def test_plans_profile_filterable_fields_are_all_accepted_by_the_parser() -> None:
    profile = compile_query_profile(plans_query_schema())
    assert profile.pane_id == "ref:plan"
    assert profile.boolean is False
    assert profile.sigils == () and profile.macros == ()
    _assert_closed_host_predicates(profile)
    sample_values = {
        "kind": "proposal",
        "status": "anything-goes",
        "tier": "epic",
        "project": "myproj",
        "since": "1d",
        "until": "1h",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        parse_plan_filter_query(f"{key}:{value}")  # must not raise


def test_plans_profile_declares_no_enum_validated_fields() -> None:
    profile = compile_query_profile(plans_query_schema())
    assert not any(item.value_kind == "enum" for item in profile.fields)
    # kind/status/tier all accept values outside their completion hints.
    for key in ("kind", "status", "tier"):
        parse_plan_filter_query(f"{key}:totally-made-up")  # must not raise


def test_plans_profile_since_until_are_not_repeatable() -> None:
    profile = compile_query_profile(plans_query_schema())
    assert profile.field("since").repeatable is False
    assert profile.field("until").repeatable is False
    with pytest.raises(PlanFilterQueryError, match="may only appear once"):
        parse_plan_filter_query("since:1d since:2d")


def test_plans_profile_search_only_fields_match_the_free_text_hint() -> None:
    profile = compile_query_profile(plans_query_schema())
    search_only = {item.key for item in profile.fields if not item.filterable}
    assert search_only == {"title", "body", "path"}
    assert profile.free_text_hint == "title, body, path (AND)"


# --- Files: negatable flat fields, kind/origin enum-enforced -----------------


def test_files_profile_filterable_fields_are_all_accepted_by_the_parser() -> None:
    profile = compile_query_profile(files_query_schema())
    assert profile.pane_id == "files"
    assert profile.boolean is False
    assert profile.sigils == () and profile.macros == ()
    _assert_closed_host_predicates(profile)
    sample_values = {
        "kind": "file",
        "project": "myproj",
        "agent": "bob",
        "workflow": "flow",
        "origin": "created",
        "since": "2024-01-01",
        "until": "2024-02-01",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        parse_files_filter_query(f"{key}:{value}")  # must not raise


def test_files_profile_negatable_fields_match_the_parser() -> None:
    profile = compile_query_profile(files_query_schema())
    assert set(profile.negatable_fields()) == {
        "agent",
        "kind",
        "origin",
        "project",
        "since",
        "until",
        "workflow",
    }
    for key, value in {
        "agent": "bob",
        "kind": "file",
        "origin": "created",
        "project": "myproj",
        "since": "2024-01-01",
        "until": "2024-02-01",
        "workflow": "flow",
    }.items():
        parse_files_filter_query(f"-{key}:{value}")  # must not raise
    assert parse_files_filter_query("-freetext").excluded_text == ("freetext",)


def test_files_profile_enum_fields_reject_out_of_vocabulary_values() -> None:
    profile = compile_query_profile(files_query_schema())
    enum_keys = {item.key for item in profile.fields if item.value_kind == "enum"}
    assert enum_keys == {"kind", "origin"}
    for key in enum_keys:
        with pytest.raises(FilesFilterQueryError):
            parse_files_filter_query(f"{key}:not-a-real-value")


def test_files_profile_search_only_fields_match_the_free_text_hint() -> None:
    profile = compile_query_profile(files_query_schema())
    search_only = {item.key for item in profile.fields if not item.filterable}
    assert search_only == {"label", "stored_path", "source_path"}
    assert profile.free_text_hint == "label, stored path, source path (AND)"


# --- Synthetic provider: proves genericity with zero provider-side Python ---


def test_provider_query_schema_derives_fields_from_the_notes_fixture() -> None:
    spec = yaml.safe_load(_NOTES_FIXTURE.read_text(encoding="utf-8"))
    profile = compile_query_profile(provider_query_schema("notes", spec))
    assert profile.pane_id == "ref:notes"
    assert profile.boolean is False
    assert profile.sigils == () and profile.macros == ()
    _assert_closed_host_predicates(profile)
    # ``related`` and ``family`` back the fixture's declared relations: a
    # ``ref.relations[].source`` must name a declared ``ref.properties`` key, so
    # relation sources are ordinary queryable fields like any other property.
    assert {item.key for item in profile.fields} == {
        "title",
        "status",
        "related",
        "family",
    }
    assert all(item.value_kind == "string" for item in profile.fields)
    assert all(item.searchable for item in profile.fields)
    assert all(item.negatable for item in profile.fields)
    assert profile.free_text_hint == "family, related, status, title (AND)"


def test_provider_query_schema_handles_missing_and_malformed_specs() -> None:
    assert compile_query_profile(provider_query_schema("empty", None)).fields == ()
    assert compile_query_profile(provider_query_schema("empty", {})).fields == ()
    malformed = {"ref": {"properties": "not-a-mapping"}}
    assert compile_query_profile(provider_query_schema("bad", malformed)).fields == ()


def test_provider_query_schema_degrades_unknown_types_to_string() -> None:
    spec = {
        "ref": {
            "properties": {
                "created": {"type": "datetime"},
                "tags": {"type": "string_list"},
                "mystery": {"type": "some_future_type"},
            }
        }
    }
    profile = compile_query_profile(provider_query_schema("kind", spec))
    assert profile.field("created").value_kind == "date"
    assert profile.field("tags").value_kind == "string"
    assert profile.field("tags").repeatable is True
    assert profile.field("mystery").value_kind == "string"


def test_provider_query_schema_grants_only_closed_host_predicates() -> None:
    spec = {"ref": {"properties": {"anything": {"type": "string"}}}}
    schema = provider_query_schema("kind", spec)
    assert schema.sigils == ()
    assert schema.macros == ()
    assert schema.predicates == tuple(sorted(HOST_PREDICATES))
    assert schema.any_special is True


# --- Cross-pane invariants ----------------------------------------------------


@pytest.mark.parametrize(
    "schema_factory",
    [
        patches_query_schema,
        stitches_query_schema,
        beads_query_schema,
        plans_query_schema,
        files_query_schema,
    ],
)
def test_every_builtin_profile_compiles_without_error(schema_factory) -> None:
    profile = compile_query_profile(schema_factory())
    assert isinstance(profile, CompiledQueryProfile)
    assert profile.digest
    assert profile.to_wire()["digest"] == profile.digest


def test_every_builtin_profile_has_a_unique_pane_id() -> None:
    all_ids = [
        factory().pane_id
        for factory in (
            patches_query_schema,
            stitches_query_schema,
            beads_query_schema,
            plans_query_schema,
            files_query_schema,
        )
    ]
    assert len(all_ids) == len(set(all_ids)) == 5
