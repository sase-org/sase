"""Coverage for the plans filter query language and in-memory index."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from hypothesis import given, strategies as st

from sase.ace.tui.widgets.artifacts.plans_data import (
    PlanProposal,
    PlansSnapshot,
    ProjectArchive,
    ProjectIssue,
)
from sase.ace.tui.widgets.artifacts.plans_filtering import (
    _PlanFilterRecord,
    build_plan_filter_index,
    compile_plan_matcher,
)
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.notifications.models import Notification
from sase.plan_search.filter_query import (
    PlanFilterQueryError,
    PlanFilterValues,
    parse_plan_filter_query,
    plan_completion_context,
    to_query_string,
    to_query_tokens,
)
from sase.plan_search.model import Plan, PlanSearchMatch
from sase.vcs_log.dates import parse_time_bound


def _record(**changes: object) -> _PlanFilterRecord:
    values: dict[str, object] = {
        "kind": "epic",
        "project": "sase",
        "project_display_name": "SASE",
        "project_labels": frozenset(("sase",)),
        "status_labels": frozenset(("open", "ready")),
        "tier_labels": frozenset(("epic",)),
        "timestamp": 200,
        "haystack": ("sase-6t", "plans filter bar", "search index"),
        "identity": "sase-6t",
        "option_id": "epic:sase-6t",
    }
    values.update(changes)
    return _PlanFilterRecord(**values)  # type: ignore[arg-type]


def _snapshot() -> PlansSnapshot:
    proposal = PlanProposal(
        project="sase",
        notification=Notification(
            id="proposal-1",
            timestamp="2026-07-01T12:00:00+00:00",
            sender="planner",
        ),
        title="Ship the plan browser",
        tier="epic",
        age="2m ago",
        timestamp="2026-07-01T12:00:00+00:00",
        plan_path="/plans/proposal.md",
        content="# Ship the plan browser",
        frontmatter={
            "tier": "epic",
            "status": "wip",
            "goal": "Make plan filtering instant",
        },
        body="# Browser\n\nCompletion-assisted filtering.",
        agent="sase-6t.plan",
        provider_model="codex/gpt-5",
    )
    epic = Issue(
        id="sase-6t",
        title="Plans filter bar",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        description="Add live plan filtering.",
        notes="Keep the keystroke path read-only.",
        assignee="bryan",
        created_at="2026-07-02T09:00:00Z",
        is_ready_to_work=True,
    )
    phase = Issue(
        id="sase-6t.1",
        title="Build the search index",
        status=Status.OPEN,
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        description="Prefold every markdown body once.",
        created_at="not-a-timestamp",
    )
    launched = Issue(
        id="sase-7x",
        title="Already launched epic",
        status=Status.OPEN,
        issue_type=IssueType.PLAN,
        tier=BeadTier.PLAN,
        created_at="2026-07-03T09:00:00Z",
        is_ready_to_work=True,
    )
    archive_match = PlanSearchMatch(
        plan=Plan(
            source="repo",
            kind="tale",
            path="/plans/202607/archive.md",
            relpath="202607/archive.md",
            name="archive",
            title="Archived rollout",
            status="done",
            created_at="2026-07-04T10:00:00+00:00",
            prompt_link="",
            summary="Completion shipped.",
            body="# Rollout\n\nThe filter bar is live.",
            frontmatter={
                "tier": "epic",
                "status": "approved",
                "goal": "Record the completed rollout",
            },
        ),
        matched_fields=[],
        score=0.0,
    )
    return PlansSnapshot(
        project=None,
        projects=("sase",),
        display_names={"sase": "Structured Agentic Software Engineering"},
        beads_dirs={"sase": "/plans/beads"},
        plans_roots={"sase": "/plans"},
        workspace_dirs={"sase": "/workspace"},
        proposals=(proposal,),
        epics=(ProjectIssue("sase", epic), ProjectIssue("sase", launched)),
        phases_by_epic={
            ("sase", epic.id): (ProjectIssue("sase", phase),),
            ("sase", launched.id): (),
        },
        ready_ids=frozenset({("sase", epic.id)}),
        blocked_ids=frozenset({("sase", phase.id)}),
        archive=(ProjectArchive("sase", archive_match),),
        source_key=("snapshot", 1),
        errors={},
        archive_truncated=True,
    )


def test_parse_empty_query_uses_defaults() -> None:
    values = parse_plan_filter_query("  \t\n")

    assert values == PlanFilterValues()
    assert values.is_empty is True


def test_parse_every_token_kind_and_case_insensitive_keys() -> None:
    values = parse_plan_filter_query(
        'KIND:epic,phase kind:"archive" '
        'STATUS:open,ready status:"Needs Review" '
        'tier:epic,plan project:sase project:"SASE Core" '
        "since:2026-07-01 until:2026-07-18T08:30 "
        'filter "live preview"'
    )

    assert values.kinds == ("epic", "phase", "archive")
    assert values.statuses == ("open", "ready", "Needs Review")
    assert values.tiers == ("epic", "plan")
    assert values.projects == ("sase", "SASE Core")
    assert values.since_text == "2026-07-01"
    assert values.since == parse_time_bound("2026-07-01")
    assert values.until_text == "2026-07-18T08:30"
    assert values.until == parse_time_bound("2026-07-18T08:30")
    assert values.text == ("filter", "live preview")
    assert values.is_empty is False


def test_quoted_commas_are_values_while_unquoted_commas_are_lists() -> None:
    values = parse_plan_filter_query(
        'status:open,ready status:"waiting,review" '
        'project:sase,core project:"docs,site"'
    )

    assert values.statuses == ("open", "ready", "waiting,review")
    assert values.projects == ("sase", "core", "docs,site")


def test_parse_mixed_positive_and_negative_terms() -> None:
    values = parse_plan_filter_query(
        "kind:epic -kind:archive status:open -status:blocked,closed "
        'tier:epic -tier:tale project:sase -project:"SASE Core" '
        'filter -generated -"rollout bot" "-status:literal"'
    )

    assert values.kinds == ("epic",)
    assert values.excluded_kinds == ("archive",)
    assert values.statuses == ("open",)
    assert values.excluded_statuses == ("blocked", "closed")
    assert values.tiers == ("epic",)
    assert values.excluded_tiers == ("tale",)
    assert values.projects == ("sase",)
    assert values.excluded_projects == ("SASE Core",)
    assert values.text == ("filter", "-status:literal")
    assert values.excluded_text == ("generated", "rollout bot")


@pytest.mark.parametrize(
    ("query", "message", "token", "span"),
    (
        ("kind:", "requires a value", "kind:", (0, 5)),
        ("status:a,,b", "empty value", "status:a,,b", (0, 11)),
        ("kind:commit", "must be one of", "kind:commit", (0, 11)),
        ("since:not-a-date", "Invalid DATE", "since:not-a-date", (0, 16)),
        ("since:2026-07-18 since:7d", "only appear once", "since:7d", (17, 25)),
        ('project:"SASE Core', "Unterminated", 'project:"SASE Core', (0, 18)),
        ('""', "must not be empty", '""', (0, 2)),
        ("-", "must not be empty", "-", (0, 1)),
        ("-since:7d", "may not be negated", "-since:7d", (0, 9)),
        ("x -until:today", "may not be negated", "-until:today", (2, 14)),
    ),
)
def test_parse_errors_carry_bad_token_and_exact_span(
    query: str,
    message: str,
    token: str,
    span: tuple[int, int],
) -> None:
    with pytest.raises(PlanFilterQueryError, match=message) as exc_info:
        parse_plan_filter_query(query)

    error = exc_info.value
    assert error.token == token
    assert error.bad_token == token
    assert error.span == span
    assert (error.start, error.end) == span


def test_unknown_key_error_suggests_close_match() -> None:
    with pytest.raises(PlanFilterQueryError) as exc_info:
        parse_plan_filter_query("filter statsu:ready")

    assert exc_info.value.span == (7, 19)
    assert "did you mean 'status:'?" in str(exc_info.value)


def test_since_must_not_be_later_than_until() -> None:
    with pytest.raises(PlanFilterQueryError) as exc_info:
        parse_plan_filter_query("since:2026-07-18 until:2026-07-01")

    assert exc_info.value.token == "until:2026-07-01"
    assert exc_info.value.span == (17, 33)


def test_quoted_key_shaped_term_remains_free_text() -> None:
    assert parse_plan_filter_query('"status:not-a-filter"').text == (
        "status:not-a-filter",
    )


def test_canonical_query_has_stable_order() -> None:
    values = parse_plan_filter_query(
        'preview project:"SASE Core" until:2026-07-18 status:ready '
        'kind:phase since:7d tier:epic "filter bar"'
    )

    assert to_query_tokens(values) == (
        "kind:phase",
        "status:ready",
        "tier:epic",
        'project:"SASE Core"',
        "since:7d",
        "until:2026-07-18",
        "preview",
        '"filter bar"',
    )
    assert to_query_string(values) == " ".join(to_query_tokens(values))
    assert to_query_string(PlanFilterValues()) == ""


def test_canonical_query_serializes_exclusions_in_facet_order() -> None:
    values = parse_plan_filter_query(
        "project:sase -status:blocked kind:phase -kind:archive "
        '-project:"SASE Core" "-literal" -generated'
    )

    assert to_query_tokens(values) == (
        "kind:phase",
        "-kind:archive",
        "-status:blocked",
        "project:sase",
        '-project:"SASE Core"',
        '"-literal"',
        "-generated",
    )


_VALUE_TEXT = st.text(
    alphabet='abcXYZ 09,:\\"-@.',
    min_size=1,
    max_size=18,
)


@given(
    kinds=st.lists(
        st.sampled_from(("proposal", "epic", "phase", "archive")),
        max_size=4,
    ).map(tuple),
    statuses=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    excluded_kinds=st.lists(
        st.sampled_from(("proposal", "epic", "phase", "archive")),
        max_size=4,
    ).map(tuple),
    excluded_statuses=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    tiers=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    excluded_tiers=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    projects=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    excluded_projects=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    text_terms=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    excluded_text=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    bounds=st.sampled_from(
        (
            ("", ""),
            ("2026-07-01", ""),
            ("", "2026-07-18"),
            ("2026-07-01", "2026-07-18T08:30"),
        )
    ),
)
def test_canonical_query_round_trip_property(
    kinds: tuple[str, ...],
    statuses: tuple[str, ...],
    excluded_kinds: tuple[str, ...],
    excluded_statuses: tuple[str, ...],
    tiers: tuple[str, ...],
    excluded_tiers: tuple[str, ...],
    projects: tuple[str, ...],
    excluded_projects: tuple[str, ...],
    text_terms: tuple[str, ...],
    excluded_text: tuple[str, ...],
    bounds: tuple[str, str],
) -> None:
    since_text, until_text = bounds
    values = PlanFilterValues(
        kinds=kinds,
        excluded_kinds=excluded_kinds,
        statuses=statuses,
        excluded_statuses=excluded_statuses,
        tiers=tiers,
        excluded_tiers=excluded_tiers,
        projects=projects,
        excluded_projects=excluded_projects,
        since_text=since_text,
        until_text=until_text,
        since=parse_time_bound(since_text) if since_text else None,
        until=parse_time_bound(until_text) if until_text else None,
        text=text_terms,
        excluded_text=excluded_text,
    )

    assert parse_plan_filter_query(to_query_string(values)) == values


@pytest.mark.parametrize(
    ("text", "cursor", "expected"),
    (
        ("", 0, ("key", "")),
        ("kind:epic ", 10, ("key", "")),
        ("sta", 3, ("key", "sta")),
        ("kind:", 5, ("kind", "")),
        ("status:in_progress", 12, ("status", "in_pr")),
        ('project:"SASE Co', 16, ("project", "SASE Co")),
        ("kind:epic,ph", 12, ("kind", "ph")),
        ('status:"needs,re', 16, ("status", "needs,re")),
        ("since:7", 7, ("since", "7")),
        ("until:today", 10, ("until", "toda")),
        ("-kind:archive", 13, ("kind", "archive")),
        ("-status:bl", 10, ("status", "bl")),
        ("-since:7", 8, ("key", "since:7")),
        ('-"generated ro', 14, ("text", "generated ro")),
        ('"filter li', 10, ("text", "filter li")),
        ("unknown:value", 13, ("key", "unknown:value")),
    ),
)
def test_completion_context_classifies_cursor_prefix(
    text: str,
    cursor: int,
    expected: tuple[str, str],
) -> None:
    kind, prefix, _negated = plan_completion_context(text, cursor)
    assert (kind, prefix) == expected


def test_plan_completion_context_reports_negative_polarity() -> None:
    assert plan_completion_context("-status:bl", 10) == ("status", "bl", True)


@pytest.mark.parametrize(
    ("changes", "expected"),
    (
        ({}, True),
        ({"kind": "archive"}, False),
        ({"status_labels": frozenset(("closed",))}, False),
        ({"tier_labels": frozenset(("plan",))}, False),
        ({"project_labels": frozenset(("other",))}, False),
        ({"timestamp": 99}, False),
        ({"timestamp": 301}, False),
        ({"timestamp": None}, False),
        ({"haystack": ("plans filter bar",)}, False),
        ({"haystack": ("search index", "plans filter bar")}, True),
    ),
)
def test_plan_matcher_ors_within_keys_and_ands_across_keys_and_text(
    changes: dict[str, object],
    expected: bool,
) -> None:
    matcher = compile_plan_matcher(
        PlanFilterValues(
            kinds=("EPIC", "phase"),
            statuses=("blocked", "READY"),
            tiers=("EPIC", "tale"),
            projects=("SASE", "sase-core"),
            since=100,
            until=300,
            text=("FILTER", "index"),
        )
    )

    assert matcher(_record(**changes)) is expected


def test_plan_matcher_negative_facets_and_text_veto_multi_label_records() -> None:
    base = _record()
    assert (
        compile_plan_matcher(
            PlanFilterValues(statuses=("open",), excluded_statuses=("ready",))
        )(base)
        is False
    )
    assert (
        compile_plan_matcher(
            PlanFilterValues(tiers=("epic",), excluded_tiers=("plan",))
        )(base)
        is True
    )
    assert (
        compile_plan_matcher(
            PlanFilterValues(projects=("SASE",), excluded_projects=("other",))
        )(base)
        is True
    )
    assert (
        compile_plan_matcher(
            PlanFilterValues(kinds=("epic",), excluded_kinds=("EPIC",))
        )(base)
        is False
    )
    assert (
        compile_plan_matcher(
            PlanFilterValues(text=("filter",), excluded_text=("INDEX",))
        )(base)
        is False
    )


def test_timestamp_bounds_include_endpoints_and_ignore_missing_without_bounds() -> None:
    assert compile_plan_matcher(PlanFilterValues(since=200))(_record(timestamp=200))
    assert compile_plan_matcher(PlanFilterValues(until=200))(_record(timestamp=200))
    assert compile_plan_matcher(PlanFilterValues())(_record(timestamp=None))


def test_build_index_covers_every_row_with_stable_option_ids() -> None:
    snapshot = _snapshot()
    index = build_plan_filter_index(snapshot)

    assert index.source_key == snapshot.source_key
    assert len(index) == 5
    assert tuple(record.kind for record in index) == (
        "proposal",
        "epic",
        "phase",
        "epic",
        "archive",
    )
    assert set(index.by_option_id) == {
        "proposal:sase:proposal-1",
        "epic:sase:sase-6t",
        "phase:sase:sase-6t.1",
        "epic:sase:sase-7x",
        "archive:sase:/plans/202607/archive.md",
    }


def test_build_index_prefolds_search_fields_and_project_aliases() -> None:
    index = build_plan_filter_index(_snapshot())

    proposal = index.by_option_id["proposal:sase:proposal-1"]
    assert proposal.status_labels == frozenset(("proposed",))
    assert proposal.tier_labels == frozenset(("epic",))
    assert proposal.project_labels == frozenset(
        ("sase", "structured agentic software engineering")
    )
    assert "make plan filtering instant" in proposal.haystack
    assert compile_plan_matcher(
        PlanFilterValues(projects=("Structured Agentic Software Engineering",))
    )(proposal)


def test_build_index_uses_the_same_derived_state_priority_as_rows() -> None:
    index = build_plan_filter_index(_snapshot())

    ready = index.by_option_id["epic:sase:sase-6t"]
    blocked = index.by_option_id["phase:sase:sase-6t.1"]
    launched = index.by_option_id["epic:sase:sase-7x"]
    assert ready.status_labels == frozenset(("in_progress", "ready"))
    assert "launched" not in ready.status_labels
    assert blocked.status_labels == frozenset(("open", "blocked"))
    assert launched.status_labels == frozenset(("open", "launched"))
    assert launched.tier_labels == frozenset(("plan",))


def test_build_index_normalizes_timestamps_and_excludes_invalid_values() -> None:
    index = build_plan_filter_index(_snapshot())

    proposal = index.by_option_id["proposal:sase:proposal-1"]
    phase = index.by_option_id["phase:sase:sase-6t.1"]
    assert proposal.timestamp == int(
        datetime.fromisoformat("2026-07-01T12:00:00+00:00").timestamp()
    )
    assert phase.timestamp is None
    assert compile_plan_matcher(PlanFilterValues(since=0))(phase) is False


def test_archive_index_includes_status_tier_and_full_body() -> None:
    archive = build_plan_filter_index(_snapshot()).by_option_id[
        "archive:sase:/plans/202607/archive.md"
    ]

    assert archive.status_labels == frozenset(("done", "approved"))
    assert archive.tier_labels == frozenset(("tale", "epic"))
    assert "# rollout\n\nthe filter bar is live." in archive.haystack
    assert compile_plan_matcher(
        PlanFilterValues(
            kinds=("archive",),
            statuses=("APPROVED",),
            tiers=("TALE",),
            text=("filter bar",),
        )
    )(archive)


def test_single_project_option_ids_match_the_existing_row_contract() -> None:
    snapshot = replace(_snapshot(), project="sase")
    index = build_plan_filter_index(snapshot)

    assert "epic:sase-6t" in index.by_option_id
    assert "epic:sase:sase-6t" not in index.by_option_id
