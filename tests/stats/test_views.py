from dataclasses import FrozenInstanceError
from zoneinfo import ZoneInfo

import pytest

from sase.stats.views import build_statistics_views
from tests.stats._views_payloads import activity_payload, run_payload


def test_builds_all_presentation_views_from_binding_payloads() -> None:
    views = build_statistics_views(
        run_payload(),
        activity_payload(),
        previous_run_payload={"totals": {"runs": 4}},
        timezone=ZoneInfo("UTC"),
    )

    assert views.empty is False
    assert views.overview.agents_run == 6
    assert views.overview.runs_delta == 2
    assert views.overview.runs_delta_ratio == 0.5
    assert views.overview.success_rate == 0.6
    assert views.overview.epic_plans == 2
    assert views.overview.question_sessions == 2
    assert views.overview.top_providers[0].label == "codex"
    assert views.overview.top_providers[0].count == 5
    assert views.overview.top_projects[0].project_key == "sase"
    assert views.overview.top_projects[0].project_label == "sase"
    assert views.overview.top_projects[0].success_rate == 0.75
    assert views.overview.buckets[1].label == "Thu 01:00"
    assert views.runs.outcomes[0].share == 0.6
    assert views.runs.commit_distribution[-1].label == "3+"
    assert views.projects.project_count == 2
    assert views.projects.patch_count == 3
    assert views.projects.unattributed_runs == 1
    assert views.projects.truncated_patch_rows == 1
    assert views.projects.malformed_spec_files_skipped == 2
    assert views.projects.projects[0].patches[0].patch_key == "stats-view"
    assert views.projects.projects[0].patches[0].patch_label == "stats-view"
    assert views.projects.projects[1].patches[0].status == "unknown"
    assert views.projects.patches[0].has_pr is True
    assert views.providers.rows[0].share == pytest.approx(4 / 6)
    assert views.providers.rows[-1].mean_runtime_seconds is None
    assert views.runtime.rows[0].share == pytest.approx(2 / 3)
    assert views.runtime.in_progress == 1
    assert views.activity.skills[0].distinct_agents == 3
    assert views.activity.workspaces[0].workspace_num == 17
    assert views.plans_questions.mean_phases_per_epic == 3.0
    assert views.plans_questions.plans_proposed == 3
    assert views.plans_questions.plans_approved == 2
    assert views.plans_questions.plans_rejected == 1
    assert views.plans_questions.plans_feedback == 0
    assert views.plans_questions.plans_pending == 0
    assert views.plans_questions.question_sessions == 2
    assert views.plans_questions.asking_agents == 2
    assert views.plans_questions.coverage_start_ts == 1_000.0
    assert views.plans_questions.questions_per_session[-1].label == "2"


def test_models_are_frozen() -> None:
    views = build_statistics_views(run_payload(), activity_payload())

    with pytest.raises(FrozenInstanceError):
        views.overview.agents_run = 99  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        views.xprompts.available = True  # type: ignore[misc]


def test_plans_questions_ignore_inaccurate_index_derived_totals() -> None:
    payload = run_payload()
    payload["plans"] = {
        "proposed": 1,
        "approved": 1,
        "rejected": 0,
        "pending": 0,
    }
    payload["questions"] = {"sessions": 1, "asking_agents": 1}

    view = build_statistics_views(payload, activity_payload()).plans_questions

    assert (
        view.plans_proposed,
        view.plans_approved,
        view.plans_rejected,
        view.plans_feedback,
        view.plans_pending,
    ) == (3, 2, 1, 0, 0)
    assert (view.question_sessions, view.asking_agents) == (2, 2)
    assert [(row.label, row.count) for row in view.plan_tiers] == [
        ("epic", 2),
        ("tale", 1),
    ]
    assert view.mean_phases_per_epic == 3.0
    assert view.questions == 3
    assert view.mean_questions_per_session == 1.5


def test_overview_buckets_trim_leading_and_trailing_zero_runs() -> None:
    payload = run_payload()
    payload["bucket_seconds"] = 86_400
    payload["buckets"] = [
        {"start_ts": 0, "runs": 0},
        {"start_ts": 86_400, "runs": 0},
        {"start_ts": 172_800, "runs": 3},
        {"start_ts": 259_200, "runs": 0},
        {"start_ts": 345_600, "runs": 5},
        {"start_ts": 432_000, "runs": 0},
        {"start_ts": 518_400, "runs": 0},
    ]

    overview = build_statistics_views(payload, activity_payload()).overview

    assert [(bucket.start_ts, bucket.runs) for bucket in overview.buckets] == [
        (172_800, 3),
        (259_200, 0),
        (345_600, 5),
    ]
    assert overview.bucket_group_seconds is None


def test_overview_buckets_group_when_the_trimmed_span_exceeds_the_cap() -> None:
    payload = run_payload()
    payload["bucket_seconds"] = 86_400
    payload["buckets"] = [
        {"start_ts": index * 86_400, "runs": 1 if index % 10 == 0 else 0}
        for index in range(200)
    ]

    overview = build_statistics_views(payload, activity_payload()).overview

    assert len(overview.buckets) <= 96
    assert overview.bucket_group_seconds == 172_800
    assert sum(bucket.runs for bucket in overview.buckets) == 20


def test_empty_and_partial_payloads_are_safe() -> None:
    views = build_statistics_views({}, {})

    assert views.empty is True
    assert views.overview.success_rate == 0.0
    assert views.overview.runs_delta is None
    assert views.runs.outcomes == ()
    assert views.projects.projects == ()
    assert views.projects.patches == ()
    assert views.projects.project_count == 0
    assert views.projects.patch_count == 0
    assert views.overview.top_projects == ()
    assert views.providers.rows == ()
    assert views.runtime.group_by == "agent"
    assert views.activity.skills == ()
    assert views.xprompts.available is False
    assert views.plans_questions.questions == 0
    assert views.runners.available is False
    assert views.runners.current_limit is None
