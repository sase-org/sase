from dataclasses import FrozenInstanceError
from zoneinfo import ZoneInfo

import pytest

from sase.project_display_names import ProjectDisplaySnapshot
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
        "plans": {
            "proposed": 4,
            "approved": 1,
            "rejected": 2,
            "pending": 1,
        },
        "questions": {"sessions": 1, "asking_agents": 1},
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
        "work": {
            "projects": [
                {
                    "project": "sase",
                    "runs": 4,
                    "completed": 3,
                    "failed": 1,
                    "other_terminal": 0,
                    "in_progress": 0,
                    "waiting": 0,
                    "success_rate": 0.75,
                    "commits": 5,
                    "distinct_changespecs": 2,
                    "unattributed_runs": 1,
                    "total_runtime_seconds": 1_200.0,
                    "last_run_ts": 7_000.0,
                },
                {
                    "project": "core",
                    "runs": 2,
                    "completed": 0,
                    "failed": 0,
                    "other_terminal": 1,
                    "in_progress": 1,
                    "waiting": 0,
                    "success_rate": 0.0,
                    "commits": 2,
                    "distinct_changespecs": 1,
                    "unattributed_runs": 0,
                    "total_runtime_seconds": 300.0,
                    "last_run_ts": 6_000.0,
                },
            ],
            "changespecs": [
                {
                    "project": "sase",
                    "name": "stats-view",
                    "status": "Ready",
                    "has_pr": True,
                    "runs": 2,
                    "distinct_agents": 2,
                    "commits": 3,
                    "total_runtime_seconds": 700.0,
                    "first_run_ts": 1_000.0,
                    "last_run_ts": 7_000.0,
                },
                {
                    "project": "core",
                    "name": "wire-work",
                    "status": "unknown",
                    "has_pr": False,
                    "runs": 2,
                    "distinct_agents": 1,
                    "commits": 2,
                    "total_runtime_seconds": 300.0,
                    "first_run_ts": 2_000.0,
                    "last_run_ts": 6_000.0,
                },
            ],
            "unattributed_runs": 1,
            "truncated_changespec_rows": 1,
            "malformed_spec_files_skipped": 2,
        },
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
    assert views.overview.top_projects[0].project_key == "sase"
    assert views.overview.top_projects[0].project_label == "sase"
    assert views.overview.top_projects[0].success_rate == 0.75
    assert views.overview.buckets[1].label == "Thu 01:00"
    assert views.runs.outcomes[0].share == 0.6
    assert views.runs.commit_distribution[-1].label == "3+"
    assert views.projects.project_count == 2
    assert views.projects.changespec_count == 3
    assert views.projects.unattributed_runs == 1
    assert views.projects.truncated_changespec_rows == 1
    assert views.projects.malformed_spec_files_skipped == 2
    assert views.projects.projects[0].changespecs[0].changespec_key == "stats-view"
    assert views.projects.projects[0].changespecs[0].changespec_label == "stats-view"
    assert views.projects.projects[1].changespecs[0].status == "unknown"
    assert views.projects.changespecs[0].has_pr is True
    assert views.providers.rows[0].share == pytest.approx(4 / 6)
    assert views.providers.rows[-1].mean_runtime_seconds is None
    assert views.runtime.rows[0].share == pytest.approx(2 / 3)
    assert views.runtime.in_progress == 1
    assert views.activity.skills[0].distinct_agents == 3
    assert views.activity.workspaces[0].workspace_num == 17
    assert views.plans_questions.mean_phases_per_epic == 3.0
    assert views.plans_questions.plans_proposed == 4
    assert views.plans_questions.plans_approved == 1
    assert views.plans_questions.plans_rejected == 2
    assert views.plans_questions.plans_pending == 1
    assert views.plans_questions.question_sessions == 1
    assert views.plans_questions.asking_agents == 1
    assert views.plans_questions.questions_per_session[-1].label == "2"


def test_models_are_frozen() -> None:
    views = build_statistics_views(_run_payload(), _activity_payload())

    with pytest.raises(FrozenInstanceError):
        views.overview.agents_run = 99  # type: ignore[misc]


def test_filtered_plans_questions_keep_global_document_aggregates() -> None:
    run_payload = _run_payload()
    run_payload["plans"] = {
        "proposed": 1,
        "approved": 1,
        "rejected": 0,
        "pending": 0,
    }
    run_payload["questions"] = {"sessions": 1, "asking_agents": 1}

    view = build_statistics_views(run_payload, _activity_payload()).plans_questions

    assert (
        view.plans_proposed,
        view.plans_approved,
        view.plans_rejected,
        view.plans_pending,
    ) == (1, 1, 0, 0)
    assert (view.question_sessions, view.asking_agents) == (1, 1)
    assert [(row.label, row.count) for row in view.plan_tiers] == [
        ("epic", 2),
        ("tale", 1),
    ]
    assert view.mean_phases_per_epic == 3.0
    assert view.questions == 3
    assert view.mean_questions_per_session == 1.5


def test_empty_and_partial_payloads_are_safe() -> None:
    views = build_statistics_views({}, {})

    assert views.empty is True
    assert views.overview.success_rate == 0.0
    assert views.overview.runs_delta is None
    assert views.runs.outcomes == ()
    assert views.projects.projects == ()
    assert views.projects.changespecs == ()
    assert views.projects.project_count == 0
    assert views.projects.changespec_count == 0
    assert views.overview.top_projects == ()
    assert views.providers.rows == ()
    assert views.runtime.group_by == "agent"
    assert views.activity.skills == ()
    assert views.plans_questions.questions == 0


@pytest.mark.parametrize("group_by", ["project", "changespec"])
def test_runtime_work_group_literals_round_trip(group_by: str) -> None:
    payload = _run_payload()
    payload["runtime_group_by"] = group_by

    views = build_statistics_views(payload, _activity_payload())

    assert views.runtime.group_by == group_by


def test_work_rows_tolerate_partial_and_invalid_values() -> None:
    views = build_statistics_views(
        {
            "work": {
                "projects": [{"project": "sase", "runs": True}],
                "changespecs": [
                    {
                        "project": "sase",
                        "name": "orphan",
                        "status": "",
                        "has_pr": "yes",
                    }
                ],
                "truncated_changespec_rows": 2,
            }
        },
        {},
    )

    assert views.projects.project_count == 1
    assert views.projects.changespec_count == 3
    assert views.projects.projects[0].runs == 0
    assert views.projects.projects[0].changespecs[0].status == "unknown"
    assert views.projects.projects[0].changespecs[0].has_pr is False


def test_project_display_snapshot_projects_every_project_bearing_row() -> None:
    payload = _run_payload()
    widgets_key = "gh_acme__widgets"
    payload["workspaces"][0]["project"] = widgets_key  # type: ignore[index]
    payload["work"]["projects"][0]["project"] = widgets_key  # type: ignore[index]
    payload["work"]["changespecs"][0].update(  # type: ignore[index,union-attr]
        {
            "project": widgets_key,
            "name": f"{widgets_key}_stats-view",
        }
    )
    payload["runtime_group_by"] = "project"
    payload["runtime_groups"][0]["group"] = widgets_key  # type: ignore[index]
    snapshot = ProjectDisplaySnapshot({widgets_key: "widgets"})

    views = build_statistics_views(
        payload,
        _activity_payload(),
        project_display_snapshot=snapshot,
    )

    project = views.projects.projects[0]
    assert (project.project_key, project.project_label) == (widgets_key, "widgets")
    assert [row.changespec_key for row in project.changespecs] == [
        f"{widgets_key}_stats-view"
    ]
    assert project.changespecs[0].changespec_label == "widgets_stats-view"
    assert (
        project.changespecs[0].project_key,
        project.changespecs[0].project_label,
    ) == (widgets_key, "widgets")
    assert (
        views.activity.workspaces[0].project_key,
        views.activity.workspaces[0].project_label,
    ) == (widgets_key, "widgets")
    assert (
        views.runtime.rows[0].group_key,
        views.runtime.rows[0].group_label,
    ) == (widgets_key, "widgets")
    assert views.projects.projects[1].project_label == "core"


def test_changespec_runtime_groups_are_humanized_without_losing_identity() -> None:
    payload = _run_payload()
    widgets_key = "gh_acme__widgets"
    changespec_key = f"{widgets_key}_repair_labels"
    payload["runtime_group_by"] = "changespec"
    payload["runtime_groups"][0]["group"] = changespec_key  # type: ignore[index]

    runtime = build_statistics_views(
        payload,
        _activity_payload(),
        project_display_snapshot=ProjectDisplaySnapshot({widgets_key: "widgets"}),
    ).runtime

    assert (runtime.rows[0].group_key, runtime.rows[0].group_label) == (
        changespec_key,
        "widgets_repair_labels",
    )


def test_ranked_project_ties_sort_by_visible_label_then_canonical_key() -> None:
    payload = _run_payload()
    projects = payload["work"]["projects"]  # type: ignore[index]
    for row, project_key in zip(  # type: ignore[assignment]
        projects,
        ("gh_zed__widgets", "gh_acme__widgets"),
        strict=True,
    ):
        row["project"] = project_key
        row["runs"] = 4
    payload["work"]["changespecs"] = []  # type: ignore[index]
    snapshot = ProjectDisplaySnapshot(
        {
            "gh_zed__widgets": "widgets",
            "gh_acme__widgets": "widgets",
        }
    )

    rows = build_statistics_views(
        payload,
        _activity_payload(),
        project_display_snapshot=snapshot,
    ).projects.projects

    assert [(row.project_label, row.project_key) for row in rows] == [
        ("widgets", "gh_acme__widgets"),
        ("widgets", "gh_zed__widgets"),
    ]
