from zoneinfo import ZoneInfo

import pytest

from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.views import build_statistics_views
from tests.stats._views_payloads import activity_payload, run_payload


def test_xprompts_absent_section_is_explicitly_unavailable() -> None:
    views = build_statistics_views(
        run_payload(),
        activity_payload(),
        timezone=ZoneInfo("UTC"),
    )

    assert views.xprompts.available is False
    assert views.xprompts.rows == ()
    assert views.xprompts.focus is None


def test_xprompts_present_empty_section_is_available() -> None:
    payload = run_payload()
    payload["xprompts"] = {
        "runs_with_xprompts": 0,
        "runs_without_xprompts": 6,
        "distinct_xprompts": 0,
        "total_references": 0,
        "rows": [],
        "truncated_rows": 0,
        "focus": None,
    }

    xprompts = build_statistics_views(
        payload,
        activity_payload(),
        timezone=ZoneInfo("UTC"),
    ).xprompts

    assert xprompts.available is True
    assert xprompts.runs_with_xprompts == 0
    assert xprompts.runs_without_xprompts == 6
    assert xprompts.rows == ()
    assert xprompts.focus is None


def test_xprompts_populated_rows_build_shares_tags_and_project_labels() -> None:
    payload = run_payload()
    payload["xprompts"] = {
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
        payload,
        activity_payload(),
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
    payload = run_payload()
    payload["xprompts"] = {
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
        payload,
        activity_payload(),
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
    payload = run_payload()
    payload["xprompts"] = {
        "runs_with_xprompts": 0,
        "runs_without_xprompts": 6,
        "distinct_xprompts": 0,
        "total_references": 0,
        "rows": [],
        "truncated_rows": 0,
        "focus": {"name": "missing", "found": False},
    }

    focus = build_statistics_views(
        payload,
        activity_payload(),
        timezone=ZoneInfo("UTC"),
    ).xprompts.focus

    assert focus is not None
    assert focus.name == "missing"
    assert focus.found is False
    assert focus.runs == 0
    assert focus.buckets == ()
