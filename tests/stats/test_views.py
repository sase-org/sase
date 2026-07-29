from dataclasses import FrozenInstanceError
from zoneinfo import ZoneInfo

import pytest

from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.views import build_statistics_views
from tests._project_display_case import ProjectDisplayCase


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
        "runners": {
            "start_ts": 0.0,
            "end_ts": 7_200.0,
            "peak_runners": 3,
            "peak_seconds": 600.0,
            "average_runners": 1.25,
            "busy_seconds": 6_000.0,
            "busy_share": 6_000 / 7_200,
            "runner_seconds": 9_000.0,
            "distribution": [
                {"runners": 0, "seconds": 1_200.0, "share": 1_200 / 7_200},
                {"runners": 1, "seconds": 3_600.0, "share": 3_600 / 7_200},
                {"runners": 2, "seconds": 1_800.0, "share": 1_800 / 7_200},
                {"runners": 3, "seconds": 600.0, "share": 600 / 7_200},
            ],
            "trend": [
                {
                    "start_ts": 0.0,
                    "end_ts": 3_600.0,
                    "average_runners": 1.0,
                    "peak_runners": 2,
                    "busy_seconds": 3_000.0,
                    "runner_seconds": 3_600.0,
                },
                {
                    "start_ts": 3_600.0,
                    "end_ts": 7_200.0,
                    "average_runners": 1.5,
                    "peak_runners": 3,
                    "busy_seconds": 3_000.0,
                    "runner_seconds": 5_400.0,
                },
            ],
            "malformed_rows_skipped": 1,
            "invalid_intervals_skipped": 2,
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


def test_xprompts_absent_section_is_explicitly_unavailable() -> None:
    views = build_statistics_views(
        _run_payload(),
        _activity_payload(),
        timezone=ZoneInfo("UTC"),
    )

    assert views.xprompts.available is False
    assert views.xprompts.rows == ()
    assert views.xprompts.focus is None


def test_xprompts_present_empty_section_is_available() -> None:
    run_payload = _run_payload()
    run_payload["xprompts"] = {
        "runs_with_xprompts": 0,
        "runs_without_xprompts": 6,
        "distinct_xprompts": 0,
        "total_references": 0,
        "rows": [],
        "truncated_rows": 0,
        "focus": None,
    }

    xprompts = build_statistics_views(
        run_payload,
        _activity_payload(),
        timezone=ZoneInfo("UTC"),
    ).xprompts

    assert xprompts.available is True
    assert xprompts.runs_with_xprompts == 0
    assert xprompts.runs_without_xprompts == 6
    assert xprompts.rows == ()
    assert xprompts.focus is None


def test_xprompts_populated_rows_build_shares_tags_and_project_labels() -> None:
    run_payload = _run_payload()
    run_payload["xprompts"] = {
        "runs_with_xprompts": 4,
        "runs_without_xprompts": 2,
        "distinct_xprompts": 2,
        "total_references": 7,
        "truncated_rows": 0,
        "rows": [
            {
                "name": "split_file",
                "kind": "part",
                "tags": ["files", "vcs"],
                "runs": 3,
                "references": 5,
                "distinct_agents": 2,
                "completed": 2,
                "failed": 1,
                "success_rate": 2 / 3,
                "total_runtime_seconds": 900.0,
                "mean_runtime_seconds": None,
                "first_run_ts": 1_000.0,
                "last_run_ts": 7_000.0,
                "models": [
                    {"name": "gpt-5", "count": 2},
                    {"name": "opus", "count": 1},
                ],
                "projects": [
                    {"name": "gh_acme__widgets", "count": 2},
                    {"name": "core", "count": 1},
                ],
                "partners": [{"name": "gh", "count": 2}],
            },
            {
                "name": "gh",
                "kind": "workflow",
                "tags": [],
                "runs": 1,
                "references": 2,
                "distinct_agents": 1,
                "completed": 1,
                "failed": 0,
                "success_rate": 1.0,
                "total_runtime_seconds": 100.0,
                "mean_runtime_seconds": 100.0,
                "first_run_ts": 2_000.0,
                "last_run_ts": 2_000.0,
                "models": [],
                "projects": [],
                "partners": [],
            },
        ],
        "focus": None,
    }
    snapshot = ProjectDisplaySnapshot({"gh_acme__widgets": "widgets"})

    xprompts = build_statistics_views(
        run_payload,
        _activity_payload(),
        timezone=ZoneInfo("UTC"),
        project_display_snapshot=snapshot,
    ).xprompts

    assert xprompts.available is True
    assert xprompts.distinct_xprompts == 2
    assert xprompts.total_references == 7
    assert [row.name for row in xprompts.rows] == ["split_file", "gh"]
    row = xprompts.rows[0]
    assert row.tags == ("files", "vcs")
    assert row.share == pytest.approx(3 / 4)
    assert row.mean_runtime_seconds is None
    assert row.models[0].share == pytest.approx(2 / 3)
    assert (row.projects[0].key, row.projects[0].label) == (
        "gh_acme__widgets",
        "widgets",
    )
    assert row.projects[0].share == pytest.approx(2 / 3)
    assert row.partners[0].share == pytest.approx(2 / 3)


def test_xprompt_focus_builds_full_breakdowns_and_bucket_labels() -> None:
    run_payload = _run_payload()
    run_payload["xprompts"] = {
        "runs_with_xprompts": 2,
        "runs_without_xprompts": 4,
        "distinct_xprompts": 1,
        "total_references": 3,
        "rows": [],
        "truncated_rows": 0,
        "focus": {
            "name": "gh",
            "found": True,
            "kind": "workflow",
            "tags": ["rollover", "vcs"],
            "runs": 2,
            "references": 3,
            "distinct_agents": 2,
            "completed": 1,
            "failed": 1,
            "success_rate": 0.5,
            "total_runtime_seconds": 300.0,
            "mean_runtime_seconds": 150.0,
            "first_run_ts": 0.0,
            "last_run_ts": 3_600.0,
            "models": [{"name": "gpt-5", "count": 2}],
            "providers": [{"name": "codex", "count": 2}],
            "projects": [{"name": "gh_acme__widgets", "count": 1}],
            "partners": [{"name": "split_file", "count": 1}],
            "tribes": [{"name": "tools", "count": 1}],
            "buckets": [
                {"start_ts": 0, "runs": 1},
                {"start_ts": 3_600, "runs": 1},
            ],
        },
    }

    focus = build_statistics_views(
        run_payload,
        _activity_payload(),
        timezone=ZoneInfo("UTC"),
        project_display_snapshot=ProjectDisplaySnapshot(
            {"gh_acme__widgets": "widgets"}
        ),
    ).xprompts.focus

    assert focus is not None
    assert focus.found is True
    assert focus.tags == ("rollover", "vcs")
    assert focus.mean_runtime_seconds == 150.0
    assert focus.models[0].share == 1.0
    assert focus.providers[0].label == "codex"
    assert focus.projects[0].label == "widgets"
    assert focus.partners[0].share == 0.5
    assert focus.tribes[0].label == "tools"
    assert [bucket.label for bucket in focus.buckets] == [
        "Thu 00:00",
        "Thu 01:00",
    ]


def test_xprompt_focus_preserves_not_found_state() -> None:
    run_payload = _run_payload()
    run_payload["xprompts"] = {
        "runs_with_xprompts": 0,
        "runs_without_xprompts": 6,
        "distinct_xprompts": 0,
        "total_references": 0,
        "rows": [],
        "truncated_rows": 0,
        "focus": {"name": "missing", "found": False},
    }

    focus = build_statistics_views(
        run_payload,
        _activity_payload(),
        timezone=ZoneInfo("UTC"),
    ).xprompts.focus

    assert focus is not None
    assert focus.name == "missing"
    assert focus.found is False
    assert focus.runs == 0
    assert focus.buckets == ()


def test_runner_view_maps_summary_distribution_and_timezone_slices() -> None:
    views = build_statistics_views(
        _run_payload(),
        _activity_payload(),
        timezone=ZoneInfo("UTC"),
        current_runner_limit=4,
    )

    runners = views.runners
    assert runners.available is True
    assert (runners.start_ts, runners.end_ts) == (0.0, 7_200.0)
    assert runners.peak_runners == 3
    assert runners.peak_seconds == 600.0
    assert runners.average_runners == 1.25
    assert runners.busy_seconds == 6_000.0
    assert runners.busy_share == pytest.approx(6_000 / 7_200)
    assert runners.runner_seconds == 9_000.0
    assert runners.current_limit == 4
    assert runners.malformed_rows_skipped == 1
    assert runners.invalid_intervals_skipped == 2

    # Distribution covers every observed count from zero through the peak, and
    # the conservation identities from the backend contract still hold.
    assert [row.runners for row in runners.distribution] == [0, 1, 2, 3]
    assert sum(row.seconds for row in runners.distribution) == pytest.approx(
        runners.end_ts - runners.start_ts
    )
    assert sum(
        row.runners * row.seconds for row in runners.distribution
    ) == pytest.approx(runners.runner_seconds)
    assert runners.distribution[1].share == pytest.approx(0.5)

    # Trend slices carry exact bounds, time-weighted average, and a label
    # formatted in the configured SASE timezone.
    assert [slice_.label for slice_ in runners.trend] == ["Thu 00:00", "Thu 01:00"]
    assert runners.trend[1].average_runners == 1.5
    assert runners.trend[1].peak_runners == 3


def test_runner_view_absent_payload_is_unavailable_but_keeps_current_limit() -> None:
    views = build_statistics_views(
        {"totals": {"runs": 0}},
        {},
        current_runner_limit=6,
    )

    runners = views.runners
    assert runners.available is False
    assert runners.distribution == ()
    assert runners.trend == ()
    assert runners.peak_runners == 0
    assert runners.average_runners == 0.0
    assert runners.current_limit == 6


def test_runner_emptiness_is_independent_of_launch_count() -> None:
    run_payload = _run_payload()
    run_payload["totals"] = {"runs": 0}
    run_payload["outcomes"] = []
    run_payload["runners"] = {
        "start_ts": 0.0,
        "end_ts": 3_600.0,
        "peak_runners": 1,
        "peak_seconds": 1_200.0,
        "average_runners": 1 / 3,
        "busy_seconds": 1_200.0,
        "busy_share": 1 / 3,
        "runner_seconds": 1_200.0,
        "distribution": [
            {"runners": 0, "seconds": 2_400.0, "share": 2 / 3},
            {"runners": 1, "seconds": 1_200.0, "share": 1 / 3},
        ],
        "trend": [],
        "malformed_rows_skipped": 0,
        "invalid_intervals_skipped": 0,
    }

    views = build_statistics_views(run_payload, _activity_payload())

    # A carry-in runner still renders even when the Runs view has no launches.
    assert views.empty is True
    assert views.runners.available is True
    assert [row.runners for row in views.runners.distribution] == [0, 1]


def test_runner_view_is_frozen() -> None:
    runners = build_statistics_views(_run_payload(), _activity_payload()).runners

    with pytest.raises(FrozenInstanceError):
        runners.peak_runners = 99  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        runners.distribution[0].seconds = 1.0  # type: ignore[misc]


def test_models_are_frozen() -> None:
    views = build_statistics_views(_run_payload(), _activity_payload())

    with pytest.raises(FrozenInstanceError):
        views.overview.agents_run = 99  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        views.xprompts.available = True  # type: ignore[misc]


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
    assert views.xprompts.available is False
    assert views.plans_questions.questions == 0
    assert views.runners.available is False
    assert views.runners.current_limit is None


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


def test_project_display_snapshot_projects_every_project_bearing_row(
    project_display_case: ProjectDisplayCase,
) -> None:
    payload = _run_payload()
    widgets_key = project_display_case.project_key
    payload["workspaces"][0]["project"] = widgets_key  # type: ignore[index]
    payload["work"]["projects"][0]["project"] = widgets_key  # type: ignore[index]
    payload["work"]["changespecs"][0].update(  # type: ignore[index,union-attr]
        {
            "project": widgets_key,
            "name": project_display_case.changespec_key,
        }
    )
    payload["runtime_group_by"] = "project"
    payload["runtime_groups"][0]["group"] = widgets_key  # type: ignore[index]
    snapshot = project_display_case.snapshot

    views = build_statistics_views(
        payload,
        _activity_payload(),
        project_display_snapshot=snapshot,
    )

    project = views.projects.projects[0]
    assert (project.project_key, project.project_label) == (
        widgets_key,
        project_display_case.project_label,
    )
    assert [row.changespec_key for row in project.changespecs] == [
        project_display_case.changespec_key
    ]
    assert (
        project.changespecs[0].changespec_label == project_display_case.changespec_label
    )
    assert (
        project.changespecs[0].project_key,
        project.changespecs[0].project_label,
    ) == (widgets_key, project_display_case.project_label)
    assert (
        views.activity.workspaces[0].project_key,
        views.activity.workspaces[0].project_label,
    ) == (widgets_key, project_display_case.project_label)
    assert (
        views.runtime.rows[0].group_key,
        views.runtime.rows[0].group_label,
    ) == (widgets_key, project_display_case.project_label)
    assert views.projects.projects[1].project_label == "core"


def test_changespec_runtime_groups_are_humanized_without_losing_identity(
    project_display_case: ProjectDisplayCase,
) -> None:
    payload = _run_payload()
    changespec_key, changespec_label = project_display_case.changespec("repair_labels")
    payload["runtime_group_by"] = "changespec"
    payload["runtime_groups"][0]["group"] = changespec_key  # type: ignore[index]

    runtime = build_statistics_views(
        payload,
        _activity_payload(),
        project_display_snapshot=project_display_case.snapshot,
    ).runtime

    assert (runtime.rows[0].group_key, runtime.rows[0].group_label) == (
        changespec_key,
        changespec_label,
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
