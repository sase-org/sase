"""Import-set and CPU contracts for the completion candidates fast path.

The durable contract is the import set: after the fast path runs, the
process must never have paid for ``sase.main.parser``, ``sase.ace.*``,
``textual``, or ``rich``. The CPU check accounts for child-process user+system
time rather than host scheduling time; the import-set assertion below is what
actually prevents a future change from
routing this path through something like ``sase agent list`` (6.4-6.9s) or
another accidental heavy import.
"""

from __future__ import annotations

import os
import resource
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_SHIPPED_KINDS = (
    "project",
    "bead",
    "repo",
    "workspace",
    "flag",
    "glossary",
    "plugin",
    "plan",
    "patch",
    "memory",
    "xprompt",
    "skill",
    "proc",
    "monitor",
    "artifact",
    "artifact_ref",
    "artifact_relation",
    "directive",
    "tag",
    "agent",
    "model",
    "snippet",
)

_PROBE_SOURCE = """
import sys
kinds = {kinds!r}
from sase.main.entry import main
for kind in kinds:
    sys.argv = ["sase", "completion", "candidates", kind]
    try:
        main()
    except SystemExit as exc:
        assert exc.code in (0, None), (kind, exc.code)
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


def _run_probe(
    cwd: Path, kinds: tuple[str, ...] = _SHIPPED_KINDS
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SASE_HOME"] = str(cwd / "sase-home")
    env.pop("SASE_SDD_BEADS_DIR", None)
    env.pop("SASE_SDD_PLANS_DIR", None)
    source = textwrap.dedent(_PROBE_SOURCE.format(kinds=kinds))
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_candidates_fast_path_avoids_heavy_imports(tmp_path: Path) -> None:
    result = _run_probe(tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout


def _run_probe_with_cpu_seconds(
    cwd: Path, kinds: tuple[str, ...]
) -> tuple[subprocess.CompletedProcess[str], float]:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = _run_probe(cwd, kinds=kinds)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    before_cpu = before.ru_utime + before.ru_stime
    after_cpu = after.ru_utime + after.ru_stime
    return result, after_cpu - before_cpu


# The budget is calibrated for child-process CPU after the package facades were
# made lazy. It intentionally ignores scheduler wait and parallel host load.
_CPU_BUDGET_MS = 250.0


@pytest.mark.parametrize("kind", _SHIPPED_KINDS)
def test_candidates_fast_path_child_cpu_budget(tmp_path: Path, kind: str) -> None:
    timings_seconds: list[float] = []
    for _ in range(2):
        result, cpu_seconds = _run_probe_with_cpu_seconds(tmp_path, kinds=(kind,))
        timings_seconds.append(cpu_seconds)
        assert result.returncode == 0, result.stderr + result.stdout

    best_ms = min(timings_seconds) * 1000
    assert best_ms < _CPU_BUDGET_MS, (kind, timings_seconds, _CPU_BUDGET_MS)
