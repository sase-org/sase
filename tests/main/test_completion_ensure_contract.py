"""Import-set and CPU contracts for the completion-ensure warm path.

Warm cache hits must not construct the argparse parser or import TUI modules.
The CPU check uses child-process user+system time, not host wall-clock.
"""

from __future__ import annotations

import os
import resource
import subprocess
import sys
import textwrap
from collections.abc import Sequence
from pathlib import Path

import pytest

from sase.completion.install_models import ExpectedCompletion
from sase.completion.runtime_cache import ensure_cached_grammar

_PROBE_SOURCE = """
import sys
from sase.main.entry import main

sys.argv = ["sase", "completion", "ensure", "bash"]
try:
    main()
except SystemExit as exc:
    assert exc.code in (0, None), exc.code
forbidden = [
    name
    for name in sys.modules
    if name == "sase.main.parser"
    or name == "sase.main.parser_registry"
    or name == "sase.completion.build"
    or name.startswith("sase.ace")
    or name == "textual"
    or name.startswith("textual.")
    or name == "rich"
    or name.startswith("rich.")
]
assert not forbidden, forbidden
"""

# Generous child-CPU bound, comparable to the 250 ms candidates budget but
# wide enough for the source-stat fingerprint walk on a shared host.
_CPU_BUDGET_MS = 1000.0


def _expected(shells: Sequence[str]) -> dict[str, ExpectedCompletion]:
    return {
        shell: ExpectedCompletion(f"# generated\n# {shell}\n", f"digest-{shell}")
        for shell in shells
    }


def _warm_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["SASE_HOME"] = str(home)
    env.pop("SASE_SDD_BEADS_DIR", None)
    env.pop("SASE_SDD_PLANS_DIR", None)
    return env


def _run_warm_probe(home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_PROBE_SOURCE)],
        cwd=home.parent,
        env=_warm_env(home),
        capture_output=True,
        text=True,
        check=False,
    )


def test_warm_ensure_avoids_parser_and_tui_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    ensure_cached_grammar("bash", expected_fn=_expected)

    result = _run_warm_probe(home)

    assert result.returncode == 0, result.stderr + result.stdout


def test_warm_ensure_child_cpu_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    ensure_cached_grammar("bash", expected_fn=_expected)

    timings_seconds: list[float] = []
    for _ in range(2):
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        result = _run_warm_probe(home)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        assert result.returncode == 0, result.stderr + result.stdout
        timings_seconds.append(
            (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)
        )

    best_ms = min(timings_seconds) * 1000
    assert best_ms < _CPU_BUDGET_MS, (timings_seconds, _CPU_BUDGET_MS)
