"""Generated-content and budget guards for ``tests/contract_manifest.txt``.

Deliberately unmarked: the engine adds the `contract` set to every scoped
selection, so measuring or regenerating it from inside that same set would tax
every check with the cost of the whole set again (and the budget test would
recurse into itself). These guards run under the exhaustive lane instead
(`just test`, `just check-full`, CI).
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests._test_contract_budget import (
    HAVE_RESOURCE,
    Measurement,
    describe_measurement,
    run_calibration_probe,
    run_measured,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests" / "contract_manifest.txt"

# The ceiling is unchanged from the wall-clock version that preceded it: the
# contract set is added to every scoped selection, so it is a tax every agent
# pays on every `just check`, and 30s is the most that tax may be. What changed
# is *what* is measured against it -- normalized child CPU rather than wall
# clock, so the guard bounds the set's size instead of the host's load. See
# tests/_test_contract_budget.py for the normalization and its calibration.
#
# Measured 2026-08-06 on the 64-core dev host at d66101e8f (34 files, 289
# tests): 22.6-23.2s normalized, i.e. ~7s of headroom, holding to within 7%
# across a load range where the raw wall clock moved from 24s to 42s. If this
# creeps toward the ceiling, trim the set per the curation procedure in
# plans/202608/test_suite_tier1.md rather than raising the budget.
#
# Membership, re-decided 2026-08-06 (the question `sase-fp.2` deferred until
# the scoped-run integration test landed, which it has). Both candidates stay
# out, and not merely for margin: `tests/test_suite_gate_integration.py` costs
# +4.8s normalized (17% of the whole budget) and `tests/
# test_markdown_template_packaging.py` +2.0s, but every change that could
# break either already forces the full suite on its own -- `tests/
# _suite_gate.py` and `tools/run_pytest` are root-conftest/selection-tooling
# paths, and `pyproject.toml` is a packaging-config path. Adding them would
# spend a quarter of the budget on coverage the broadening rules already give.
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


@pytest.mark.skipif(
    not HAVE_RESOURCE,
    reason="child-CPU normalization needs the Unix-only `resource` module",
)
def test_contract_set_serial_runtime_stays_within_budget() -> None:
    files = _read_manifest()

    tool = _load_refresh_tool()
    env = tool._nested_pytest_env()

    # Bracket the measured run: one probe before and one after, so a load
    # change arriving partway through a ~25s run is still seen.
    before = run_calibration_probe(sys.executable, cwd=ROOT, env=env)
    proc, wall, cpu = run_measured(
        [sys.executable, "-m", "pytest", "-q", *files],
        cwd=ROOT,
        env=env,
    )
    after = run_calibration_probe(sys.executable, cwd=ROOT, env=env)

    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]

    measurement = Measurement(wall=wall, cpu=cpu, probe_cpu=(before, after))
    assert measurement.normalized <= _BUDGET_SECONDS, (
        f"{describe_measurement(measurement, _BUDGET_SECONDS)}\n{proc.stdout[-4000:]}"
    )
