"""Generated-content and budget guards for ``tests/contract_manifest.txt``.

Deliberately unmarked: the engine adds the `contract` set to every scoped
selection, so measuring or regenerating it from inside that same set would tax
every check with the cost of the whole set again (and the budget test would
recurse into itself). These guards run under the exhaustive lane instead
(`just test`, `just check-full`, CI).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests" / "contract_manifest.txt"

# Measured 2026-08-05 on the dev host: the committed set ran 24-26s serially
# (this test's own subprocess wrapper included) across repeated runs, some
# under real contention from other concurrent workspaces. If this creeps
# toward the ceiling, trim the set per the curation procedure in
# plans/202608/test_suite_tier1.md rather than raising the budget.
_BUDGET_SECONDS = 30.0


def _load_refresh_tool() -> ModuleType:
    script = ROOT / "tools" / "refresh_contract_manifest"
    loader = SourceFileLoader("refresh_contract_manifest_tool", str(script))
    spec = importlib.util.spec_from_file_location(
        "refresh_contract_manifest_tool",
        script,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_manifest() -> list[str]:
    return [
        line
        for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_contract_manifest_matches_marker_selection() -> None:
    tool = _load_refresh_tool()

    current = tool.collect_contract_files()
    committed = _read_manifest()

    assert current == committed, (
        "tests/contract_manifest.txt is stale; run "
        "`just refresh-contract-manifest`.\n"
        f"marker currently selects: {current}\n"
        f"committed manifest:       {committed}"
    )


def test_contract_set_serial_runtime_stays_within_budget() -> None:
    files = _read_manifest()

    tool = _load_refresh_tool()

    start = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *files],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=tool._nested_pytest_env(),
        check=False,
    )
    elapsed = time.monotonic() - start

    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    assert elapsed <= _BUDGET_SECONDS, (
        f"contract set took {elapsed:.1f}s serially, over the "
        f"{_BUDGET_SECONDS:.0f}s budget:\n{proc.stdout[-4000:]}"
    )
