"""Disk-backed Agents-tab view-hints scenarios for the TUI trace benchmark."""

from __future__ import annotations

import statistics
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.app import AceApp
from sase.ace.tui.models.fold_state import FoldLevel

from ..fixtures import (
    HINT_FAMILY_MEMBER_COUNT,
    HINT_REPLY_SIZE_KB,
    make_hint_agent,
    make_hint_family_container,
)
from .common import _read_jsonl, _summarize_spans, _wait_for_startup

_HINT_RENDER_SPAN = "widget.prompt_panel.update_display_with_hints"

VIEW_HINTS_STEPS: tuple[str, ...] = (
    "large_reply_first_press",
    "large_reply_repeat_press",
    "family_container_press",
    "family_container_unfolded_press",
    "hint_mode_auto_refresh",
)
VIEW_HINTS_BASELINE_PATH = (
    Path(__file__).parents[1] / "baselines" / "view_hints_baseline.json"
)
VIEW_HINTS_BASELINE_RUNS = 5


def _summarize_hint_counters(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the size counters carried on the hint-render span."""
    hint_records = [r for r in records if r.get("span") == _HINT_RENDER_SPAN]
    if not hint_records:
        return {}
    return {
        "renders": len(hint_records),
        "annotated_chars": int(
            statistics.median(int(r.get("annotated_chars", 0)) for r in hint_records)
        ),
        "hints": int(statistics.median(int(r.get("hints", 0)) for r in hint_records)),
        "commit_views": int(
            statistics.median(int(r.get("commit_views", 0)) for r in hint_records)
        ),
        "header_summary": sorted(
            {str(r.get("header_summary", "")) for r in hint_records}
        ),
        "family_container": sorted(
            {bool(r.get("family_container")) for r in hint_records}
        ),
    }


async def _run_view_hints_scenario(
    *,
    gp_file: Path,
    artifacts_root: Path,
    trace_path: Path,
) -> dict[str, Any]:
    """Drive the Agents-tab ``v`` keypath and time each step separately."""
    plain_agent = make_hint_agent(
        1,
        artifacts_root=artifacts_root,
        project_file=str(gp_file),
    )
    family_agent = make_hint_family_container(
        artifacts_root=artifacts_root,
        project_file=str(gp_file),
    )

    steps: dict[str, dict[str, Any]] = {}

    def _trace_len() -> int:
        return len(_read_jsonl(trace_path))

    with patch("sase.ace.changespec.find_all_changespecs_cached", return_value=[]):
        app = AceApp(
            query='"hint_bench"',
            auto_start_axe=False,
            initial_tab="agents",
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            await _wait_for_startup(app, pilot)

            app._load_agents = lambda *_a, **_k: None  # type: ignore[assignment]
            app._schedule_agents_async_refresh = lambda *_a, **_k: None  # type: ignore[assignment]
            await pilot.pause()

            async def _select(agent: Any) -> None:
                app._agents = [agent]  # type: ignore[attr-defined]
                app.current_idx = 0
                app._refresh_agents_display()  # type: ignore[attr-defined]
                await pilot.pause()

            async def _teardown_bar() -> None:
                app._remove_hint_input_bar()  # type: ignore[attr-defined]
                await pilot.pause()

            async def _timed(step: str, action: Any) -> None:
                cursor = _trace_len()
                started = time.perf_counter()
                await action()
                await pilot.pause()
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                records = _read_jsonl(trace_path)[cursor:]
                steps[step] = {
                    "wall_ms": elapsed_ms,
                    "spans": _summarize_spans(records),
                    "hint_counters": _summarize_hint_counters(records),
                }

            async def _press_v() -> None:
                await pilot.press("v")

            await _select(plain_agent)
            await _timed("large_reply_first_press", _press_v)

            await _teardown_bar()
            await _timed("large_reply_repeat_press", _press_v)

            async def _auto_refresh() -> None:
                app._refresh_agents_display()  # type: ignore[attr-defined]

            await _timed("hint_mode_auto_refresh", _auto_refresh)
            await _teardown_bar()

            await _select(family_agent)
            await _timed("family_container_press", _press_v)
            await _teardown_bar()

            app.panel_fold_level = FoldLevel.FULLY_EXPANDED  # type: ignore[assignment]
            await pilot.pause()
            await _timed("family_container_unfolded_press", _press_v)
            await _teardown_bar()

    return {
        "reply_kb": HINT_REPLY_SIZE_KB,
        "family_members": HINT_FAMILY_MEMBER_COUNT,
        "steps": steps,
    }


async def run_view_hints_baseline(
    *,
    gp_file: Path,
    trace_path: Path,
    runs: int = VIEW_HINTS_BASELINE_RUNS,
) -> dict[str, Any]:
    """Run the view-hints scenario repeatedly and aggregate the samples."""
    raw_runs: list[dict[str, Any]] = []
    for run_idx in range(runs):
        if trace_path.exists():
            trace_path.unlink()
        raw_runs.append(
            await _run_view_hints_scenario(
                gp_file=gp_file,
                artifacts_root=gp_file.parent / f"view_hints_artifacts_{run_idx}",
                trace_path=trace_path,
            )
        )

    aggregate: dict[str, Any] = {}
    for step in VIEW_HINTS_STEPS:
        step_runs = [r["steps"][step] for r in raw_runs if step in r["steps"]]
        if not step_runs:
            continue
        span_names = sorted({name for r in step_runs for name in r["spans"]})
        aggregate[step] = {
            "wall_ms": statistics.median(float(r["wall_ms"]) for r in step_runs),
            "hint_counters": next(
                (r["hint_counters"] for r in step_runs if r.get("hint_counters")),
                {},
            ),
            "spans": {
                name: {
                    "p50_ms": statistics.median(
                        float(r["spans"][name]["p50_ms"])
                        for r in step_runs
                        if name in r["spans"]
                    ),
                    "max_ms": max(
                        float(r["spans"][name]["max_ms"])
                        for r in step_runs
                        if name in r["spans"]
                    ),
                }
                for name in span_names
            },
        }

    return {
        "version": 1,
        "runs": runs,
        "reply_kb": HINT_REPLY_SIZE_KB,
        "family_members": HINT_FAMILY_MEMBER_COUNT,
        "steps": VIEW_HINTS_STEPS,
        "median": aggregate,
        "raw_runs": raw_runs,
    }
