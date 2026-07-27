"""General synthetic-data scenarios for the TUI trace benchmark."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.app import AceApp

from ..fixtures import (
    AGENT_SIZES,
    CHANGESPEC_SIZES,
    LARGE_REPLY_SIZES_MB,
    build_fixture,
    make_large_reply,
)
from .common import (
    _read_jsonl,
    _summarize_jk,
    _summarize_spans,
    _wait_for_startup,
)
from .view_hints import _run_view_hints_scenario

_DEFAULT_J_KEYS = 50
_QUERY_EDIT_SEQUENCE: tuple[str, ...] = (
    '"cs_0"',
    '"cs_00"',
    '"cs_000"',
    '"cs_0001"',
    '"cs_0002"',
    "status:Ready",
    "status:Draft",
)


async def _run_scenario(
    cs_count: int,
    agent_count: int,
    *,
    j_keys: int,
    gp_file: Path,
    large_reply_text: str | None,
) -> dict[str, Any]:
    """Run one fixture-size scenario through the ACE TUI."""
    fixture = build_fixture(cs_count, agent_count, gp_file=gp_file)
    started_wall: dict[str, float] = {}
    finished_wall: dict[str, float] = {}

    def _mark(name: str) -> None:
        finished_wall[name] = time.perf_counter()

    def _mark_start(name: str) -> None:
        started_wall[name] = time.perf_counter()

    with patch(
        "sase.ace.changespec.find_all_changespecs_cached",
        return_value=fixture.changespecs,
    ):

        def _apply_query(query: str) -> None:
            from sase.ace.query import parse_query

            app.query_string = query
            app.parsed_query = parse_query(query)  # type: ignore[assignment]
            app._load_changespecs()  # type: ignore[attr-defined]

        _mark_start("cold_start")
        app = AceApp(
            query='"cs_"',
            auto_start_axe=False,
            initial_tab="changespecs",
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            _mark("cold_start")
            await _wait_for_startup(app, pilot)

            _mark_start("query_change")
            _apply_query('"cs_0"')
            await pilot.pause()
            _mark("query_change")

            _mark_start("repeated_query_edits")
            for query in _QUERY_EDIT_SEQUENCE:
                _apply_query(query)
                await pilot.pause()
            _mark("repeated_query_edits")

            _apply_query('"cs_"')
            await pilot.pause()

            _mark_start("jk_burst")
            for _ in range(j_keys):
                await pilot.press("j")
                await pilot.pause(0.005)
            for _ in range(j_keys):
                await pilot.press("k")
                await pilot.pause(0.005)
            _mark("jk_burst")

            _mark_start("auto_refresh_idle")
            app._refresh_display()  # type: ignore[attr-defined]
            await pilot.pause()
            _mark("auto_refresh_idle")

            if large_reply_text is not None and fixture.agents:
                _mark_start("large_reply_select")
                app._agents = fixture.agents  # type: ignore[attr-defined]
                app.current_tab = "agents"  # type: ignore[assignment]
                await pilot.pause()
                await pilot.press("j")
                await pilot.pause(0.05)
                _mark("large_reply_select")

    return {
        "cs_count": cs_count,
        "agent_count": agent_count,
        "wall_ms": {
            name: (finished_wall[name] - started_wall[name]) * 1000.0
            for name in finished_wall
        },
    }


async def _run_full_baseline(
    output_path: Path,
    *,
    trace_path: Path,
    perf_path: Path,
    gp_file: Path,
) -> dict[str, Any]:
    """Run all fixture-size combinations and dump a baseline JSON."""
    paired = list(zip(CHANGESPEC_SIZES, AGENT_SIZES, strict=True))
    large_reply_text = make_large_reply(LARGE_REPLY_SIZES_MB[0])

    scenarios: list[dict[str, Any]] = []
    for cs_count, agent_count in paired:
        if trace_path.exists():
            trace_path.unlink()
        if perf_path.exists():
            perf_path.unlink()
        result = await _run_scenario(
            cs_count,
            agent_count,
            j_keys=_DEFAULT_J_KEYS,
            gp_file=gp_file,
            large_reply_text=large_reply_text,
        )
        result["spans"] = _summarize_spans(_read_jsonl(trace_path))
        result["jk_paint"] = _summarize_jk(_read_jsonl(perf_path))
        scenarios.append(result)

    if trace_path.exists():
        trace_path.unlink()
    if perf_path.exists():
        perf_path.unlink()
    view_hints = await _run_view_hints_scenario(
        gp_file=gp_file,
        artifacts_root=gp_file.parent / "view_hints_artifacts",
        trace_path=trace_path,
    )

    baseline = {
        "version": 2,
        "j_keys_per_burst": _DEFAULT_J_KEYS,
        "query_edit_sequence": list(_QUERY_EDIT_SEQUENCE),
        "large_reply_mb": LARGE_REPLY_SIZES_MB[0],
        "scenarios": scenarios,
        "view_hints": view_hints,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(baseline, indent=2) + "\n")
    return baseline
