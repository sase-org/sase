"""Steady-state harness for j/k key-to-paint latency.

Drives the ace TUI through ``Pilot`` with ``SASE_TUI_PERF=1`` enabled,
captures key-to-paint samples to a JSONL file, and prints a p50/p95/max
table per scenario. Marked ``slow`` so it does not run as part of the
default ``just test`` suite -- run explicitly with::

    pytest -s -m slow tests/ace/tui/bench_tui_jk.py

The collected benchmark cases live in split ``bench_tui_jk_*`` modules. This
module re-exports them so the historical single-file pytest command still
works, and keeps the standalone aggregate-log ``main()`` entrypoint.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.ace.tui._bench_tui_jk_helpers import (
    _perf_jsonl as _perf_jsonl,
    _print_table,
    _read_samples,
    _summarize,
)
from tests.ace.tui.bench_tui_jk_agents import (
    test_bench_agents_jk_and_panel_navigation as test_bench_agents_jk_and_panel_navigation,
    test_bench_clan_jk_at_each_panel_fold_level as test_bench_clan_jk_at_each_panel_fold_level,
    test_bench_selected_tribe_jk_at_each_fold_level as test_bench_selected_tribe_jk_at_each_fold_level,
)
from tests.ace.tui.bench_tui_jk_keypath import (
    test_bench_keystroke_reaches_no_provider_discovery_or_subprocess as test_bench_keystroke_reaches_no_provider_discovery_or_subprocess,
)
from tests.ace.tui.bench_tui_jk_link_rail import (
    test_bench_agents_jk_with_and_without_the_link_rail as test_bench_agents_jk_with_and_without_the_link_rail,
)
from tests.ace.tui.bench_tui_jk_panes import (
    test_bench_axe_jk as test_bench_axe_jk,
    test_bench_patches_jk as test_bench_patches_jk,
)

pytestmark = pytest.mark.slow


def main() -> int:
    """Print a single combined table from an existing benchmark JSONL log."""
    log = Path(
        os.environ.get(
            "SASE_TUI_PERF_PATH", str(Path.home() / ".sase" / "perf" / "tui_jk.jsonl")
        )
    )
    if log.exists():
        summary = _summarize(_read_samples(log))
        _print_table(f"Aggregate samples in {log}:", summary)
        return 0
    print(f"no perf log at {log}; run pytest with -m slow first", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover -- script entry
    raise SystemExit(main())
