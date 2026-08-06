"""Diff-scoped test selection over a cached static import graph.

This module lives beside ``tests/_suite_gate.py`` for the same reasons: it is
repository build tooling rather than product code, ``tools/run_pytest`` already
imports its shared runner logic from a private ``tests/_*.py`` module, and code
under ``tests/`` sits outside symvision's ``src/sase`` scan and outside mypy's
``files = ["src"]``.

The selector answers one question: given a change set, which ``test_*.py``
files plausibly cover it? It answers it with a *depth-bounded* reverse walk of
the in-repo import graph, because ``src/sase`` contains a single 497-module
strongly-connected component whose members transitively reach ~87% of the test
suite. Unbounded reverse closure is therefore not a selector; depth-bounding is
the mechanism, not a tuning knob.

Selection is deliberately a heuristic. The broadening rules, the escalation
threshold, the always-included contract set, and the manifest that records
every decision all exist because the closure is unsound.

This module holds the closure and the policy that surrounds it. Its neighbours
hold the parts that stand on their own:

* :mod:`tests._test_selection_graph` — building the import graph.
* :mod:`tests._test_selection_changes` — asking git what moved.
* :mod:`tests._test_selection_rules` — the named broadening rules.
* :mod:`tests._test_selection_manifest` — cache paths, manifest I/O, and the
  environment fingerprint the manifest baseline is keyed to.
* :mod:`tests._test_selection_contexts` — per-test coverage as a second source.
* :mod:`tests._test_selection_timings` — what the selected files cost to run.
* :mod:`tests._test_selection_report` — rendering a selection for a reader.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests._test_selection_changes import ChangeSet, compute_change_set
from tests._test_selection_contexts import (
    ContextSelection,
    select_from_contexts,
)
from tests._test_selection_graph import (
    ImportGraph,
    SelectionError,
    build_import_graph,
    is_test_file,
    is_visual_path,
)
from tests._test_selection_health import FULL_LANE_WALL_SECONDS
from tests._test_selection_health_store import store_directory
from tests._test_selection_manifest import (
    ENVIRONMENT_ESCALATING_INPUTS,
    GRAPH_CACHE_FILENAME,
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA,
    SELECTION_DIRECTORY,
    environment_changed_inputs,
    environment_fingerprint,
    read_manifest,
)
from tests._test_selection_rules import (
    CONTRACT_MANIFEST_PATH,
    RULE_CONTRACT_SET_ALWAYS,
    RULE_NO_BASELINE_DEPTH_BOOST,
    RULE_RATIO_EXCEEDED,
    RULE_SERIAL_BUDGET_EXCEEDED,
    evaluate_broadening_rules,
)
from tests._test_selection_timings import (
    REASON_ESCALATED,
    TimingEstimate,
    estimate_serial_seconds,
    timings_directory,
)


DEFAULT_DEPTH = 2
DEFAULT_MAX_RATIO = 0.25
#: The serial-runtime budget: the crossover past which running the selection
#: scoped costs the waiting agent more than handing the whole suite to the
#: governed parallel lane would have. It is the full lane's measured wall
#: clock, not a round number — see
#: :data:`tests._test_selection_health.FULL_LANE_WALL_SECONDS`.
DEFAULT_MAX_SERIAL_SECONDS = FULL_LANE_WALL_SECONDS
DEFAULT_BASE_REF = "origin/master"

DEPTH_ENV = "SASE_TEST_SELECTION_DEPTH"
MAX_RATIO_ENV = "SASE_TEST_SELECTION_MAX_RATIO"
MAX_SERIAL_SECONDS_ENV = "SASE_TEST_SELECTION_MAX_SERIAL_SECONDS"
BASE_ENV = "SASE_CHECK_BASE"

FULL_SUITE = "FULL_SUITE"


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionOptions:
    base_ref: str = DEFAULT_BASE_REF
    depth: int = DEFAULT_DEPTH
    max_ratio: float = DEFAULT_MAX_RATIO
    max_serial_seconds: float = DEFAULT_MAX_SERIAL_SECONDS
    use_cache: bool = True

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        base_ref: str | None = None,
        depth: int | None = None,
        max_ratio: float | None = None,
        max_serial_seconds: float | None = None,
        use_cache: bool = True,
    ) -> SelectionOptions:
        environ = os.environ if environ is None else environ
        if base_ref is None:
            base_ref = environ.get(BASE_ENV) or DEFAULT_BASE_REF
        if depth is None:
            depth = _positive_int(environ.get(DEPTH_ENV), DEFAULT_DEPTH, DEPTH_ENV)
        if max_ratio is None:
            max_ratio = _ratio(environ.get(MAX_RATIO_ENV), DEFAULT_MAX_RATIO)
        if max_serial_seconds is None:
            max_serial_seconds = _positive_float(
                environ.get(MAX_SERIAL_SECONDS_ENV),
                DEFAULT_MAX_SERIAL_SECONDS,
                MAX_SERIAL_SECONDS_ENV,
            )
        elif max_serial_seconds <= 0:
            # An explicit `--max-serial-seconds 0` is rejected on the same
            # terms as the environment variable rather than silently becoming
            # a budget that escalates everything.
            raise SelectionError(
                "max_serial_seconds must be a positive number of seconds"
            )
        return cls(
            base_ref=base_ref,
            depth=depth,
            max_ratio=max_ratio,
            max_serial_seconds=max_serial_seconds,
            use_cache=use_cache,
        )


def _positive_int(raw: str | None, default: int, name: str) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise SelectionError(f"{name} must be a non-negative integer") from error
    if value < 0:
        raise SelectionError(f"{name} must be a non-negative integer")
    return value


def _positive_float(raw: str | None, default: float, name: str) -> float:
    """A positive number of seconds, or a stated error.

    Zero is rejected along with the negatives: a budget of ``0`` would escalate
    every run that has an estimate at all, which is what
    ``SASE_TEST_SELECTION_TIMINGS_DISABLED=1`` is for and is not what anyone
    means by a budget.
    """
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise SelectionError(f"{name} must be a positive number of seconds") from error
    if value <= 0:
        raise SelectionError(f"{name} must be a positive number of seconds")
    return value


def _ratio(raw: str | None, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise SelectionError(f"{MAX_RATIO_ENV} must be a number in (0, 1]") from error
    if not 0 < value <= 1:
        raise SelectionError(f"{MAX_RATIO_ENV} must be a number in (0, 1]")
    return value


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Selection:
    selected: tuple[str, ...]
    escalated: bool
    rules: tuple[str, ...]
    manifest: dict[str, Any]
    explanations: dict[str, tuple[str, int]]
    universe_count: int
    #: The knobs this selection was made under. Carried so a renderer can say
    #: what an estimate was measured *against* without re-reading the
    #: environment it no longer runs in.
    options: SelectionOptions = SelectionOptions()
    contexts: ContextSelection = ContextSelection()
    #: What a serial run of the candidate selection was estimated to cost, or
    #: why that cannot be said. This is what `RULE_SERIAL_BUDGET_EXCEEDED`
    #: decides on, so on an escalated run it describes the selection that was
    #: rejected rather than the empty one that replaced it — unless a
    #: change-set rule escalated first, in which case there was never a
    #: selection to cost and the reason is `escalated`.
    timings: TimingEstimate = field(default_factory=TimingEstimate)
    #: The selection the serial budget rejected, kept so the runner can offer
    #: it to the middle gear (:mod:`tests._test_selection_gear`) before handing
    #: the whole suite to the full lane. Empty unless
    #: `RULE_SERIAL_BUDGET_EXCEEDED` was the *only* reason this run escalated:
    #: a change-set rule escalates because the closure cannot be trusted for
    #: that change, which no amount of parallelism answers, and the ratio
    #: escalates precisely where there is no cost model to bound a gear with.
    gear_candidate: tuple[str, ...] = ()

    @property
    def paths_output(self) -> str:
        if self.escalated:
            return FULL_SUITE
        return "\n".join(self.selected)


def load_contract_manifest(root: Path, path: str = CONTRACT_MANIFEST_PATH) -> list[str]:
    """Read the committed contract-set manifest, if the ``contract`` phase landed.

    An absent manifest is a valid input: it means the contract set is empty.
    """
    try:
        raw = (root / path).read_text(encoding="utf-8")
    except OSError:
        return []
    return sorted(
        {
            line.strip()
            for line in raw.splitlines()
            if line.strip() and not line.startswith("#")
        }
    )


def _closure(
    graph: ImportGraph,
    seeds: Sequence[str],
    depth: int,
) -> dict[str, tuple[str, int]]:
    """Walk reverse import edges ``depth`` times from ``seeds``.

    Terminal (test) modules reached at any hop join the selection; expandable
    modules join the next frontier. After the bounded walk, the direct terminal
    importers of every expandable module reached are harvested, so a depth of
    ``N`` means "``N`` hops of production/helper modules, then the tests".
    """
    terminals: dict[str, tuple[str, int]] = {}
    reached: dict[str, tuple[str, int]] = {}
    frontier: dict[str, tuple[str, int]] = {}

    for module in seeds:
        path = graph.path_for(module)
        if path is None:
            continue
        if is_test_file(path):
            terminals.setdefault(module, (module, 0))
            continue
        reached.setdefault(module, (module, 0))
        frontier.setdefault(module, (module, 0))

    for hop in range(1, depth + 1):
        next_frontier: dict[str, tuple[str, int]] = {}
        for module, (seed, _) in frontier.items():
            for importer in graph.importers.get(module, ()):
                importer_path = graph.path_for(importer)
                if importer_path is None:
                    continue
                if is_test_file(importer_path):
                    terminals.setdefault(importer, (seed, hop))
                    continue
                if importer in reached:
                    continue
                reached[importer] = (seed, hop)
                next_frontier[importer] = (seed, hop)
        frontier = next_frontier
        if not frontier:
            break

    for module, (seed, hop) in reached.items():
        for importer in graph.importers.get(module, ()):
            importer_path = graph.path_for(importer)
            if importer_path is not None and is_test_file(importer_path):
                terminals.setdefault(importer, (seed, hop + 1))

    return terminals


def _tests_under(graph: ImportGraph, directory: str) -> list[str]:
    prefix = f"{directory}/"
    return [
        path for path in graph.paths if path.startswith(prefix) and is_test_file(path)
    ]


def select_tests(
    root: Path,
    options: SelectionOptions | None = None,
    *,
    graph: ImportGraph | None = None,
    change_set: ChangeSet | None = None,
    contract_set: Sequence[str] | None = None,
    environment: Mapping[str, str] | None = None,
    previous_manifest: Mapping[str, Any] | None = None,
    contexts_store: Path | None = None,
    timings_store: Path | None = None,
) -> Selection:
    """Select the test files that plausibly cover the current change set."""
    options = options or SelectionOptions.from_environment()
    if graph is None:
        graph = build_import_graph(
            root,
            cache_path=root / SELECTION_DIRECTORY / GRAPH_CACHE_FILENAME,
            use_cache=options.use_cache,
        )
    if change_set is None:
        change_set = compute_change_set(root, options.base_ref)
    if contract_set is None:
        contract_set = load_contract_manifest(root)
    if environment is None:
        environment = environment_fingerprint(root)
    if previous_manifest is None:
        previous_manifest = read_manifest(
            root / SELECTION_DIRECTORY / MANIFEST_FILENAME
        )

    previous_environment = (
        (previous_manifest or {}).get("baseline", {}).get("environment")
    )
    changed_environment_inputs = environment_changed_inputs(
        environment, previous_environment
    )
    core_identity_changed = bool(
        changed_environment_inputs & ENVIRONMENT_ESCALATING_INPUTS
    )

    evaluation = evaluate_broadening_rules(
        change_set.paths,
        base_resolved=change_set.merge_base is not None,
        core_identity_changed=core_identity_changed,
        has_rename_or_delete=change_set.has_rename_or_delete,
        graph=graph,
    )

    universe = sorted(
        path for path in graph.paths if is_test_file(path) and not is_visual_path(path)
    )
    rules = list(evaluation.rules)

    # A rule that forces the full suite short-circuits the branch below, so
    # contexts are never looked at on that path. Say so on the manifest instead
    # of leaving a default-shaped `contexts` block that reads as "the baseline
    # was missing" — an escalated run ran every test and was never exposed to a
    # narrower selection at all.
    contexts = ContextSelection(consulted=False)
    gear_candidate: tuple[str, ...] = ()
    selected: set[str] = set()
    explanations: dict[str, tuple[str, int]] = {}
    depth = options.depth
    if not evaluation.forces_full_suite:
        # Ground truth is consulted *before* the closure because whether a
        # usable baseline exists decides how deep the closure has to walk. It is
        # still unioned in below and never substituted for the closure — see
        # `tests._test_selection_contexts` for why the union is the whole point.
        contexts = select_from_contexts(
            root,
            store=contexts_store
            if contexts_store is not None
            else store_directory(root),
            changed_paths=change_set.paths,
            known_test_files=frozenset(universe),
        )
        rules.extend(contexts.rules)

        # A rename or deletion moves importers around in ways one hop of the
        # graph no longer describes; buy back that hop rather than build
        # bespoke machinery for it.
        depth += 1 if change_set.has_rename_or_delete else 0
        # With no usable baseline the closure is the only source there is, so it
        # buys a hop as well. Measured, not assumed: over 65 replayed commits
        # (`just selection-backtest`) the extra hop is what recovers the tests a
        # baseline-less workspace would otherwise skip in silence.
        if not contexts.usable:
            depth += 1
            rules.append(RULE_NO_BASELINE_DEPTH_BOOST)
        seeds = [
            graph.paths[path]
            for path in change_set.paths
            if path in graph.paths and not is_test_file(path)
        ]
        terminals = _closure(graph, seeds, depth)
        for module, origin in terminals.items():
            path = graph.path_for(module)
            if path is None:
                continue
            selected.add(path)
            explanations[path] = origin

        for directory in evaluation.conftest_directories:
            for path in _tests_under(graph, directory):
                selected.add(path)
                explanations.setdefault(path, (f"{directory}/conftest.py", 0))

        for path in change_set.paths:
            if is_test_file(path):
                selected.add(path)
                explanations.setdefault(path, (path, 0))

        for path in contract_set:
            selected.add(path)
            explanations.setdefault(path, (CONTRACT_MANIFEST_PATH, 0))
        if contract_set:
            rules.append(RULE_CONTRACT_SET_ALWAYS)

        for path in contexts.selected:
            selected.add(path)
            explanations.setdefault(path, (f"contexts:{contexts.baseline_sha}", 0))

        # A changed path can be a deletion or a rename-away: it still shows up
        # verbatim in `change_set.paths` (git diff and status don't distinguish
        # "gone" from "touched" at this call site), so nothing upstream stops a
        # test file that no longer exists from reaching here. `graph.paths` is
        # built from the current working tree (`discover_python_files`), so
        # membership in it is exactly "still on disk" — filtering against it
        # drops deleted/renamed-away paths without touching the closure, which
        # already only ever produces terminals that exist.
        selected = {
            path
            for path in selected
            if not is_visual_path(path) and path in graph.paths
        }

    escalated = evaluation.forces_full_suite

    # What the selection would cost to run serially, decided *before* the
    # selection is thrown away, so the budget rule below has a number and so
    # the manifest can show it whether or not the rule fires. A run that a
    # change-set rule already escalated never had a per-file selection to
    # cost: that records as `escalated`, not as `0.0`.
    if escalated:
        timings = TimingEstimate(reason=REASON_ESCALATED)
    else:
        timings = estimate_serial_seconds(
            sorted(selected),
            directory=timings_directory(
                store_directory(root) if timings_store is None else timings_store
            ),
        )
        # Runtime first, file count only as the fallback. The ratio is a 6x-
        # spread proxy for runtime — the epic measured a 94-file selection at
        # 465s against a 517-file one at 404s — so it is consulted only where
        # the duration table cannot answer, which keeps a fresh host with no
        # table behaving exactly as it did before.
        if timings.available and timings.seconds is not None:
            if timings.seconds > options.max_serial_seconds:
                escalated = True
                rules.append(RULE_SERIAL_BUDGET_EXCEEDED)
                # The one escalation a bounded parallel run can answer: the
                # selection is sound, it is only too slow serially. Keep it so
                # `tools/run_pytest` can offer it to the middle gear.
                gear_candidate = tuple(sorted(selected))
        elif len(selected) > options.max_ratio * len(universe):
            escalated = True
            rules.append(RULE_RATIO_EXCEEDED)

    if escalated:
        selected = set()
        explanations = {}

    ordered_rules = tuple(sorted(set(rules)))
    ordered_selected = tuple(sorted(selected))

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "base": {"ref": change_set.base_ref, "merge_base": change_set.merge_base},
        "changed_files": list(change_set.paths),
        "depth": options.depth,
        # The depth the closure actually walked: the configured depth plus the
        # hops the rename/delete and no-baseline compensations bought. Recorded
        # separately so a reader can tell a configured depth from a compensated
        # one without re-deriving it from `rules_fired`.
        "effective_depth": depth,
        "max_ratio": options.max_ratio,
        # The serial-runtime budget the estimate below was measured against.
        # Recorded on every scoped manifest, including the runs that stayed
        # scoped: "estimated 180s, budget 232s" is the sentence a reader
        # looking at a 400-file selection needs, and it is only a sentence if
        # both halves are on the record.
        "max_serial_seconds": options.max_serial_seconds,
        "rules_fired": list(ordered_rules),
        "escalated": escalated,
        "selected": list(ordered_selected),
        "selected_count": len(ordered_selected),
        "universe_count": len(universe),
        "baseline": {
            "environment": environment,
            # Every bucket that moved since the previous manifest, escalating
            # or not — the honest record for a change that did not force the
            # full suite, not silence. `core-identity-changed` fired only if
            # this set intersects `ENVIRONMENT_ESCALATING_INPUTS`.
            "environment_changed_inputs": sorted(changed_environment_inputs),
            "head": change_set.head,
            "tree_dirty": change_set.tree_dirty,
        },
        "graph": dict(graph.stats),
        "contexts": contexts.payload(),
        "timings": timings.payload(),
    }
    return Selection(
        selected=ordered_selected,
        escalated=escalated,
        rules=ordered_rules,
        manifest=manifest,
        explanations=explanations,
        universe_count=len(universe),
        options=options,
        contexts=contexts,
        timings=timings,
        gear_candidate=gear_candidate,
    )
