"""Shared deterministic Statistics-tab fixtures for ACE PNG snapshots."""

from __future__ import annotations

from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.ranges import StatsRange

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
