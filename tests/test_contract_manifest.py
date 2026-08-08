"""Generated-content and deterministic budget guards for the contract manifest.

Deliberately unmarked: the engine adds the `contract` set to every scoped
selection, so regenerating or budgeting it from inside that same set would tax
every check with the cost of the whole set again. These guards run under the
exhaustive lane instead (`just test`, `just check-full`, CI).
"""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests" / "contract_manifest.txt"

# Membership, re-decided 2026-08-06 (the question `sase-fp.2` deferred until
# the scoped-run integration test landed, which it has). Both candidates stay
# out, and not merely for margin: the retired serial-cost measurement priced
# `tests/test_suite_gate_integration.py` at +4.8s and `tests/
# test_markdown_template_packaging.py` at +2.0s, but every change that could
# break either already forces the full suite on its own -- `tests/
# _suite_gate.py` and `tools/run_pytest` are root-conftest/selection-tooling
# paths, and `pyproject.toml` is a packaging-config path. Adding them would
# spend significant curation cost on coverage the broadening rules already give.
#
# This cap intentionally equals the current manifest length. The retired
# runtime oracle measured the current 35-entry set at 27.4 serial seconds on
# 2026-08-08 before it was replaced; one additional contract file should force
# an explicit value-per-second curation decision instead of consuming hidden
# headroom. If the set changes, re-curate it per plans/202608/test_suite_tier1.md
# and update this cap together with the measured-cost comment.
_MANIFEST_ENTRY_BUDGET = 35
_MEASURED_SERIAL_COST = "27.4 serial seconds"


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


def _budget_failure_message(files: list[str]) -> str:
    count = len(files)
    if count < _MANIFEST_ENTRY_BUDGET:
        return (
            "tests/contract_manifest.txt contains "
            f"{count} entries, below the {_MANIFEST_ENTRY_BUDGET}-entry "
            "contract-set budget.\n"
            f"The retired timed guard measured this set at {_MEASURED_SERIAL_COST}; "
            "lower this cap and update the measured-cost comment so removed entries "
            "do not become hidden headroom.\n"
            "Use the curation procedure in plans/202608/test_suite_tier1.md."
        )
    overflow = files[_MANIFEST_ENTRY_BUDGET:]
    return (
        "tests/contract_manifest.txt contains "
        f"{count} entries, over the {_MANIFEST_ENTRY_BUDGET}-entry "
        "contract-set budget.\n"
        f"The current 35-entry set was measured at {_MEASURED_SERIAL_COST} before "
        "the load-sensitive runtime oracle was retired.\n"
        "Re-curate by value per second, then update this cap and measured-cost "
        "comment per plans/202608/test_suite_tier1.md.\n"
        f"entries over budget: {overflow}"
    )


def test_contract_set_manifest_entry_budget_has_no_hidden_headroom() -> None:
    files = _read_manifest()

    assert len(files) == _MANIFEST_ENTRY_BUDGET, _budget_failure_message(files)


def test_contract_set_manifest_entry_budget_diagnostic_names_curation() -> None:
    files = [
        f"tests/generated_contract_{index}.py"
        for index in range(_MANIFEST_ENTRY_BUDGET + 1)
    ]

    message = _budget_failure_message(files)

    assert _MEASURED_SERIAL_COST in message
    assert "plans/202608/test_suite_tier1.md" in message
    assert "tests/generated_contract_35.py" in message
