"""Pin the Artifacts Agent pane query profile."""

from __future__ import annotations

import pytest

from sase.ace.query.profile_reference import (
    ProfileQueryError,
    canonical_query_for_profile,
    parse_query_for_profile,
)
from sase.ace.query_profile import (
    HOST_PREDICATES,
    ArtifactQuerySchema,
    QueryFieldSpec,
    agents_live_query_schema,
    agents_query_schema,
    compile_query_profile,
)

from tests._query_profile_helpers import assert_closed_host_predicates


def test_agents_profile_filterable_fields_are_all_accepted_by_the_parser() -> None:
    profile = compile_query_profile(agents_query_schema())
    assert profile.pane_id == "agents"
    assert profile.boolean is True
    assert profile.sigils == () and profile.macros == ()
    assert_closed_host_predicates(profile)
    sample_values = {
        "name": "sase-r8.9.land",
        "kind": "workflow-child",
        "family": "research.12",
        "clan": "athena.sase-8t",
        "tribe": "epic",
        "role": "code",
        "workflow": "review",
        "parent": "20260822161630",
        "project": "sase",
        "state": "dismissed",
        "status": "failed",
        "hidden": "true",
        "dismissed": "true",
        "revivable": "true",
        "historically_viewable": "true",
        "durably_revivable": "true",
        "restartable": "false",
        "attention": "true",
        "retry": "false",
        "attempt": "2",
        "model": "gpt-5.6-sol",
        "provider": "codex",
        "relation": "read",
        "artifact": "plan:202608/example.md",
        "linked": "true",
        "since": "7d",
        "until": "2026-08-01",
        "after": "2h",
        "before": "today",
        "min": "5m",
        "max": "2h",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        parse_query_for_profile(f"{key}:{value}", profile)  # must not raise


def test_agents_profile_wire_payload_survives_shared_field_refactor() -> None:
    profile = compile_query_profile(agents_query_schema())
    legacy_profile = compile_query_profile(
        _legacy_agents_schema(profile.field("relation").static_values)
    )

    assert profile.digest == legacy_profile.digest
    assert profile.to_wire() == legacy_profile.to_wire()


def test_agents_profile_string_field_matching_shapes() -> None:
    profile = compile_query_profile(agents_query_schema())
    exact = {
        item.key
        for item in profile.fields
        if item.filterable and item.value_kind == "string" and item.exact_match
    }
    substring = {
        item.key
        for item in profile.fields
        if item.filterable and item.value_kind == "string" and not item.exact_match
    }
    assert exact == {"name", "family", "clan", "project", "artifact"}
    assert substring == {"role", "workflow", "parent", "model"}
    assert profile.field("role").static_values == ("code", "plan", "mon")


def test_agents_profile_enum_fields_pin_static_vocabularies() -> None:
    profile = compile_query_profile(agents_query_schema())
    assert profile.field("kind").static_values == (
        "agent",
        "member",
        "family",
        "clan",
        "workflow",
        "workflow-child",
    )
    assert profile.field("state").static_values == ("active", "done", "dismissed")
    assert profile.field("status").static_values == (
        "STARTING",
        "RUNNING",
        "WAITING",
        "DONE",
        "FAILED",
        "COMPLETED",
    )
    assert profile.field("tribe").static_values == ("epic", "chop", "research")
    assert profile.field("provider").static_values == (
        "agy",
        "claude",
        "codex",
        "grok",
        "muse",
        "opencode",
        "qwen",
    )
    assert "read" in profile.field("relation").static_values
    assert "implements" in profile.field("relation").static_values

    assert canonical_query_for_profile("status:failed", profile) == "status:FAILED"
    assert canonical_query_for_profile("relation:read", profile) == "relation:read"
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("kind:not-real", profile)
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("provider:not-real", profile)
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("relation:not-real", profile)


def test_agents_profile_boolean_fields_require_explicit_values() -> None:
    profile = compile_query_profile(agents_query_schema())
    bool_keys = {
        item.key
        for item in profile.fields
        if item.filterable and item.value_kind == "bool"
    }
    assert bool_keys == {
        "hidden",
        "dismissed",
        "revivable",
        "historically_viewable",
        "durably_revivable",
        "restartable",
        "attention",
        "retry",
        "linked",
    }
    for key in bool_keys:
        assert canonical_query_for_profile(f"{key}:true", profile) == f"{key}:true"
        assert canonical_query_for_profile(key, profile) == f'"{key}"'
        with pytest.raises(ProfileQueryError):
            parse_query_for_profile(f"{key}:yes", profile)


def test_agents_profile_time_fields_document_month_minute_collision() -> None:
    profile = compile_query_profile(agents_query_schema())
    date_hints = {
        profile.field("since").hint,
        profile.field("until").hint,
        profile.field("after").hint,
        profile.field("before").hint,
    }
    duration_hints = {profile.field("min").hint, profile.field("max").hint}
    assert all("Nm means months" in hint for hint in date_hints)
    assert all("Nm means minutes" in hint for hint in duration_hints)
    assert profile.field("attempt").value_kind == "int"


def test_agents_profile_search_only_fields_match_the_free_text_hint() -> None:
    profile = compile_query_profile(agents_query_schema())
    search_only = {item.key for item in profile.fields if not item.filterable}
    assert search_only == {"label", "text"}
    assert set(profile.searchable_fields()) == {"name", "label", "text"}
    assert profile.free_text_hint == "name, label, text metadata (implicit AND)"
    assert profile.identity_field == "name"


def test_agents_live_profile_filterable_fields_are_all_accepted_by_parser() -> None:
    profile = compile_query_profile(agents_live_query_schema())
    assert profile.pane_id == "agents-live"
    assert profile.boolean is True
    assert profile.sigils == () and profile.macros == ()
    assert profile.predicates == ()
    assert profile.any_special is False
    sample_values = {
        "name": "sase-zf.1--code",
        "kind": "workflow-child",
        "family": "research.12",
        "clan": "athena.sase-zf",
        "project": "sase",
        "role": "code",
        "workflow": "review",
        "model": "gpt-5.6-sol",
        "provider": "codex",
        "status": "QUESTION",
        "attempt": "2",
        "hidden": "true",
        "attention": "true",
        "retry": "false",
        "cl": "sase-zf",
        "machine": "here",
        "tribe": "pinned",
        "pinned": "true",
        "unread": "false",
        "needs": "input",
        "source": "axe",
        "since": "7d",
        "until": "2026-08-01",
        "after": "2h",
        "before": "today",
        "min": "5m",
        "max": "2h",
    }
    filterable_keys = {item.key for item in profile.fields if item.filterable}
    assert filterable_keys == set(sample_values)
    for key, value in sample_values.items():
        parse_query_for_profile(f"{key}:{value}", profile)  # must not raise


def test_agents_live_profile_matching_shapes_are_operational_not_archive() -> None:
    profile = compile_query_profile(agents_live_query_schema())
    exact = {
        item.key
        for item in profile.fields
        if item.filterable and item.value_kind == "string" and item.exact_match
    }
    substring = {
        item.key
        for item in profile.fields
        if item.filterable and item.value_kind == "string" and not item.exact_match
    }
    bool_keys = {
        item.key
        for item in profile.fields
        if item.filterable and item.value_kind == "bool"
    }

    assert exact == {"name", "family", "clan", "project", "machine", "tribe"}
    assert substring == {"role", "workflow", "model", "cl"}
    assert bool_keys == {"hidden", "attention", "retry", "pinned", "unread"}
    assert profile.field("role").static_values == ("code", "plan", "mon")
    assert profile.field("needs").static_values == ("input",)
    assert profile.field("source").static_values == ("axe", "manual")

    for removed in (
        "state",
        "dismissed",
        "revivable",
        "historically_viewable",
        "durably_revivable",
        "restartable",
        "linked",
        "relation",
        "artifact",
        "label",
    ):
        assert profile.field(removed) is None


def test_agents_live_profile_enum_fields_pin_static_vocabularies() -> None:
    profile = compile_query_profile(agents_live_query_schema())
    assert profile.field("kind").static_values == (
        "agent",
        "member",
        "family",
        "clan",
        "workflow",
        "workflow-child",
    )
    assert profile.field("status").static_values == (
        "STARTING",
        "RUNNING",
        "RETRYING",
        "ANSWERED",
        "WAITING",
        "QUEUED",
        "QUESTION",
        "WAITING INPUT",
        "PLAN",
        "TALE",
        "EPIC",
        "PLAN APPROVED",
        "TALE APPROVED",
        "EPIC APPROVED",
        "PLAN COMMITTED",
        "WORKING PLAN",
        "WORKING TALE",
        "DONE",
        "FAILED",
        "FAILED (RETRIED)",
        "COMPLETED",
        "PLAN DONE",
        "TALE DONE",
        "PLAN REJECTED",
        "EPIC CREATED",
        "STOPPED",
        "FEEDBACK",
    )
    assert profile.field("provider").static_values == (
        "agy",
        "claude",
        "codex",
        "grok",
        "muse",
        "opencode",
        "qwen",
    )

    assert (
        canonical_query_for_profile('status:"plan approved"', profile)
        == 'status:"PLAN APPROVED"'
    )
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("kind:not-real", profile)
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("provider:not-real", profile)
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("source:not-real", profile)


def test_agents_live_profile_removed_legacy_spellings_stay_rejected() -> None:
    profile = compile_query_profile(agents_live_query_schema())

    for query in ("age:2h", "age>2h", "type:run", "type:workflow"):
        with pytest.raises(ProfileQueryError):
            parse_query_for_profile(query, profile)

    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("!!!", profile)
    with pytest.raises(ProfileQueryError):
        parse_query_for_profile("tribe:", profile)


def test_agents_live_profile_search_only_fields_match_the_free_text_hint() -> None:
    profile = compile_query_profile(agents_live_query_schema())
    search_only = {item.key for item in profile.fields if not item.filterable}
    assert search_only == {"text"}
    assert set(profile.searchable_fields()) == {"name", "cl", "text"}
    assert profile.free_text_hint == "name, cl, text metadata (implicit AND)"
    assert profile.identity_field == "name"


def _legacy_agents_schema(
    relation_values: tuple[str, ...] | None,
) -> ArtifactQuerySchema:
    return ArtifactQuerySchema(
        pane_id="agents",
        boolean=True,
        fields=(
            _legacy_agents_enum_fields(relation_values or ())
            + _legacy_agents_exact_string_fields()
            + _legacy_agents_string_fields()
            + _legacy_agents_bool_fields()
            + _legacy_agents_date_fields()
            + _legacy_agents_int_fields()
            + _legacy_agents_search_only_fields()
        ),
        predicates=tuple(sorted(HOST_PREDICATES)),
        any_special=True,
        free_text_hint="name, label, text metadata (implicit AND)",
        identity_field="name",
    )


def _legacy_agents_enum_fields(
    relation_values: tuple[str, ...],
) -> tuple[QueryFieldSpec, ...]:
    return (
        QueryFieldSpec(
            key="kind",
            value_kind="enum",
            static_values=(
                "agent",
                "member",
                "family",
                "clan",
                "workflow",
                "workflow-child",
            ),
            hint="agent, member, family, clan, workflow, or workflow-child",
        ),
        QueryFieldSpec(
            key="tribe",
            value_kind="enum",
            static_values=("epic", "chop", "research"),
            hint="clan tribe: epic, chop, or research",
        ),
        QueryFieldSpec(
            key="state",
            value_kind="enum",
            static_values=("active", "done", "dismissed"),
            hint="active, done, or dismissed",
        ),
        QueryFieldSpec(
            key="status",
            value_kind="enum",
            static_values=(
                "STARTING",
                "RUNNING",
                "WAITING",
                "DONE",
                "FAILED",
                "COMPLETED",
            ),
            hint="STARTING, RUNNING, WAITING, DONE, FAILED, or COMPLETED",
        ),
        QueryFieldSpec(
            key="provider",
            value_kind="enum",
            static_values=(
                "agy",
                "claude",
                "codex",
                "grok",
                "muse",
                "opencode",
                "qwen",
            ),
            hint="LLM provider; static values merge with observed facets",
        ),
        QueryFieldSpec(
            key="relation",
            value_kind="enum",
            static_values=relation_values,
            hint="artifact-link relation slug",
        ),
    )


def _legacy_agents_exact_string_fields() -> tuple[QueryFieldSpec, ...]:
    return (
        QueryFieldSpec(
            key="name",
            exact_match=True,
            searchable=True,
            hint="agent name or canonical global name",
        ),
        QueryFieldSpec(
            key="family",
            exact_match=True,
            hint="family name derived from the agent name",
        ),
        QueryFieldSpec(
            key="clan",
            exact_match=True,
            hint="clan name or agent_clan",
        ),
        QueryFieldSpec(
            key="project",
            exact_match=True,
            hint="project key or display name",
        ),
        QueryFieldSpec(
            key="artifact",
            exact_match=True,
            hint="canonical artifact ref linked to the agent",
        ),
    )


def _legacy_agents_string_fields() -> tuple[QueryFieldSpec, ...]:
    return (
        QueryFieldSpec(
            key="role",
            static_values=("code", "plan", "mon"),
            hint="member role suffix such as code, plan, or mon",
        ),
        QueryFieldSpec(key="workflow", hint="workflow name"),
        QueryFieldSpec(key="parent", hint="parent timestamp"),
        QueryFieldSpec(
            key="model",
            hint="model name; static values merge with observed facets",
        ),
    )


def _legacy_agents_bool_fields() -> tuple[QueryFieldSpec, ...]:
    return tuple(
        QueryFieldSpec(
            key=key,
            value_kind="bool",
            static_values=("true", "false"),
            hint=hint,
        )
        for key, hint in (
            ("hidden", "artifact-index hidden flag"),
            ("dismissed", "true when state is dismissed"),
            ("revivable", "dismissed with durable archive inputs"),
            ("historically_viewable", "archive has enough data to inspect"),
            ("durably_revivable", "archive has enough data to restore"),
            ("restartable", "archive has prompt and model parameters"),
            ("attention", "failed or waiting on input"),
            ("retry", "participates in a retry chain"),
            ("linked", "true when at least one artifact link touches the agent"),
        )
    )


def _legacy_agents_date_fields() -> tuple[QueryFieldSpec, ...]:
    date_hint = "Nh/Nd/Nw/Nm, today, YYYY-MM-DD; Nm means months"
    return tuple(
        QueryFieldSpec(
            key=key,
            value_kind="date",
            hint=hint,
        )
        for key, hint in (
            ("since", f"started at or after; {date_hint}"),
            ("until", f"started at or before; {date_hint}"),
            ("after", f"finished at or after; {date_hint}"),
            ("before", f"finished at or before; {date_hint}"),
        )
    )


def _legacy_agents_int_fields() -> tuple[QueryFieldSpec, ...]:
    duration_hint = "seconds or Ns/Nm/Nh/Nd; Nm means minutes"
    return (
        QueryFieldSpec(
            key="min",
            value_kind="int",
            hint=f"runtime at least; {duration_hint}",
        ),
        QueryFieldSpec(
            key="max",
            value_kind="int",
            hint=f"runtime at most; {duration_hint}",
        ),
        QueryFieldSpec(
            key="attempt",
            value_kind="int",
            hint="retry attempt number, equality-only",
        ),
    )


def _legacy_agents_search_only_fields() -> tuple[QueryFieldSpec, ...]:
    return tuple(
        QueryFieldSpec(key=key, filterable=False, searchable=True, hint="free text")
        for key in ("label", "text")
    )
