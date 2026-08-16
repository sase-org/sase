"""Deterministic Statistics-tab view models for ACE PNG snapshots."""

from __future__ import annotations

from sase.ace.tui.modals.statistics_pane_data import StatisticsViewData
from sase.stats import PerfView, build_perf_view
from sase.stats.perf_query import PerfGroupBy
from sase.stats.ranges import StatsRange
from sase.stats.views import build_statistics_views
from tests.ace.tui.visual._ace_config_center_statistics_fixtures import (
    _ENGINE_KEY,
    _INTEGRATION_KEY,
    _PROJECT_DISPLAY_SNAPSHOT,
    _STATISTICS_NOW,
    _STATISTICS_RANGE,
    _WIDGETS_KEY,
    _xprompts_payload,
)
from tests.stats._views_payloads import (
    perf_logs_payload,
    perf_telemetry_payload,
)


def _populated_statistics_view(
    view: str = "overview",
    selected_range: StatsRange = _STATISTICS_RANGE,
    project_filter: str | None = None,
    xprompt_focus: str | None = None,
    perf_group_by: PerfGroupBy = "subsystem",
) -> StatisticsViewData:
    runtime_group_by = "tribe"
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
            "proposing_agents": 7,
            "approved": 8,
            "rejected": 1,
            "feedback": 1,
            "pending": 1,
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
                    "distinct_changespecs": 3,  # legacy stats wire field
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
                    "distinct_changespecs": 2,  # legacy stats wire field
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
                    "distinct_changespecs": 1,  # legacy stats wire field
                    "unattributed_runs": 2,
                    "total_runtime_seconds": 1_670.0,
                    "last_run_ts": _STATISTICS_NOW - 7_200,
                },
            ],
            "changespecs": [  # legacy stats wire key
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
            "truncated_patch_rows": 0,
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
            "lanes_counted": 37,
            "lanes_without_end_skipped": 4,
            "user_hidden_skipped": 0,
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
            "asking_agents": 6,
            "questions": 13,
            "questions_per_session": [
                {"value": 1, "count": 4},
                {"value": 2, "count": 3},
                {"value": 3, "count": 1},
            ],
            "mean_questions_per_session": 1.625,
        },
    }
    perf = None
    if view == "perf":
        perf = _perf_populated_view(selected_range, perf_group_by)
    return StatisticsViewData(
        view=view,  # type: ignore[arg-type]
        selected_range=selected_range,
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
        perf=perf,
    )


def _perf_populated_view(
    selected_range: StatsRange = _STATISTICS_RANGE,
    group_by: PerfGroupBy = "subsystem",
) -> PerfView:
    previous_logs = perf_logs_payload()
    previous_logs["startup"]["stages"][2]["summary"]["p50"] = 1.2  # type: ignore[index]
    previous_telemetry = perf_telemetry_payload()
    previous_telemetry["histograms"]["sase_agent_run_duration_seconds"]["p95"] = {  # type: ignore[index]
        "resolution": "raw",
        "series": [{"labels": {}, "value": 100.0}],
    }
    return build_perf_view(
        perf_logs_payload(),
        perf_telemetry_payload(),
        selected_range=selected_range,
        previous_perf_payload=previous_logs,
        previous_telemetry_payload=previous_telemetry,
        group_by=group_by,
        now=_STATISTICS_NOW,
    )


def _degraded_perf_logs_payload() -> dict[str, object]:
    payload = perf_logs_payload()
    payload["coverage"] = [
        {
            "source": "startup",
            "path": "/tmp/tui_startup.jsonl",
            "present": True,
            "records_scanned": 3,
            "records_in_window": 3,
            "earliest_ts": _STATISTICS_NOW - 5_000.0,
            "latest_ts": _STATISTICS_NOW - 100.0,
            "truncated": False,
            "malformed_skipped": 0,
        },
        {
            "source": "stalls",
            "path": "/tmp/tui_stalls.jsonl",
            "present": True,
            "records_scanned": 4,
            "records_in_window": 4,
            "earliest_ts": _STATISTICS_NOW - 4_000.0,
            "latest_ts": _STATISTICS_NOW - 200.0,
            "truncated": False,
            "malformed_skipped": 1,
        },
        {
            "source": "launch_timing",
            "path": "/tmp/tui_launch_timing.jsonl",
            "present": True,
            "records_scanned": 4,
            "records_in_window": 4,
            "earliest_ts": _STATISTICS_NOW - 3_000.0,
            "latest_ts": _STATISTICS_NOW - 300.0,
            "truncated": True,
            "malformed_skipped": 0,
        },
        {
            "source": "agent_loads",
            "path": "/tmp/tui_agent_loads.jsonl",
            "present": True,
            "records_scanned": 1,
            "records_in_window": 1,
            "earliest_ts": _STATISTICS_NOW - 2_000.0,
            "latest_ts": _STATISTICS_NOW - 2_000.0,
            "truncated": False,
            "malformed_skipped": 0,
        },
        {
            "source": "git_ops",
            "path": "/tmp/tui_git_ops.jsonl",
            "present": False,
            "records_scanned": 0,
            "records_in_window": 0,
            "earliest_ts": None,
            "latest_ts": None,
            "truncated": False,
            "malformed_skipped": 0,
        },
        {
            "source": "external_tools",
            "path": "/tmp/tui_external_tools.jsonl",
            "present": True,
            "records_scanned": 2,
            "records_in_window": 1,
            "earliest_ts": _STATISTICS_NOW - 1_000.0,
            "latest_ts": _STATISTICS_NOW - 1_000.0,
            "truncated": False,
            "malformed_skipped": 1,
        },
    ]
    return payload


def _degraded_perf_statistics_view(
    view: str = "perf",
    selected_range: StatsRange = _STATISTICS_RANGE,
    project_filter: str | None = None,
    xprompt_focus: str | None = None,
    perf_group_by: PerfGroupBy = "subsystem",
) -> StatisticsViewData:
    perf_view = build_perf_view(
        _degraded_perf_logs_payload(),
        {"enabled": False, "group_by": perf_group_by},
        selected_range=selected_range,
        group_by=perf_group_by,
        now=_STATISTICS_NOW,
    )
    return StatisticsViewData(
        view=view,  # type: ignore[arg-type]
        selected_range=selected_range,
        generated_at=_STATISTICS_NOW,
        views=build_statistics_views(
            {},
            {},
            project_display_snapshot=_PROJECT_DISPLAY_SNAPSHOT,
            current_runner_limit=4,
        ),
        project_filter=project_filter,
        xprompt_focus=xprompt_focus,
        project_display_snapshot=_PROJECT_DISPLAY_SNAPSHOT,
        perf=perf_view,
    )
