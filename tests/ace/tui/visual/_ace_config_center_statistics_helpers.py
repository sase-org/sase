"""Deterministic Statistics-tab models for ACE PNG snapshots."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.ace.tui.modals.statistics_pane_data import StatisticsViewData
from sase.stats.ranges import StatsRange
from sase.stats.views import build_statistics_views

_STATISTICS_NOW = 1_720_268_400.0
_STATISTICS_RANGE = StatsRange(
    int(_STATISTICS_NOW - 7 * 86_400),
    int(_STATISTICS_NOW),
    "2024-07-01 18:20 EDT – 2024-07-08 18:20 EDT",
)


def _populated_statistics_view(
    view: str = "overview",
    selected_range: StatsRange = _STATISTICS_RANGE,
    runtime_group_by: str = "tribe",
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
        "questions": {"sessions": 8, "asking_agents": 6},
        "workspaces": [
            {"project": "sase", "workspace_num": 15, "runs": 12},
            {"project": "sase", "workspace_num": 18, "runs": 9},
            {"project": "sase-core", "workspace_num": 3, "runs": 6},
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
    }
    activity_payload = {
        "skills": [
            {"name": "sase_beads", "count": 18, "distinct_agents": 9},
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
        ),
    )


def _patch_statistics_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)
    monkeypatch.setattr(
        sp,
        "load_statistics_view",
        lambda view, selected_range, runtime_group_by: _populated_statistics_view(
            view, selected_range, runtime_group_by
        ),
    )


def _patch_statistics_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "resolve_preset", lambda _key: _STATISTICS_RANGE)
    monkeypatch.setattr(
        sp,
        "load_statistics_view",
        lambda view, selected_range, runtime_group_by: StatisticsViewData(
            view=view,
            selected_range=selected_range,
            runtime_group_by=runtime_group_by,
            generated_at=_STATISTICS_NOW,
            views=build_statistics_views({}, {}),
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
