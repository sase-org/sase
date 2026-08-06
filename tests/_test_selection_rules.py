"""Broadening rules: the named reasons a change set widens the selection.

Split out of :mod:`tests._test_selection` so neither half grows past the
repository's per-file line budget. Every rule here exists because the reverse
import closure is unsound for some class of change — a fixture that the graph
cannot see, a config file that has no importers, an environment that changed
underneath the graph entirely. The rules are named because the manifest records
which ones fired, and ``just selection-health`` reads that record back.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from tests._test_selection_graph import ImportGraph


CONTRACT_MANIFEST_PATH = "tests/contract_manifest.txt"

RULE_BASE_UNRESOLVED = "base-unresolved"
RULE_ROOT_CONFTEST = "root-conftest"
RULE_PACKAGING_CONFIG = "packaging-config"
RULE_JUSTFILE = "justfile"
RULE_SRC_DATA_ASSET = "src-data-asset"
RULE_SELECTION_TOOLING = "selection-tooling"
#: Fires when a *core-identity* environment input differs from the previous
#: manifest's baseline — not on every input the fingerprint digests. Only the
#: buckets in `tests._test_selection_manifest.ENVIRONMENT_ESCALATING_INPUTS`
#: qualify (`pyproject`, `uv-lock`, `venv-config`, `core-cargo`, `extension`,
#: `python`); a validator script or an unrelated package's installed metadata
#: changing does not fire this rule. `evaluate_broadening_rules` below takes
#: the already-narrowed boolean as `core_identity_changed`; the manifest's
#: `baseline.environment_changed_inputs` records every bucket that moved,
#: escalating or not, so a non-escalating change stays visible instead of
#: silent — see `sase-gj.4`.
RULE_CORE_IDENTITY_CHANGED = "core-identity-changed"
RULE_DIRECTORY_CONFTEST = "directory-conftest"
RULE_CONTRACT_SET_ALWAYS = "contract-set-always"
RULE_CONTRACT_SET_ONLY = "contract-set-only"
RULE_RENAME_OR_DELETE = "rename-or-delete"
#: The selection is too large a share of the suite to be worth running scoped.
#: A *fallback*: it survives only for the case where no duration table exists,
#: because file count is a 6x-spread proxy for runtime and the selections that
#: blow the runtime budget are precisely the ones it rates as cheap. See
#: ``RULE_SERIAL_BUDGET_EXCEEDED``, which supersedes it wherever the table can
#: answer.
RULE_RATIO_EXCEEDED = "selection-ratio-exceeded"

#: A serial run of the selection is estimated to cost more than the governed
#: full lane's wall clock (``SASE_TEST_SELECTION_MAX_SERIAL_SECONDS``, default
#: :data:`tests._test_selection_health.FULL_LANE_WALL_SECONDS`). Past that
#: crossover the "fast path" is the slow path: the same agent would have had
#: `just check-full` sooner. Evaluated only when
#: :func:`tests._test_selection_timings.estimate_serial_seconds` returns an
#: available estimate; when it does not, ``RULE_RATIO_EXCEEDED`` decides
#: instead, so a host with no table behaves exactly as it did before.
RULE_SERIAL_BUDGET_EXCEEDED = "serial-budget-exceeded"

RULE_NO_BASELINE_DEPTH_BOOST = "no-baseline-depth-boost"

#: Rules whose only sound response is to run everything.
#:
#: This set is consulted by :meth:`RuleEvaluation.forces_full_suite`, which
#: runs *before* the closure, so it holds only rules
#: :func:`evaluate_broadening_rules` can decide from the change set alone.
#: ``RULE_RATIO_EXCEEDED`` and ``RULE_SERIAL_BUDGET_EXCEEDED`` also escalate,
#: but neither can be known until there is a selection to measure; both are
#: appended by :func:`tests._test_selection.select_tests` afterwards and are
#: deliberately absent here for that reason, not because they are weaker.
#:
#: ``RULE_NO_BASELINE_DEPTH_BOOST`` is deliberately absent. Absence of a usable
#: coverage baseline is uncommon per-run on a host that fetches or records one,
#: but it is the *standing* condition of a workspace that is offline or idle
#: past the CI artifact's retention — so escalating on it would hand those
#: workspaces a permanently full lane. It compensates by walking one hop
#: deeper instead, which the backtest measured as recovering 91% of the
#: closure's blind spot; see :func:`tests._test_selection.select_tests`.
FULL_SUITE_RULES = frozenset(
    {
        RULE_BASE_UNRESOLVED,
        RULE_ROOT_CONFTEST,
        RULE_PACKAGING_CONFIG,
        RULE_JUSTFILE,
        RULE_SRC_DATA_ASSET,
        RULE_SELECTION_TOOLING,
        RULE_CORE_IDENTITY_CHANGED,
    }
)

#: The root conftest and every module it imports from within the repository.
#: A change to any of them can alter fixture behaviour for the whole suite.
ROOT_CONFTEST_PATHS = frozenset(
    {
        "tests/conftest.py",
        "tests/_suite_gate.py",
        "tests/_tmp_leak_guard.py",
        "tests/_project_display_case.py",
    }
)
PACKAGING_CONFIG_PATHS = frozenset({"pyproject.toml", "uv.lock", "tox.ini"})
JUSTFILE_PATHS = frozenset({"Justfile", "justfile"})
SELECTION_TOOLING_PATHS = frozenset(
    {
        "tools/run_pytest",
        "tools/select_tests",
        "tests/_test_selection.py",
        "tests/_test_selection_changes.py",
        "tests/_test_selection_contexts.py",
        "tests/_test_selection_graph.py",
        "tests/_test_selection_manifest.py",
        "tests/_test_selection_report.py",
        "tests/_test_selection_rules.py",
        # Joined the set with `RULE_SERIAL_BUDGET_EXCEEDED`: the duration table
        # stopped being an inert measurement the moment an escalation started
        # depending on it, and a change to the cost model can move any run
        # across the budget.
        "tests/_test_selection_timings.py",
        CONTRACT_MANIFEST_PATH,
    }
)
SRC_DATA_ASSET_SUFFIXES = (".yml", ".yaml", ".json")


def _is_src_data_asset(path: str) -> bool:
    return path.startswith("src/") and path.endswith(SRC_DATA_ASSET_SUFFIXES)


def _is_directory_conftest(path: str) -> bool:
    return (
        path.startswith("tests/")
        and path.endswith("/conftest.py")
        and path != "tests/conftest.py"
    )


@dataclass(frozen=True)
class RuleEvaluation:
    rules: tuple[str, ...]
    conftest_directories: tuple[str, ...]

    @property
    def forces_full_suite(self) -> bool:
        return any(rule in FULL_SUITE_RULES for rule in self.rules)


def evaluate_broadening_rules(
    changed_paths: Iterable[str],
    *,
    base_resolved: bool,
    core_identity_changed: bool,
    has_rename_or_delete: bool,
    graph: ImportGraph,
) -> RuleEvaluation:
    """Classify the change set into the named rules it triggers."""
    rules: list[str] = []
    conftest_directories: list[str] = []
    known_module_paths = 0

    if not base_resolved:
        rules.append(RULE_BASE_UNRESOLVED)
    if core_identity_changed:
        rules.append(RULE_CORE_IDENTITY_CHANGED)

    for path in changed_paths:
        if path in ROOT_CONFTEST_PATHS:
            rules.append(RULE_ROOT_CONFTEST)
        elif path in PACKAGING_CONFIG_PATHS:
            rules.append(RULE_PACKAGING_CONFIG)
        elif path in JUSTFILE_PATHS:
            rules.append(RULE_JUSTFILE)
        elif path in SELECTION_TOOLING_PATHS:
            rules.append(RULE_SELECTION_TOOLING)
        elif _is_src_data_asset(path):
            rules.append(RULE_SRC_DATA_ASSET)
        elif _is_directory_conftest(path):
            rules.append(RULE_DIRECTORY_CONFTEST)
            conftest_directories.append(path[: -len("/conftest.py")])
        if path in graph.paths:
            known_module_paths += 1

    if has_rename_or_delete:
        rules.append(RULE_RENAME_OR_DELETE)
    if known_module_paths == 0 and not conftest_directories:
        # Docs, sdd/**, .github/**, and friends contribute no seeds at all.
        rules.append(RULE_CONTRACT_SET_ONLY)

    ordered = tuple(sorted(set(rules)))
    return RuleEvaluation(
        rules=ordered,
        conftest_directories=tuple(sorted(set(conftest_directories))),
    )
