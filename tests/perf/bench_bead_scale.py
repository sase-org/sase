"""Scale-aware bead benchmark over synthetic or copied corpora.

Measures binding reads, CLI commands, mutations, and the TUI Beads board
loader on history-shaped stores, and emits JSON with per-op stats, the
corpus shape, and the core revision. Pass ``--check-gate`` to enforce the
A1 history-independence criteria (sase-1h8.14 ``perf-gate``) instead of
only recording.

Run directly:

    python tests/perf/bench_bead_scale.py --scale 1 --scale 2 \\
        --output /tmp/bead-scale.json

Use ``--store <dir>`` (repeatable) to measure an existing store, for
example a ``tools/bead_scale_corpus`` copy of the live store, instead of
generating a synthetic corpus.

This module is the public facade for the bead-scale benchmark; the
implementation lives in :mod:`tests.perf._bead_scale_bench`,
:mod:`tests.perf._bead_scale_gate`, and :mod:`tests.perf._bead_scale_main`.
It re-exports every public name of the original module so existing imports
keep working.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.perf._bead_scale_bench import benchmark_store  # noqa: E402
from tests.perf._bead_scale_gate import (  # noqa: E402
    GATE_ABSOLUTE_OPS,
    GATE_RATIO_OPS,
    evaluate_gate,
)
from tests.perf._bead_scale_main import main  # noqa: E402

__all__ = [
    "GATE_ABSOLUTE_OPS",
    "GATE_RATIO_OPS",
    "REPO_ROOT",
    "benchmark_store",
    "evaluate_gate",
    "main",
    "pytestmark",
]


if __name__ == "__main__":
    raise SystemExit(main())
