from dataclasses import FrozenInstanceError
from zoneinfo import ZoneInfo

import pytest

from sase.stats.views import build_statistics_views


def _run_payload() -> dict[str, object]:
    return {
        "start_ts": 0,
        "end_ts": 7_200,
        "runtime_group_by": "agent",
        "bucket_seconds": 3_600,
        "totals": {
            "runs": 6,
            "completed": 3,
            "failed": 1,
            "other_terminal": 1,
            "in_progress": 1,
            "waiting": 0,
        },
        "outcomes": [
            {"name": "completed", "count": 3},
            {"name": "failed", "count": 1},
            {"name": "stopped", "count": 1},
        ],
        "retries": {"chains": 2, "attempts": 3, "kills": 1},
        "providers": [
            {
                "provider": "codex",
                "model": "gpt-5",
                "effort": "high",
                "runs": 4,
                "success_rate": 0.75,
                "mean_runtime_seconds": 200.0,
            },
            {
                "provider": "codex",
                "model": "gpt-5",
                "effort": "default",
                "runs": 1,
                "success_rate": 1.0,
                "mean_runtime_seconds": 50.0,
            },
            {
                "provider": "claude",
                "model": "opus",
                "effort": "xhigh",
                "runs": 1,
                "success_rate": 0.0,
                "mean_runtime_seconds": None,
            },
        ],
        "commits": {
            "total_commits": 7,
            "committing_agents": 3,
            "average_per_committing_agent": 7 / 3,
            "distribution": {"zero": 3, "one": 1, "two": 1, "three_plus": 1},
            "top_repos": [
                {"name": "sase", "count": 5},
                {"name": "core", "count": 2},
            ],
        },
        "questions": {"sessions": 2, "asking_agents": 1},
        "workspaces": [
            {"project": "sase", "workspace_num": 17, "runs": 4},
            {"project": "core", "workspace_num": 2, "runs": 2},
        ],
        "buckets": [
            {"start_ts": 0, "runs": 2},
            {"start_ts": 3_600, "runs": 4},
        ],
        "runtime_groups": [
            {
                "group": "alpha",
                "runs": 2,
                "total_seconds": 1_000.0,
                "mean_seconds": 500.0,
                "p50_seconds": 450.0,
                "p95_seconds": 700.0,
                "max_seconds": 750.0,
            },
            {
                "group": "beta",
                "runs": 1,
                "total_seconds": 500.0,
                "mean_seconds": 500.0,
                "p50_seconds": 500.0,
                "p95_seconds": 500.0,
                "max_seconds": 500.0,
            },
        ],
    }


def _activity_payload() -> dict[str, object]:
    return {
        "skills": [
            {"name": "review", "count": 8, "distinct_agents": 3},
            {"name": "plan", "count": 4, "distinct_agents": 2},
        ],
        "memories": [
            {"name": "sase.md", "count": 5, "distinct_agents": 2},
        ],
        "plans": {
            "proposed": 3,
            "tiers": [
                {"name": "epic", "count": 2},
                {"name": "tale", "count": 1},
            ],
            "approved": 2,
            "rejected": 1,
            "pending": 0,
            "phases_per_epic": [
                {"value": 2, "count": 1},
                {"value": 4, "count": 1},
            ],
            "mean_phases_per_epic": 3.0,
        },
        "questions": {
            "sessions": 2,
            "questions": 3,
            "questions_per_session": [
                {"value": 1, "count": 1},
                {"value": 2, "count": 1},
            ],
            "mean_questions_per_session": 1.5,
        },
    }


def test_builds_all_presentation_views_from_binding_payloads() -> None:
    views = build_statistics_views(
        _run_payload(),
        _activity_payload(),
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
    assert views.overview.buckets[1].label == "Thu 01:00"
    assert views.runs.outcomes[0].share == 0.6
    assert views.runs.commit_distribution[-1].label == "3+"
    assert views.providers.rows[0].share == pytest.approx(4 / 6)
    assert views.providers.rows[-1].mean_runtime_seconds is None
    assert views.runtime.rows[0].share == pytest.approx(2 / 3)
    assert views.runtime.in_progress == 1
    assert views.activity.skills[0].distinct_agents == 3
    assert views.activity.workspaces[0].workspace_num == 17
    assert views.plans_questions.mean_phases_per_epic == 3.0
    assert views.plans_questions.asking_agents == 1
    assert views.plans_questions.questions_per_session[-1].label == "2"


def test_models_are_frozen() -> None:
    views = build_statistics_views(_run_payload(), _activity_payload())

    with pytest.raises(FrozenInstanceError):
        views.overview.agents_run = 99  # type: ignore[misc]


def test_empty_and_partial_payloads_are_safe() -> None:
    views = build_statistics_views({}, {})

    assert views.empty is True
    assert views.overview.success_rate == 0.0
    assert views.overview.runs_delta is None
    assert views.runs.outcomes == ()
    assert views.providers.rows == ()
    assert views.runtime.group_by == "agent"
    assert views.activity.skills == ()
    assert views.plans_questions.questions == 0
