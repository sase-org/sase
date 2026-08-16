"""Shared fixtures and helpers for the plans filter query tests.

Hosts the synthetic :class:`_PlanFilterRecord` factory, the plans snapshot used to
exercise :func:`build_plan_filter_index`, and the thin wrappers that compile a query
index and evaluate a query string against it.
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.query_profile import (
    CompiledQueryProfile,
    compiled_profile_for_builtin_pane,
)
from sase.ace.tui.widgets.artifacts.bead_plan_links import BeadPlanLink
from sase.ace.tui.widgets.artifacts.plans_data import (
    ActivePlanDocument,
    LinkedPlanDocument,
    PlanProposal,
    PlansSnapshot,
    ProjectArchive,
)
from sase.ace.tui.widgets.artifacts.plans_filtering import _PlanFilterRecord
from sase.ace.tui.widgets.artifacts.query_rows import build_plans_query_index
from sase.bead.model import BeadTier, IssueType, Status
from sase.core.query_profile_corpus_facade import (
    compile_artifact_query_index,
    evaluate_artifact_query_many,
)
from sase.core.time import get_timezone
from sase.notifications.models import Notification
from sase.plan_search.model import Plan, PlanSearchMatch


def plan_record(**changes: object) -> _PlanFilterRecord:
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


def plan_profile() -> CompiledQueryProfile:
    profile = compiled_profile_for_builtin_pane("ref:plan")
    assert profile is not None
    return profile


def query_matches_record(query: str, record: _PlanFilterRecord) -> bool:
    fields: dict[str, object] = {
        "kind": tuple(record.kind_labels or frozenset((record.kind,))),
        "status": tuple(record.status_labels),
        "tier": tuple(record.tier_labels),
        "project": tuple(
            value for value in (record.project, record.project_display_name) if value
        ),
        "title": tuple(record.haystack),
        "body": tuple(record.haystack),
        "path": record.identity,
    }
    if record.timestamp is not None:
        fields["since"] = (record.timestamp,)
        fields["until"] = (record.timestamp,)
    index = compile_artifact_query_index(
        pane_id="ref:plan",
        generation=1,
        profile=plan_profile(),
        entries=(
            {
                "stable_id": record.option_id,
                "fields": fields,
                "searchable_text": "\n".join(record.haystack),
                "predicates": (),
            },
        ),
    )
    return evaluate_artifact_query_many(query, index).matched_row_ids == (
        record.option_id,
    )


def matched_plan_option_ids(snapshot: PlansSnapshot, query: str) -> frozenset[str]:
    _filter_index, query_index = build_plans_query_index(
        snapshot,
        pane_id="ref:plan",
        generation=1,
        profile=plan_profile(),
    )
    return frozenset(evaluate_artifact_query_many(query, query_index).matched_row_ids)


def epoch(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> int:
    return int(
        datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            tzinfo=get_timezone(),
        ).timestamp()
    )


def plans_snapshot() -> PlansSnapshot:
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
    link = BeadPlanLink(
        project="sase",
        bead_id="sase-6t",
        bead_type=IssueType.PLAN,
        bead_status=Status.IN_PROGRESS,
        bead_tier=BeadTier.EPIC,
        bead_title="Plans filter bar",
        bead_created_at="2026-07-02T09:00:00Z",
        reference="plan:202607/active.md",
        path="/plans/202607/active.md",
    )
    document = LinkedPlanDocument(
        reference=link.reference,
        path=link.path,
        content="# Plans filter bar\n\nSearch index.",
        frontmatter={
            "title": "Plans filter bar",
            "tier": "epic",
            "status": "wip",
            "create_time": "2026-07-02T09:00:00Z",
            "goal": "Make plan filtering instant",
        },
        body="# Plans filter bar\n\nSearch index.",
        error=None,
        signature=(1, 2, 3, 4),
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
        plans_roots={"sase": {"plans": "/plans"}},
        workspace_dirs={"sase": "/workspace"},
        proposals=(proposal,),
        active=(ActivePlanDocument("sase", document, link),),
        archive=(ProjectArchive("sase", archive_match),),
        bead_plan_links={("sase", link.bead_id): link},
        linked_plan_documents={("sase", link.bead_id): document},
        source_key=("snapshot", 1),
        errors={},
        archive_truncated=True,
    )
