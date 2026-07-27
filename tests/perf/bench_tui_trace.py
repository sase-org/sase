"""Phase 1 synthetic-data benchmark harness for the ace TUI.

Bead sase-w.1 / sdd/plans/202604/tui_perf_overhaul_1.md.

Drives the ace TUI through ``Pilot`` with ``SASE_TUI_TRACE=1`` (and the
existing ``SASE_TUI_PERF=1`` for j/k key-to-paint samples) enabled, against
synthetic ChangeSpec / Agent / large-reply fixtures. Captures span timings
to ``tui_trace.jsonl`` and writes a structured baseline numbers JSON next
to it so later phases can diff against it.

Marked ``slow`` so it does not run as part of the default ``just test``
suite — run explicitly with::

    pytest -s -m slow tests/perf/bench_tui_trace.py

Or as a script::

    python -m tests.perf.bench_tui_trace --output baseline.json

Scenarios per fixture size:

- cold start
- query change
- 50-key j/k burst
- auto-refresh with no changes
- large-reply select

The Agents-tab ``v`` keypath has its own scenario set (``VIEW_HINTS_STEPS``,
bead sase-a5.1 / plans:202607/agents_view_hints_perf.md), run separately
because it needs disk-backed agent artifacts rather than the disk-free rows
the other scenarios share. Its committed baseline lives at
``tests/perf/baselines/view_hints_baseline.json``; regenerate it with::

    python -m tests.perf.bench_tui_trace --view-hints-baseline

Out of scope: any actual hot-path optimization (these scenarios only measure).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.app import AceApp
from sase.ace.tui.models.fold_state import FoldLevel
from sase.xprompt import xprompt_inspect

from .fixtures import (
    AGENT_SIZES,
    CHANGESPEC_SIZES,
    HINT_FAMILY_MEMBER_COUNT,
    HINT_REPLY_SIZE_KB,
    LARGE_REPLY_SIZES_MB,
    build_fixture,
    make_hint_agent,
    make_hint_family_container,
    make_large_reply,
)

pytestmark = pytest.mark.slow

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


async def _wait_for_startup(app: AceApp, pilot: object) -> None:
    """Wait for background startup surfaces before timing follow-up actions."""
    deadline = asyncio.get_running_loop().time() + 20.0
    while not (
        app._mount_state_loads_done
        and app._agents_first_load_done
        and app._axe_first_load_done
    ):
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("ACE benchmark startup did not settle within 20s")
        await pilot.pause()  # type: ignore[attr-defined]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _summarize_spans(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_span: dict[str, list[float]] = {}
    for r in records:
        by_span.setdefault(str(r.get("span", "")), []).append(
            float(r.get("duration_ms", 0.0))
        )
    out: dict[str, dict[str, float]] = {}
    for span, vals in by_span.items():
        if not vals:
            continue
        vs = sorted(vals)
        n = len(vs)
        p95_idx = max(0, int(round(0.95 * (n - 1))))
        out[span] = {
            "n": float(n),
            "p50_ms": float(statistics.median(vs)),
            "p95_ms": vs[p95_idx],
            "max_ms": vs[-1],
        }
    return out


def _summarize_jk(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_action: dict[str, list[float]] = {}
    for r in records:
        action = str(r.get("action", ""))
        if not action:
            continue
        by_action.setdefault(action, []).append(float(r.get("paint_ms", 0.0)))
    out: dict[str, dict[str, float]] = {}
    for action, vals in by_action.items():
        if not vals:
            continue
        vs = sorted(vals)
        n = len(vs)
        p95_idx = max(0, int(round(0.95 * (n - 1))))
        out[action] = {
            "n": float(n),
            "p50_ms": float(statistics.median(vs)),
            "p95_ms": vs[p95_idx],
            "max_ms": vs[-1],
        }
    return out


async def _run_scenario(
    cs_count: int,
    agent_count: int,
    *,
    j_keys: int,
    gp_file: Path,
    large_reply_text: str | None,
) -> dict[str, Any]:
    """Run one fixture-size scenario through the ACE TUI.

    Returns the per-scenario summary dict. Must be awaited inside a fresh
    pytest event loop or the script's asyncio.run wrapper.
    """
    fixture = build_fixture(cs_count, agent_count, gp_file=gp_file)

    started_wall: dict[str, float] = {}
    finished_wall: dict[str, float] = {}

    def _mark(name: str) -> None:
        import time

        finished_wall[name] = time.perf_counter()

    def _mark_start(name: str) -> None:
        import time

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

        # Cold start
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

            # Query change: filter to a subset
            _mark_start("query_change")
            _apply_query('"cs_0"')
            await pilot.pause()
            _mark("query_change")

            # Repeated query edits: exercise the product filter route with
            # one cached ChangeSpec corpus and multiple query programs.
            _mark_start("repeated_query_edits")
            for query in _QUERY_EDIT_SEQUENCE:
                _apply_query(query)
                await pilot.pause()
            _mark("repeated_query_edits")

            # Reset query so subsequent scenarios have full list.
            _apply_query('"cs_"')
            await pilot.pause()

            # 50-key j/k burst
            _mark_start("jk_burst")
            for _ in range(j_keys):
                await pilot.press("j")
                await pilot.pause(0.005)
            for _ in range(j_keys):
                await pilot.press("k")
                await pilot.pause(0.005)
            _mark("jk_burst")

            # Auto-refresh with no changes
            _mark_start("auto_refresh_idle")
            app._refresh_display()  # type: ignore[attr-defined]
            await pilot.pause()
            _mark("auto_refresh_idle")

            # Large-reply select: inject the synthetic agents and select one
            if large_reply_text is not None and fixture.agents:
                _mark_start("large_reply_select")
                app._agents = fixture.agents  # type: ignore[attr-defined]
                # Switch to agents tab so the agent detail path fires.
                app.current_tab = "agents"  # type: ignore[assignment]
                await pilot.pause()
                # Move once to trigger detail render
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


_HINT_RENDER_SPAN = "widget.prompt_panel.update_display_with_hints"


def _summarize_hint_counters(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the size counters carried on the hint-render span.

    Durations alone cannot say whether a phase got faster because it bounded
    the document or because the machine was quieter, so the baseline records
    how much text was annotated and how many hints came out alongside them.
    """
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


VIEW_HINTS_STEPS: tuple[str, ...] = (
    "large_reply_first_press",
    "large_reply_repeat_press",
    "family_container_press",
    "family_container_unfolded_press",
    "hint_mode_auto_refresh",
)


async def _run_view_hints_scenario(
    *,
    gp_file: Path,
    artifacts_root: Path,
    trace_path: Path,
) -> dict[str, Any]:
    """Drive the Agents-tab ``v`` keypath and time each step separately.

    Covers the four steps phase ``measure`` of
    ``plans:202607/agents_view_hints_perf.md`` calls for: a first press on a
    plain agent with a large reply, a repeat press on that same row, a press on
    a family-container row, and an auto-refresh tick while hint mode is active.

    Unlike the other scenarios these fixtures are disk-backed — the hint render
    reads ``raw_xprompt.md`` / ``*_prompt.md`` / ``live_reply.md`` — so the
    numbers include the artifact reads a real press pays.

    Spans are sliced per step off ``trace_path`` rather than pooled across the
    whole run, because the plain-agent and family-container presses are the two
    costs later phases need to compare independently. ``wall_ms`` measures
    dispatch through Pilot settle and therefore carries unrelated repaint work;
    treat the per-step ``spans`` table as the comparison metric.
    """
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

            # Startup is done, so pin the agent list: any further disk load
            # would replace the fixture rows with this machine's real agents
            # and silently measure the wrong document.
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

            # Tear the bar down so the repeat press re-renders rather than
            # short-circuiting through _refocus_existing_hint_bar.
            await _teardown_bar()
            await _timed("large_reply_repeat_press", _press_v)

            async def _auto_refresh() -> None:
                app._refresh_agents_display()  # type: ignore[attr-defined]

            # Auto-refresh tick with hint mode still active.
            await _timed("hint_mode_auto_refresh", _auto_refresh)
            await _teardown_bar()

            await _select(family_agent)
            await _timed("family_container_press", _press_v)
            await _teardown_bar()

            # At the default panel fold the family reply section renders tail
            # previews of each member. The fully-expanded fold is the branch
            # that annotates every member's reply in full, which is where the
            # per-chunk family hint work the plan flags actually runs.
            app.panel_fold_level = FoldLevel.FULLY_EXPANDED  # type: ignore[assignment]
            await pilot.pause()
            await _timed("family_container_unfolded_press", _press_v)
            await _teardown_bar()

    return {
        "reply_kb": HINT_REPLY_SIZE_KB,
        "family_members": HINT_FAMILY_MEMBER_COUNT,
        "steps": steps,
    }


VIEW_HINTS_BASELINE_PATH = (
    Path(__file__).parent / "baselines" / "view_hints_baseline.json"
)
VIEW_HINTS_BASELINE_RUNS = 5


async def run_view_hints_baseline(
    *,
    gp_file: Path,
    trace_path: Path,
    runs: int = VIEW_HINTS_BASELINE_RUNS,
) -> dict[str, Any]:
    """Run the view-hints scenario ``runs`` times and aggregate the samples.

    A single Pilot-driven press is noisy, so the committed baseline stores the
    median across runs per (step, span) plus every raw run, letting a later
    phase re-derive the aggregate or inspect the spread.
    """
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


async def _run_full_baseline(
    output_path: Path,
    *,
    trace_path: Path,
    perf_path: Path,
    gp_file: Path,
) -> dict[str, Any]:
    """Run all fixture-size combinations and dump a baseline JSON."""
    # Pair the matched (cs, agent) sizes — a 100-CL fixture pairs with the
    # 50-agent fixture, etc. Cross-product would balloon runtime without
    # adding much signal at Phase 1.
    paired = list(zip(CHANGESPEC_SIZES, AGENT_SIZES, strict=True))
    large_reply_text = make_large_reply(LARGE_REPLY_SIZES_MB[0])

    scenarios: list[dict[str, Any]] = []
    for cs_count, agent_count in paired:
        # Truncate trace JSONL between scenarios so the per-scenario
        # summary isn't polluted by prior runs.
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


@pytest.fixture
def _trace_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    """Wire all three required env vars to ``tmp_path`` for isolation."""
    trace_path = tmp_path / "tui_trace.jsonl"
    perf_path = tmp_path / "tui_jk.jsonl"
    gp_file = tmp_path / "bench" / "bench.sase"
    gp_file.parent.mkdir(parents=True)
    gp_file.write_text("")
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.setenv("SASE_TUI_PERF_PATH", str(perf_path))
    return trace_path, perf_path, gp_file


async def test_baseline_smoke(_trace_env: tuple[Path, Path, Path]) -> None:
    """Smoke test: run the smallest fixture and confirm trace JSONL fills."""
    trace_path, perf_path, gp_file = _trace_env
    result = await _run_scenario(
        CHANGESPEC_SIZES[0],
        AGENT_SIZES[0],
        j_keys=10,
        gp_file=gp_file,
        large_reply_text=None,
    )
    spans = _read_jsonl(trace_path)
    assert spans, "tui_trace.jsonl was empty — instrumentation may not be wired"
    summary = _summarize_spans(spans)
    assert "changespec.filter" in summary, (
        f"missing changespec.filter span; saw {sorted(summary)}"
    )
    # The two ChangeSpec hot-path spans should always appear at this size.
    assert any(name.startswith("widget.changespec_list.") for name in summary), (
        f"missing changespec_list spans; saw {sorted(summary)}"
    )
    print(json.dumps(result, indent=2), file=sys.stderr)


def test_xprompt_tokenizer_guard_limit_benchmark() -> None:
    """Print tokenizer p50/p95 at the prompt overlay's 80 KB guard limit."""
    composite = (
        "#gh:sase %auto #pr:my_change %m:opus use /sase_plan "
        "then /sase_repo and leave /unknown plain\n---\n"
    )
    prose = "Explain /sase_git_commit details and preserve src/pkg/file.py. " * 70
    chunk = prose + composite
    tail = "\n---"
    text = (chunk * (80_000 // len(chunk) + 1))[: 80_000 - len(tail)] + tail
    known_skills = frozenset({"sase_git_commit", "sase_plan", "sase_repo"})
    samples_ms: list[float] = []

    for _ in range(100):
        started = time.perf_counter()
        xprompt_inspect.tokenize(text, known_skills=known_skills)
        samples_ms.append((time.perf_counter() - started) * 1_000)

    ordered = sorted(samples_ms)
    p95_index = max(0, int(round(0.95 * (len(ordered) - 1))))
    print("\nxprompt tokenizer (80 KB, 100 iterations)")
    print("p50_ms  p95_ms  max_ms")
    print(
        f"{statistics.median(ordered):>6.2f}  "
        f"{ordered[p95_index]:>6.2f}  {ordered[-1]:>6.2f}"
    )


def test_xprompt_tokenizer_code_heavy_benchmark() -> None:
    """Keep literal-zone scanning responsive for a large code-heavy prompt."""
    code_line = (
        "def transform(value): return {'value': value + 1}  # literal #hidden %auto\n"
    )
    code = (code_line * 1_000)[:40_000]
    adjacent_line = (
        "Keep `#hidden`/`%m:opus`/`{{ hidden }}` and prefix`value`suffix literal.\n"
    )
    adjacent = (adjacent_line * 1_000)[:39_000]
    text = f"```python\n{code}```\n{adjacent}Then run #gh:sase %auto\n"
    samples_ms: list[float] = []

    for _ in range(100):
        started = time.perf_counter()
        xprompt_inspect.tokenize(text)
        samples_ms.append((time.perf_counter() - started) * 1_000)

    ordered = sorted(samples_ms)
    p95_index = max(0, int(round(0.95 * (len(ordered) - 1))))
    p95_ms = ordered[p95_index]
    print("\nxprompt tokenizer (80 KB code-heavy prompt, 100 iterations)")
    print("p50_ms  p95_ms  max_ms")
    print(f"{statistics.median(ordered):>6.2f}  {p95_ms:>6.2f}  {ordered[-1]:>6.2f}")
    assert p95_ms < 16.0


async def test_view_hints_scenario(_trace_env: tuple[Path, Path, Path]) -> None:
    """Run the ``v`` keypath scenarios and print the span table.

    Also acts as the wiring check for the phase ``measure`` spans: if any of
    them stops firing, this fails rather than silently reporting an empty
    baseline.
    """
    trace_path, _perf_path, gp_file = _trace_env
    result = await _run_view_hints_scenario(
        gp_file=gp_file,
        artifacts_root=gp_file.parent / "view_hints_artifacts",
        trace_path=trace_path,
    )
    steps = result["steps"]
    for step in VIEW_HINTS_STEPS:
        assert step in steps, f"missing step {step}; saw {sorted(steps)}"

    press_spans = steps["large_reply_first_press"]["spans"]
    for span in (
        "agents.view_files",
        "agents.view_agent_files",
        "agents.view_hint_bar_mount",
        "widget.prompt_panel.update_display_with_hints",
    ):
        assert span in press_spans, f"missing {span} span; saw {sorted(press_spans)}"
    refresh_spans = steps["hint_mode_auto_refresh"]["spans"]
    assert "agents.view_hints_refresh" in refresh_spans, (
        f"missing agents.view_hints_refresh span; saw {sorted(refresh_spans)}"
    )

    # The size counters are what later phases attribute a duration change to,
    # so a silently-dropped counter must fail here rather than at compare time.
    plain_counters = steps["large_reply_first_press"]["hint_counters"]
    assert plain_counters["annotated_chars"] > HINT_REPLY_SIZE_KB * 1024
    assert plain_counters["hints"] > 0
    assert plain_counters["family_container"] == [False]
    family_counters = steps["family_container_unfolded_press"]["hint_counters"]
    assert family_counters["family_container"] == [True]
    assert family_counters["annotated_chars"] > plain_counters["annotated_chars"], (
        "an unfolded family container should annotate more than one member"
    )
    print(json.dumps(result, indent=2), file=sys.stderr)


async def test_full_baseline(
    _trace_env: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """Run every fixture size and dump a baseline JSON (written to tmp)."""
    trace_path, perf_path, gp_file = _trace_env
    output = tmp_path / "tui_perf_baseline.json"
    baseline = await _run_full_baseline(
        output,
        trace_path=trace_path,
        perf_path=perf_path,
        gp_file=gp_file,
    )
    assert baseline["scenarios"], "baseline produced no scenarios"
    assert output.exists()
    print(f"\nbaseline written to {output}", file=sys.stderr)
    print(json.dumps(baseline, indent=2), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Standalone entrypoint: run all scenarios and write a baseline JSON.

    Equivalent to ``pytest -s -m slow tests/perf/bench_tui_trace.py`` but
    callable as a plain script for use outside the pytest plumbing.
    """
    parser = argparse.ArgumentParser(description="TUI perf baseline harness.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=(
            "Where to write the baseline numbers JSON. Defaults to "
            "~/.sase/perf/tui_perf_baseline.json, or the committed "
            "view-hints baseline under --view-hints-baseline."
        ),
    )
    parser.add_argument(
        "-t",
        "--trace-path",
        type=Path,
        default=Path.home() / ".sase" / "perf" / "tui_trace.jsonl",
        help="JSONL path for span samples.",
    )
    parser.add_argument(
        "-p",
        "--perf-path",
        type=Path,
        default=Path.home() / ".sase" / "perf" / "tui_jk.jsonl",
        help="JSONL path for j/k key-to-paint samples.",
    )
    parser.add_argument(
        "--view-hints-baseline",
        action="store_true",
        help=(
            "Run only the Agents-tab view-hints scenarios and write the "
            f"committed baseline to --output (default {VIEW_HINTS_BASELINE_PATH})."
        ),
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=VIEW_HINTS_BASELINE_RUNS,
        help="Repeat count for --view-hints-baseline.",
    )
    args = parser.parse_args(argv)

    os.environ["SASE_TUI_TRACE"] = "1"
    os.environ["SASE_TUI_TRACE_PATH"] = str(args.trace_path)
    os.environ["SASE_TUI_PERF"] = "1"
    os.environ["SASE_TUI_PERF_PATH"] = str(args.perf_path)

    import tempfile

    if args.view_hints_baseline:
        output = args.output or VIEW_HINTS_BASELINE_PATH
        with tempfile.TemporaryDirectory() as tmpdir:
            gp_file = Path(tmpdir) / "bench.sase"
            gp_file.write_text("")
            baseline = asyncio.run(
                run_view_hints_baseline(
                    gp_file=gp_file,
                    trace_path=args.trace_path,
                    runs=args.runs,
                )
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(baseline, indent=2) + "\n")
        print(f"view-hints baseline written to {output}")
        return 0

    full_output = args.output or (
        Path.home() / ".sase" / "perf" / "tui_perf_baseline.json"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        gp_file = Path(tmpdir) / "bench.sase"
        gp_file.write_text("")
        baseline = asyncio.run(
            _run_full_baseline(
                full_output,
                trace_path=args.trace_path,
                perf_path=args.perf_path,
                gp_file=gp_file,
            )
        )

    print(json.dumps(baseline, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
