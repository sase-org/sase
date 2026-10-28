"""Small reusable wire payloads for Statistics pane tests."""

from __future__ import annotations

from sase.stats.query import RuntimeGroupBy
from sase.stats.ranges import StatsRange

NOW = 1_720_268_400.0


def run_payload(selected_range: StatsRange, group_by: RuntimeGroupBy) -> dict:
    return {
        "start_ts": selected_range.start_ts,
        "end_ts": selected_range.end_ts,
        "runtime_group_by": group_by,
        "bucket_seconds": 86_400,
        "totals": {
            "runs": 6,
            "completed": 4,
            "failed": 1,
            "other_terminal": 0,
            "in_progress": 1,
            "waiting": 0,
        },
        "outcomes": [
            {"name": "completed", "count": 4},
            {"name": "failed", "count": 1},
        ],
        "retries": {"chains": 1, "attempts": 2, "kills": 0},
        "providers": [
            {
                "provider": "codex",
                "model": "gpt-5.6",
                "effort": "high",
                "runs": 4,
                "success_rate": 0.75,
                "mean_runtime_seconds": 125.0,
            },
            {
                "provider": "claude",
                "model": "opus",
                "effort": "default",
                "runs": 2,
                "success_rate": 0.5,
                "mean_runtime_seconds": 240.0,
            },
        ],
        "commits": {
            "total_commits": 7,
            "committing_agents": 3,
            "committing_runs": 3,
            "average_per_committing_agent": 7 / 3,
            "distribution": {"zero": 3, "one": 1, "two": 1, "three_plus": 1},
            "top_repos": [{"name": "sase", "count": 7}],
        },
        "plans": {
            "proposed": 1,
            "approved": 1,
            "rejected": 0,
            "pending": 0,
        },
        "questions": {"sessions": 1, "asking_agents": 1},
        "workspaces": [{"project": "sase", "workspace_num": 15, "runs": 6}],
        "buckets": [
            {"start_ts": selected_range.start_ts, "runs": 2},
            {"start_ts": selected_range.start_ts + 86_400, "runs": 4},
        ],
        "runtime_groups": [
            {
                "group": "alpha",
                "runs": 3,
                "total_seconds": 600.0,
                "mean_seconds": 200.0,
                "p50_seconds": 180.0,
                "p95_seconds": 290.0,
                "max_seconds": 300.0,
            }
        ],
        "work": {
            "projects": [
                {
                    "project": "sase",
                    "runs": 4,
                    "completed": 3,
                    "failed": 1,
                    "success_rate": 0.75,
                    "commits": 5,
                    "distinct_changespecs": 1,  # legacy stats wire field
                    "unattributed_runs": 1,
                    "total_runtime_seconds": 500.0,
                    "last_run_ts": NOW,
                },
                {
                    "project": "core",
                    "runs": 2,
                    "completed": 1,
                    "failed": 0,
                    "success_rate": 1.0,
                    "commits": 2,
                    "distinct_changespecs": 1,  # legacy stats wire field
                    "unattributed_runs": 0,
                    "total_runtime_seconds": 100.0,
                    "last_run_ts": NOW - 60,
                },
            ],
            "changespecs": [  # legacy stats wire key
                {
                    "project": "sase",
                    "name": "statistics-projects",
                    "status": "Ready",
                    "has_pr": True,
                    "runs": 3,
                    "distinct_agents": 2,
                    "commits": 5,
                    "total_runtime_seconds": 420.0,
                    "last_run_ts": NOW,
                },
                {
                    "project": "core",
                    "name": "stats-wire",
                    "status": "Submitted",
                    "has_pr": True,
                    "runs": 2,
                    "distinct_agents": 1,
                    "commits": 2,
                    "total_runtime_seconds": 100.0,
                    "last_run_ts": NOW - 60,
                },
            ],
            "unattributed_runs": 1,
            "truncated_patch_rows": 0,
            "malformed_spec_files_skipped": 0,
        },
        "runners": {
            "start_ts": float(selected_range.start_ts),
            "end_ts": float(selected_range.end_ts),
            "peak_runners": 2,
            "peak_seconds": 1_800.0,
            "average_runners": 1.0,
            "busy_seconds": 5_400.0,
            "busy_share": 0.75,
            "runner_seconds": 7_200.0,
            "distribution": [
                {"runners": 0, "seconds": 1_800.0, "share": 0.25},
                {"runners": 1, "seconds": 3_600.0, "share": 0.5},
                {"runners": 2, "seconds": 1_800.0, "share": 0.25},
            ],
            "trend": [
                {
                    "start_ts": float(selected_range.start_ts),
                    "end_ts": float(selected_range.start_ts + 86_400),
                    "average_runners": 1.0,
                    "peak_runners": 2,
                    "busy_seconds": 2_700.0,
                    "runner_seconds": 3_600.0,
                }
            ],
            "lanes_counted": 3,
            "lanes_without_end_skipped": 0,
            "user_hidden_skipped": 0,
            "malformed_rows_skipped": 0,
            "invalid_intervals_skipped": 0,
        },
        "macros": {
            "runs_with_macros": 4,
            "runs_without_macros": 2,
            "distinct_macros": 2,
            "total_references": 5,
            "truncated_rows": 0,
            "rows": [
                {
                    "name": "split_file",
                    "kind": "part",
                    "tags": ["files"],
                    "runs": 3,
                    "references": 4,
                    "distinct_agents": 2,
                    "completed": 2,
                    "failed": 1,
                    "success_rate": 2 / 3,
                    "total_runtime_seconds": 360.0,
                    "mean_runtime_seconds": 120.0,
                    "first_run_ts": NOW - 3_600,
                    "last_run_ts": NOW,
                    "models": [
                        {"name": "gpt-5.6", "count": 2},
                        {"name": "opus", "count": 1},
                    ],
                    "projects": [
                        {"name": "sase", "count": 2},
                        {"name": "core", "count": 1},
                    ],
                    "partners": [{"name": "gh", "count": 2}],
                    "models_truncated": 0,
                    "projects_truncated": 0,
                    "partners_truncated": 0,
                },
                {
                    "name": "gh",
                    "kind": "workflow",
                    "tags": ["vcs"],
                    "runs": 1,
                    "references": 1,
                    "distinct_agents": 1,
                    "completed": 1,
                    "failed": 0,
                    "success_rate": 1.0,
                    "total_runtime_seconds": 90.0,
                    "mean_runtime_seconds": 90.0,
                    "first_run_ts": NOW - 60,
                    "last_run_ts": NOW - 60,
                    "models": [],
                    "projects": [{"name": "sase", "count": 1}],
                    "partners": [],
                    "models_truncated": 0,
                    "projects_truncated": 0,
                    "partners_truncated": 0,
                },
            ],
            "focus": None,
        },
    }


def activity_payload() -> dict:
    return {
        "skills": [{"name": "sase_plan", "count": 8, "distinct_agents": 3}],
        "memories": [{"name": "tui_perf.md", "count": 4, "distinct_agents": 2}],
        "plans": {
            "proposed": 3,
            "proposing_agents": 2,
            "tiers": [
                {"name": "epic", "count": 1},
                {"name": "tale", "count": 2},
            ],
            "approved": 2,
            "rejected": 0,
            "feedback": 0,
            "pending": 1,
            "phases_per_epic": [{"value": 5, "count": 1}],
            "mean_phases_per_epic": 5.0,
        },
        "questions": {
            "sessions": 2,
            "asking_agents": 2,
            "questions": 3,
            "questions_per_session": [
                {"value": 1, "count": 1},
                {"value": 2, "count": 1},
            ],
            "mean_questions_per_session": 1.5,
        },
    }
