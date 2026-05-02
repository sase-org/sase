"""Phase 1 synthetic-data benchmark harness for the ace TUI.

Bead sase-w.1 / sdd/tales/202604/tui_perf_overhaul_1.md.

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

Out of scope: any actual hot-path optimization (Phase 1 only measures).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.app import AceApp

from .fixtures import (
    AGENT_SIZES,
    CHANGESPEC_SIZES,
    LARGE_REPLY_SIZES_MB,
    build_fixture,
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
        "sase.ace.changespec.find_all_changespecs", return_value=fixture.changespecs
    ):

        def _apply_query(query: str) -> None:
            from sase.ace.query import parse_query

            app.query_string = query
            app.parsed_query = parse_query(query)  # type: ignore[assignment]
            app._load_changespecs()  # type: ignore[attr-defined]

        # Cold start
        _mark_start("cold_start")
        app = AceApp(query="!!!", auto_start_axe=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            _mark("cold_start")

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
            _apply_query("!!!")
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

    baseline = {
        "version": 1,
        "j_keys_per_burst": _DEFAULT_J_KEYS,
        "query_edit_sequence": list(_QUERY_EDIT_SEQUENCE),
        "large_reply_mb": LARGE_REPLY_SIZES_MB[0],
        "scenarios": scenarios,
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
    gp_file = tmp_path / "bench" / "bench.gp"
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
        default=Path.home() / ".sase" / "perf" / "tui_perf_baseline.json",
        help="Where to write the baseline numbers JSON.",
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
    args = parser.parse_args(argv)

    os.environ["SASE_TUI_TRACE"] = "1"
    os.environ["SASE_TUI_TRACE_PATH"] = str(args.trace_path)
    os.environ["SASE_TUI_PERF"] = "1"
    os.environ["SASE_TUI_PERF_PATH"] = str(args.perf_path)

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        gp_file = Path(tmpdir) / "bench.gp"
        gp_file.write_text("")
        baseline = asyncio.run(
            _run_full_baseline(
                args.output,
                trace_path=args.trace_path,
                perf_path=args.perf_path,
                gp_file=gp_file,
            )
        )

    print(json.dumps(baseline, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
