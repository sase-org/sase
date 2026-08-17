"""Import-set and latency contracts for the completion candidates fast path.

The durable contract is the import set: after the fast path runs, the
process must never have paid for ``sase.main.parser``, ``sase.ace.*``,
``textual``, or ``rich``. The wall-clock check is soft -- timing tests are
inherently flaky -- so it uses a generous budget and CI multiplier; the
import-set assertion below is what actually prevents a future change from
routing this path through something like ``sase agent list`` (6.4-6.9s) or
another accidental heavy import.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

_PROBE_SOURCE = """
import sys
sys.argv = ["sase", "completion", "candidates", "project"]
from sase.main.entry import main
try:
    main()
except SystemExit as exc:
    assert exc.code in (0, None), exc.code
forbidden = [
    name
    for name in sys.modules
    if name == "sase.main.parser"
    or name.startswith("sase.ace")
    or name == "textual"
    or name.startswith("textual.")
    or name == "rich"
    or name.startswith("rich.")
]
assert not forbidden, forbidden
"""


def _run_probe(cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SASE_HOME"] = str(cwd / "sase-home")
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_PROBE_SOURCE)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_candidates_fast_path_avoids_heavy_imports(tmp_path: Path) -> None:
    result = _run_probe(tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout


# The epic plan's aspirational budget is a ~20ms interpreter floor plus a
# ~1.6ms Rust-binding call. In practice `sase.core`'s package `__init__`
# eagerly imports several unrelated facades (glossary, clipboard, shell) on
# any `sase.core.*` import -- a pre-existing cost the `bead` fast path
# already pays too -- which alone measures close to 20ms. The budget below is
# calibrated off measured reality with headroom, not the plan's number; see
# the PROPOSED FOLLOW-UP note on this bead.
_LATENCY_BUDGET_MS = 150.0
_CI_MULTIPLIER = 3.0 if os.environ.get("CI") else 1.0


def test_candidates_fast_path_wall_clock_budget(tmp_path: Path) -> None:
    timings_seconds: list[float] = []
    for _ in range(3):
        start = time.perf_counter()
        result = _run_probe(tmp_path)
        timings_seconds.append(time.perf_counter() - start)
        assert result.returncode == 0, result.stderr + result.stdout

    best_ms = min(timings_seconds) * 1000
    budget_ms = _LATENCY_BUDGET_MS * _CI_MULTIPLIER
    assert best_ms < budget_ms, (timings_seconds, budget_ms)
