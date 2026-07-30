"""Deterministic Statistics-tab models for ACE PNG snapshots."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.ace.tui.modals.statistics_pane_data import StatisticsViewData
from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.ranges import StatsRange
from sase.stats.views import build_statistics_views

_STATISTICS_NOW = 1_720_268_400.0
_STATISTICS_RANGE = StatsRange(
    int(_STATISTICS_NOW - 7 * 86_400),
    int(_STATISTICS_NOW),
    "2024-07-01 18:20 EDT – 2024-07-08 18:20 EDT",
    "Last 7 days",
)
_WIDGETS_KEY = "gh_acme__widgets"
_ENGINE_KEY = "gh_acme__engine"
_INTEGRATION_KEY = "gh_acme__integration"
_PROJECT_DISPLAY_SNAPSHOT = ProjectDisplaySnapshot(
    {
        _WIDGETS_KEY: "widgets",
        _ENGINE_KEY: "engine",
        _INTEGRATION_KEY: "integration",
    }
)


def _xprompts_payload(
    selected_range: StatsRange,
    xprompt_focus: str | None,
) -> dict[str, object]:
    rows = [
        {
            "name": "split_file",
            "kind": "part",
            "tags": ["files"],
            "runs": 14,
            "references": 17,
            "distinct_agents": 9,
            "completed": 12,
            "failed": 1,
            "success_rate": 12 / 14,
            "total_runtime_seconds": 6_480.0,
            "mean_runtime_seconds": 462.9,
            "first_run_ts": _STATISTICS_NOW - 6 * 86_400,
            "last_run_ts": _STATISTICS_NOW - 320,
            "models": [
                {"name": "gpt-5.6", "count": 8},
                {"name": "opus-4.1", "count": 4},
                {"name": "2.5-pro", "count": 2},
            ],
            "projects": [
                {"name": _WIDGETS_KEY, "count": 8},
                {"name": _ENGINE_KEY, "count": 4},
                {"name": _INTEGRATION_KEY, "count": 2},
            ],
            "partners": [
                {"name": "gh", "count": 7},
                {"name": "sase_plan", "count": 4},
            ],
        },
        {
            "name": "gh",
            "kind": "workflow",
            "tags": ["rollover", "vcs"],
            "runs": 9,
            "references": 9,
            "distinct_agents": 7,
            "completed": 8,
            "failed": 1,
            "success_rate": 8 / 9,
            "total_runtime_seconds": 4_860.0,
            "mean_runtime_seconds": 540.0,
            "first_run_ts": _STATISTICS_NOW - 5 * 86_400,
            "last_run_ts": _STATISTICS_NOW - 1_800,
            "models": [
                {"name": "gpt-5.6", "count": 6},
                {"name": "opus-4.1", "count": 3},
            ],
            "projects": [
                {"name": _WIDGETS_KEY, "count": 6},
                {"name": _ENGINE_KEY, "count": 3},
            ],
            "partners": [{"name": "split_file", "count": 7}],
        },
        {
            "name": "sase_plan",
            "kind": "part",
            "tags": ["planning"],
            "runs": 6,
            "references": 6,
            "distinct_agents": 5,
            "completed": 5,
            "failed": 0,
            "success_rate": 5 / 6,
            "total_runtime_seconds": 3_120.0,
            "mean_runtime_seconds": 520.0,
            "first_run_ts": _STATISTICS_NOW - 4 * 86_400,
            "last_run_ts": _STATISTICS_NOW - 7_200,
            "models": [
                {"name": "opus-4.1", "count": 4},
                {"name": "gpt-5.6", "count": 2},
            ],
            "projects": [
                {"name": _WIDGETS_KEY, "count": 5},
                {"name": _INTEGRATION_KEY, "count": 1},
            ],
            "partners": [{"name": "split_file", "count": 4}],
        },
        {
            "name": "sase/reads",
            "kind": "swarm",
            "tags": ["research"],
            "runs": 4,
            "references": 4,
            "distinct_agents": 4,
            "completed": 4,
            "failed": 0,
            "success_rate": 1.0,
            "total_runtime_seconds": 1_920.0,
            "mean_runtime_seconds": 480.0,
            "first_run_ts": _STATISTICS_NOW - 2 * 86_400,
            "last_run_ts": _STATISTICS_NOW - 10_800,
            "models": [
                {"name": "opus-4.1", "count": 3},
                {"name": "gpt-5.6", "count": 1},
            ],
            "projects": [{"name": _WIDGETS_KEY, "count": 4}],
            "partners": [{"name": "gh", "count": 4}],
        },
    ]
    focus: dict[str, object] | None = None
    if xprompt_focus is not None:
        found = xprompt_focus == "split_file"
        focus = {
            "name": xprompt_focus,
            "found": found,
            "kind": "part" if found else "unknown",
            "tags": ["files"] if found else [],
            "runs": 14 if found else 0,
            "references": 17 if found else 0,
            "distinct_agents": 9 if found else 0,
            "completed": 12 if found else 0,
            "failed": 1 if found else 0,
            "success_rate": 12 / 14 if found else 0.0,
            "total_runtime_seconds": 6_480.0 if found else 0.0,
            "mean_runtime_seconds": 462.9 if found else None,
            "first_run_ts": _STATISTICS_NOW - 6 * 86_400 if found else 0.0,
            "last_run_ts": _STATISTICS_NOW - 320 if found else 0.0,
            "models": (
                [
                    {"name": "gpt-5.6", "count": 8},
                    {"name": "opus-4.1", "count": 4},
                    {"name": "2.5-pro", "count": 2},
                ]
                if found
                else []
            ),
            "providers": (
                [
                    {"name": "codex", "count": 8},
                    {"name": "claude", "count": 4},
                    {"name": "gemini", "count": 2},
                ]
                if found
                else []
            ),
            "projects": (
                [
                    {"name": _WIDGETS_KEY, "count": 8},
                    {"name": _ENGINE_KEY, "count": 4},
                    {"name": _INTEGRATION_KEY, "count": 2},
                ]
                if found
                else []
            ),
            "partners": (
                [
                    {"name": "gh", "count": 7},
                    {"name": "sase_plan", "count": 4},
                ]
                if found
                else []
            ),
            "tribes": (
                [
                    {"name": "platform", "count": 8},
                    {"name": "workflow", "count": 4},
                    {"name": "research", "count": 2},
                ]
                if found
                else []
            ),
            "buckets": (
                [
                    {
                        "start_ts": selected_range.start_ts + index * 86_400,
                        "runs": runs,
                    }
                    for index, runs in enumerate((1, 3, 2, 1, 3, 2, 2))
                ]
                if found
                else []
            ),
        }
    return {
        "runs_with_xprompts": 23,
        "runs_without_xprompts": 9,
        "distinct_xprompts": 4,
        "total_references": 36,
        "truncated_rows": 0,
        "rows": rows,
        "focus": focus,
    }


def _populated_statistics_view(
    view: str = "overview",
    selected_range: StatsRange = _STATISTICS_RANGE,
    runtime_group_by: str = "tribe",
    project_filter: str | None = None,
    xprompt_focus: str | None = None,
) -> StatisticsViewData:
    run_payload = {
        "start_ts": selected_range.start_ts,
        "end_ts": selected_range.end_ts,
        "runtime_group_by": runtime_group_by,
        "bucket_seconds": 86_400,
        "totals": {
            "runs": 32,
            "completed": 25,
            "failed": 4,
            "other_terminal": 1,
            "in_progress": 2,
            "waiting": 0,
        },
        "outcomes": [
            {"name": "completed", "count": 25},
            {"name": "failed", "count": 4},
            {"name": "stopped", "count": 1},
        ],
        "retries": {"chains": 4, "attempts": 7, "kills": 2},
        "providers": [
            {
                "provider": "codex",
                "model": "gpt-5.6",
                "effort": "high",
                "runs": 18,
                "success_rate": 0.89,
                "mean_runtime_seconds": 442.0,
            },
            {
                "provider": "claude",
                "model": "opus-4.1",
                "effort": "xhigh",
                "runs": 9,
                "success_rate": 0.78,
                "mean_runtime_seconds": 681.0,
            },
            {
                "provider": "gemini",
                "model": "2.5-pro",
                "effort": "default",
                "runs": 5,
                "success_rate": 0.60,
                "mean_runtime_seconds": 318.0,
            },
        ],
        "commits": {
            "total_commits": 41,
            "committing_agents": 19,
            "average_per_committing_agent": 2.16,
            "distribution": {"zero": 13, "one": 7, "two": 5, "three_plus": 7},
            "top_repos": [
                {"name": "sase", "count": 26},
                {"name": "sase-core", "count": 11},
                {"name": "sase-github", "count": 4},
            ],
        },
        "plans": {
            "proposed": 11,
            "approved": 8,
            "rejected": 1,
            "pending": 2,
        },
        "questions": {"sessions": 8, "asking_agents": 6},
        "workspaces": [
            {"project": _WIDGETS_KEY, "workspace_num": 15, "runs": 12},
            {"project": _WIDGETS_KEY, "workspace_num": 18, "runs": 9},
            {"project": _ENGINE_KEY, "workspace_num": 3, "runs": 6},
        ],
        "buckets": [
            {"start_ts": selected_range.start_ts + index * 86_400, "runs": runs}
            for index, runs in enumerate((3, 7, 2, 6, 4, 5, 5))
        ],
        "runtime_groups": [
            {
                "group": "platform",
                "runs": 12,
                "total_seconds": 6_840.0,
                "mean_seconds": 570.0,
                "p50_seconds": 480.0,
                "p95_seconds": 1_120.0,
                "max_seconds": 1_340.0,
            },
            {
                "group": "workflow",
                "runs": 9,
                "total_seconds": 4_050.0,
                "mean_seconds": 450.0,
                "p50_seconds": 390.0,
                "p95_seconds": 780.0,
                "max_seconds": 900.0,
            },
            {
                "group": "research",
                "runs": 7,
                "total_seconds": 2_240.0,
                "mean_seconds": 320.0,
                "p50_seconds": 275.0,
                "p95_seconds": 590.0,
                "max_seconds": 650.0,
            },
        ],
        "work": {
            "projects": [
                {
                    "project": _WIDGETS_KEY,
                    "runs": 18,
                    "completed": 15,
                    "failed": 2,
                    "other_terminal": 0,
                    "in_progress": 1,
                    "waiting": 0,
                    "success_rate": 15 / 17,
                    "commits": 26,
                    "distinct_changespecs": 3,
                    "unattributed_runs": 6,
                    "total_runtime_seconds": 9_480.0,
                    "last_run_ts": _STATISTICS_NOW - 320,
                },
                {
                    "project": _ENGINE_KEY,
                    "runs": 9,
                    "completed": 7,
                    "failed": 1,
                    "other_terminal": 0,
                    "in_progress": 1,
                    "waiting": 0,
                    "success_rate": 0.875,
                    "commits": 11,
                    "distinct_changespecs": 2,
                    "unattributed_runs": 4,
                    "total_runtime_seconds": 4_860.0,
                    "last_run_ts": _STATISTICS_NOW - 1_800,
                },
                {
                    "project": _INTEGRATION_KEY,
                    "runs": 5,
                    "completed": 3,
                    "failed": 1,
                    "other_terminal": 1,
                    "in_progress": 0,
                    "waiting": 0,
                    "success_rate": 0.6,
                    "commits": 4,
                    "distinct_changespecs": 1,
                    "unattributed_runs": 2,
                    "total_runtime_seconds": 1_670.0,
                    "last_run_ts": _STATISTICS_NOW - 7_200,
                },
            ],
            "changespecs": [
                {
                    "project": _WIDGETS_KEY,
                    "name": f"{_WIDGETS_KEY}_statistics-project-views",
                    "status": "Ready",
                    "has_pr": False,
                    "runs": 6,
                    "distinct_agents": 4,
                    "commits": 10,
                    "total_runtime_seconds": 3_840.0,
                    "last_run_ts": _STATISTICS_NOW - 320,
                },
                {
                    "project": _WIDGETS_KEY,
                    "name": f"{_WIDGETS_KEY}_agent-artifact-index",
                    "status": "Submitted",
                    "has_pr": True,
                    "runs": 4,
                    "distinct_agents": 3,
                    "commits": 9,
                    "total_runtime_seconds": 2_520.0,
                    "last_run_ts": _STATISTICS_NOW - 3_600,
                },
                {
                    "project": _ENGINE_KEY,
                    "name": f"{_ENGINE_KEY}_work-statistics-wire",
                    "status": "Mailed",
                    "has_pr": True,
                    "runs": 3,
                    "distinct_agents": 2,
                    "commits": 7,
                    "total_runtime_seconds": 1_920.0,
                    "last_run_ts": _STATISTICS_NOW - 1_800,
                },
                {
                    "project": _ENGINE_KEY,
                    "name": f"{_ENGINE_KEY}_runtime-groups",
                    "status": "Archived",
                    "has_pr": False,
                    "runs": 2,
                    "distinct_agents": 2,
                    "commits": 4,
                    "total_runtime_seconds": 1_140.0,
                    "last_run_ts": _STATISTICS_NOW - 14_400,
                },
                {
                    "project": _INTEGRATION_KEY,
                    "name": f"{_INTEGRATION_KEY}_provider-rollups",
                    "status": "unknown",
                    "has_pr": False,
                    "runs": 3,
                    "distinct_agents": 2,
                    "commits": 4,
                    "total_runtime_seconds": 980.0,
                    "last_run_ts": _STATISTICS_NOW - 7_200,
                },
            ],
            "unattributed_runs": 12,
            "truncated_changespec_rows": 0,
            "malformed_spec_files_skipped": 0,
        },
        "runners": {
            "start_ts": float(selected_range.start_ts),
            "end_ts": float(selected_range.end_ts),
            "peak_runners": 5,
            "peak_seconds": 25_920.0,
            "average_runners": 1.9,
            "busy_seconds": 518_400.0,
            "busy_share": 6 / 7,
            "runner_seconds": 1_149_120.0,
            "distribution": [
                {"runners": 0, "seconds": 86_400.0, "share": 1 / 7},
                {"runners": 1, "seconds": 172_800.0, "share": 2 / 7},
                {"runners": 2, "seconds": 172_800.0, "share": 2 / 7},
                {"runners": 3, "seconds": 86_400.0, "share": 1 / 7},
                {"runners": 4, "seconds": 60_480.0, "share": 0.1},
                {"runners": 5, "seconds": 25_920.0, "share": 3 / 70},
            ],
            "trend": [
                {
                    "start_ts": float(selected_range.start_ts + index * 86_400),
                    "end_ts": float(selected_range.start_ts + (index + 1) * 86_400),
                    "average_runners": average,
                    "peak_runners": peak,
                    "busy_seconds": busy,
                    "runner_seconds": runner_time,
                }
                for index, (average, peak, busy, runner_time) in enumerate(
                    (
                        (0.5, 1, 43_200.0, 43_200.0),
                        (1.25, 2, 75_600.0, 108_000.0),
                        (2.5, 4, 86_400.0, 216_000.0),
                        (3.8, 5, 86_400.0, 328_320.0),
                        (1.8, 3, 82_800.0, 155_520.0),
                        (2.2, 4, 86_400.0, 190_080.0),
                        (1.25, 2, 57_600.0, 108_000.0),
                    )
                )
            ],
            "malformed_rows_skipped": 2,
            "invalid_intervals_skipped": 1,
        },
        "xprompts": _xprompts_payload(selected_range, xprompt_focus),
    }
    activity_payload = {
        "skills": [
            {"name": "sase_plan", "count": 18, "distinct_agents": 9},
            {"name": "sase_repo", "count": 12, "distinct_agents": 7},
            {"name": "sase_memory_read", "count": 8, "distinct_agents": 5},
        ],
        "memories": [
            {"name": "tui_perf.md", "count": 7, "distinct_agents": 4},
            {"name": "xprompts.md", "count": 5, "distinct_agents": 3},
        ],
        "plans": {
            "proposed": 11,
            "tiers": [
                {"name": "epic", "count": 4},
                {"name": "tale", "count": 7},
            ],
            "approved": 8,
            "rejected": 1,
            "pending": 2,
            "phases_per_epic": [
                {"value": 3, "count": 1},
                {"value": 5, "count": 2},
                {"value": 7, "count": 1},
            ],
            "mean_phases_per_epic": 5.0,
        },
        "questions": {
            "sessions": 8,
            "questions": 13,
            "questions_per_session": [
                {"value": 1, "count": 4},
                {"value": 2, "count": 3},
                {"value": 3, "count": 1},
            ],
            "mean_questions_per_session": 1.625,
        },
    }
    return StatisticsViewData(
        view=view,  # type: ignore[arg-type]
        selected_range=selected_range,
        runtime_group_by=runtime_group_by,  # type: ignore[arg-type]
        generated_at=_STATISTICS_NOW,
        views=build_statistics_views(
            run_payload,
            activity_payload,
            previous_run_payload={"totals": {"runs": 24}},
            project_display_snapshot=_PROJECT_DISPLAY_SNAPSHOT,
            current_runner_limit=4,
        ),
        project_filter=project_filter,
        xprompt_focus=xprompt_focus,
        project_display_snapshot=_PROJECT_DISPLAY_SNAPSHOT,
    )


def _patch_statistics_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)
    monkeypatch.setattr(
        sp,
        "load_statistics_view",
        lambda view, selected_range, runtime_group_by, project_filter=None, xprompt_focus=None: (
            _populated_statistics_view(
                view,
                selected_range,
                runtime_group_by,
                project_filter,
                xprompt_focus,
            )
        ),
    )


def _patch_statistics_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)
    monkeypatch.setattr(
        sp,
        "load_statistics_view",
        lambda view, selected_range, runtime_group_by, project_filter=None, xprompt_focus=None: (
            StatisticsViewData(
                view=view,
                selected_range=selected_range,
                runtime_group_by=runtime_group_by,
                generated_at=_STATISTICS_NOW,
                views=build_statistics_views({}, {}),
                project_filter=project_filter,
                xprompt_focus=xprompt_focus,
            )
        ),
    )


def _patch_statistics_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)

    def stay_loading(self: StatisticsPane) -> None:
        self._loading = True
        self._update_heading()
        self._paint_loading()

    monkeypatch.setattr(StatisticsPane, "_start_load", stay_loading)


__all__ = [
    "_patch_statistics_empty",
    "_patch_statistics_loading",
    "_patch_statistics_populated",
]
