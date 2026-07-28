"""Synthetic-data benchmark entry point for the ace TUI.

Drives the ace TUI through ``Pilot`` with ``SASE_TUI_TRACE=1`` (and the
existing ``SASE_TUI_PERF=1`` for j/k key-to-paint samples) enabled. The
implementation lives in ``tests.perf.tui_trace``; this module keeps the
existing pytest and standalone-script interfaces.

Run with::

    pytest -s -m slow tests/perf/bench_tui_trace.py
    python -m tests.perf.bench_tui_trace --output baseline.json

The Agents-tab ``v`` keypath can be captured separately with::

    python -m tests.perf.bench_tui_trace --view-hints-baseline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

import pytest

from sase.xprompt import xprompt_inspect

from .fixtures import (
    AGENT_SIZES,
    CHANGESPEC_SIZES,
    HINT_FAMILY_MEMBER_COUNT,
    HINT_REPLY_SIZE_KB,
)
from .tui_trace.common import (
    _read_jsonl,
    _summarize_jk,
    _summarize_spans,
    _wait_for_startup,
)
from .tui_trace.scenarios import (
    _DEFAULT_J_KEYS,
    _QUERY_EDIT_SEQUENCE,
    _run_full_baseline,
    _run_scenario,
)
from .tui_trace.view_hints import (
    VIEW_HINTS_BASELINE_PATH,
    VIEW_HINTS_BASELINE_RUNS,
    VIEW_HINTS_STEPS,
    _HINT_RENDER_SPAN,
    _run_view_hints_scenario,
    _summarize_hint_counters,
    run_view_hints_baseline,
)

pytestmark = pytest.mark.slow


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
    trace_path, _perf_path, gp_file = _trace_env
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
    """Run the ``v`` keypath scenarios and verify the required spans."""
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

    plain_counters = steps["large_reply_first_press"]["hint_counters"]
    assert plain_counters["annotated_chars"] > HINT_REPLY_SIZE_KB * 1024
    assert plain_counters["hints"] > 0
    assert plain_counters["family_container"] == [False]
    default_family_counters = steps["family_container_press"]["hint_counters"]
    full_family_counters = steps["family_container_unfolded_press"]["hint_counters"]
    for family_counters in (default_family_counters, full_family_counters):
        assert family_counters["family_container"] == [True]
        assert family_counters["annotated_chars"] > plain_counters["annotated_chars"]
        assert family_counters["annotated_chars"] <= 200_000
        assert family_counters["hints"] > 0
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
    """Run benchmark scenarios and write a baseline JSON."""
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
