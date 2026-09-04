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
# runtime oracle measured the prior 35-entry set at 27.4 serial seconds on
# 2026-08-08 before it was replaced; the Patch/stitch terminology audit was
# explicitly added as the 36th always-on contract because it guards cross-repo
# compatibility boundaries. If the set changes, re-curate it per
# plans/202608/test_suite_tier1.md and update this cap together with the
# measured-cost comment.
#
# Re-curated to 40 on 2026-08-10 for four `tools/` script guards:
# `test_ratchet_core_window_tool.py`, `test_probe_core_floor_tool.py`,
# `test_sase_core_rs_glossary_line_break_smoke_tool.py`, and the
# `tools/sase_bead` wrapper guard in `test_sase_bead_tool.py`. They earn their
# place on value per second rather than on kind: a `tools/` script is not a
# node in the import graph, so a change that touches only one contributes no
# seeds, `RULE_CONTRACT_SET_ONLY` fires, and the contract set is the *only*
# thing that runs -- exactly the invariant no import edge can express. The
# wrapper guard covers the checked-in `sase` wrapper smoke contract and measured
# at <1 s inside the refreshed set. The whole 40-entry set measured 24.7 s on
# 2026-08-10 under
# `pytest -m contract $(cat tests/contract_manifest.txt) -p no:randomly
# --durations=0`, which is the same `--durations` aggregate the retired oracle
# read. The set is still inside the 30 s serial budget the plan sets.
#
# Re-curated to 41 on 2026-08-11 (sase-jo.2) for
# `test_commit_type_tag_contract.py`, the structural guard for the tracked-
# commit `SASE_TYPE=` provenance invariant: it walks every `src/sase` module
# for `git commit` argv construction, exactly the "no import edge can express
# it" case the curation procedure admits on value per second. Its first
# version cost 8.6 s (a full `ast.parse` of all 2,978 `src/sase` modules); a
# substring pre-filter for the literal `"commit"` (present in only 87 of them)
# cut that to 0.46 s. The whole 41-entry set measured 24.0 s under the same
# `pytest -m contract $(cat tests/contract_manifest.txt) -p no:randomly
# --durations=0` command, still inside the 30 s serial budget the plan sets.
#
# Re-curated to 43 on 2026-08-16 when `test_validate_sase_core_rs_tool.py` was
# split by test domain. The two added paths redistribute the same 25 validator
# tests rather than expanding contract membership. The whole 43-entry set
# measured 26.1 s under the command above, still inside the 30 s serial budget.
#
# Re-curated to 44 on 2026-08-18 (sase-p3.15.1) for
# `test_setup_required_plugins_tool.py`, the guard for `tools/setup_required_plugins`.
# Like the other `tools/` script guards already in this set, the script is not a node
# in the import graph, so a change that touches only it contributes no seeds and the
# contract set is the only thing that would catch a regression. The whole 44-entry set
# measured 27.8 s under the command above, still inside the 30 s serial budget.
#
# Re-curated to 49 on 2026-08-18 when `test_config_schema.py` was split by schema
# domain: ACE settings, scoped keymaps, runtime limits, extension points, and bead
# settings. The five added paths redistribute the same 91 schema tests rather than
# expanding contract membership, and each one stays in the set for the reason the
# original file was admitted -- it validates `src/sase/config/schema.json` and
# `src/sase/default_config.yml`, data files no import edge reaches. The whole
# 49-entry set measured 29.8 s under the command above (median of three runs on a
# host that measured the same set at 29.0 s before the split, so the split itself
# costs well under a second of extra per-module collection). That is inside the
# 30 s serial budget the plan sets, but it is the least headroom this set has ever
# had: the next candidate should displace an entry rather than raise this cap.
#
# Re-curated to 52 on 2026-08-19 when `test_suite_gate.py` was split by focus area:
# configure/exemptions stayed in `test_suite_gate.py`, and the token budget, lease
# lifecycle, and reclaim/watchdog areas moved to `test_suite_gate_budget.py`,
# `test_suite_gate_lease.py`, and `test_suite_gate_reclaim.py`. The three added paths
# redistribute the same 57 gate tests rather than expanding contract membership, and
# each stays in the set for the reason the original file was admitted -- `tests/
# _suite_gate.py` and `tools/run_pytest` are root-conftest/selection-tooling paths no
# import edge reaches. The whole 52-entry set measured 29.6 s under the command above
# (median of three runs on this host). That is inside the 30 s serial budget the plan
# sets; the next candidate should still displace an entry rather than raise this cap.
#
# Re-curated to 53 on 2026-08-22 by keeping `test_core_finalizer_facade.py`,
# the compact cross-boundary finalizer protocol guard, and displacing
# `test_xprompt_workflow_schema.py`: changes to the workflow JSON schema or
# checked-in workflow YAML already fire the `src-data-asset` full-suite rule,
# and the test remains in the exhaustive lane. The timezone-display audit keeps
# its repo-wide coverage but prefilters files that cannot contain one of the
# clock attribute names before AST parsing. The whole 53-entry set measured
# 27.0 s under the command above on this host.
#
# Re-curated to 54 on 2026-08-22 (sase-s1.6) when
# `test_ratchet_core_window_source_normalization.py` split the canonical-PyPI
# trailing-slash equivalence tests out of `test_ratchet_core_window_tool.py`.
# The added path redistributes the same tools/ ratchet guard already in the
# set: `tools/ratchet_core_window` is not a node in the import graph, so a
# source-spelling-only lock rewrite is otherwise invisible to scoped
# selection. The whole 54-entry set measured 26.9 s under the command above
# on this host, still inside the 30 s serial budget.
#
# Re-curated to 57 on 2026-08-24 when `test_ratchet_core_window_tool.py` split
# into `test_ratchet_core_window_tool_core.py` (ceiling policy, target-version
# selection, PyPI fetch retries), `test_ratchet_core_window_tool_modes.py`
# (report/check/apply flows), `test_ratchet_core_window_tool_reconciliation.py`
# (transitive uv.lock reconciliation), and
# `test_ratchet_core_window_tool_guardrails.py` (unexpected-diff guardrails) to
# keep every file under 500 lines, the same one-file-in/four-files-out shape as
# the `test_suite_gate.py` split. Each successor keeps the marker for the
# reason the original file earned it: `tools/ratchet_core_window` is not a
# node in the import graph, so scoped selection cannot see a regression in any
# of the four without it. The whole 57-entry set measured 30.7 s under the
# command above (median of three runs on this host) -- the first time this set
# has measured over the plan's nominal 30 s serial budget. Per-file `tool`
# fixture setup stayed under 0.01 s each, so the increase is collection/import
# overhead from four modules reloading the same script rather than added test
# weight. The next candidate should displace an entry rather than add one.
#
# Re-curated to 58 on 2026-08-27 for `test_config_schema_gate_shell.py`, which
# keeps the gate-shell schema/default-config contract beside the other split
# config-schema domains. Like those files, it validates data files no import
# edge reaches rather than expanding behavioral test weight. The whole 58-entry
# set measured 31.1 s under the command above on this host; the next candidate
# should displace an entry rather than add one.
#
# Re-curated to 60 on 2026-08-27 (sase-um.6) for two paths. First,
# `test_github_actions_ci_master_gate.py` redistributes `test_github_actions_ci.py`'s
# master-gate.yml/full.yml/core-pin-ratchet.yml sections, split out once the file
# crossed the 1000-line `toobig` ceiling; both halves keep the marker for the reason
# the original file earned it -- checked-in workflow YAML is a data asset no import
# edge reaches. Second, `test_ratchet_core_revision_tool.py` guards the new
# `tools/ratchet_core_revision` script (the sase-core source-revision-pin ratchet),
# admitted on the same value-per-second basis as the other `tools/ratchet_core_window`
# and `tools/probe_core_floor` guards already in this set: a `tools/` script
# contributes no import-graph seeds, so `RULE_CONTRACT_SET_ONLY` fires and this set is
# the only thing that would catch a regression in it. The whole 60-entry set measured
# 31.85 s under the command above on this host; the next candidate should displace an
# entry rather than add one.
#
# Re-curated to 62 on 2026-08-28 when `test_github_actions_ci.py` split into
# `test_github_actions_ci_workflow.py`, `test_github_actions_publish.py`, and
# `test_github_actions_setup_sase.py`. The two added entries redistribute the
# same checked-in workflow/action YAML guards rather than expanding behavioral
# coverage. The whole 62-entry set measured 32.14 s under the command above on
# this host; the next candidate should displace an entry rather than add one.
#
# Re-curated to 63 when `test_validate_test_environment_tool.py` joined the
# contract set as a `tools/` script guard (no import-graph seeds). The
# 63-entry set is estimated at 33.24 s from the 62-entry measurement plus
# that file's shard timing.
_MANIFEST_ENTRY_BUDGET = 63
_MEASURED_SERIAL_COST = "33.24 serial seconds across 63 entries"


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
            f"The current set was measured at {_MEASURED_SERIAL_COST}; "
            "lower this cap and update the measured-cost comment so removed entries "
            "do not become hidden headroom.\n"
            "Use the curation procedure in plans/202608/test_suite_tier1.md."
        )
    overflow = files[_MANIFEST_ENTRY_BUDGET:]
    return (
        "tests/contract_manifest.txt contains "
        f"{count} entries, over the {_MANIFEST_ENTRY_BUDGET}-entry "
        "contract-set budget.\n"
        f"The current set was measured at {_MEASURED_SERIAL_COST}.\n"
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
    assert f"tests/generated_contract_{_MANIFEST_ENTRY_BUDGET}.py" in message
