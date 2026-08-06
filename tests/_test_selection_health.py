"""False-negative detection and the summary the project owner reads.

Diff-scoped selection is a heuristic (see :mod:`tests._test_selection`), so the
only honest way to run it as the default verification lane is to *measure*
whether it has ever been wrong. This module owns that measurement, over the two
record kinds :mod:`tests._test_selection_health_store` writes and
:mod:`tests._test_selection_health_records` reads back:

``selection``
    One per ``tools/run_pytest scoped`` run: the manifest the engine produced,
    plus the duration and outcome the runner appended.
``full-run``
    One per full-lane run (``just test`` / ``just check-full`` / the coverage
    leg): the node IDs that failed, and the commit they failed at.

A **false negative** is a test that failed in a full run and was *excluded* by a
scoped run over an ancestor of the same change. Correlating the two record
kinds is what turns "selection is probably fine" into a number.

"The same change" is the load-bearing half of that definition. The store is
shared by every numbered workspace and those workspaces normally sit on the
same master HEAD, so ancestry alone makes ``is_ancestor(head, head)`` trivially
true and charges every workspace's flakes to every other workspace's selection.
A scoped run is therefore charged with a full-run failure only when *all* of:

* both records name the same workspace;
* the scoped run's HEAD is an ancestor of the full run's HEAD;
* the full run's change set covers the scoped run's — equal, or a superset,
  because agents commit as they go and the change set is computed against the
  ``origin/master`` merge-base, so a later full run in the same workspace
  normally sees a superset of an earlier scoped run's files;
* the scoped run did not escalate, and did not select the failing test's file.

Records written before schema 2 carry neither a workspace nor a change set, so
they cannot satisfy that rule. They are excluded from correlation and counted
separately in the report, so a zero reading is never mistaken for a clean one.

A failure that satisfies all of the above can still be a **known flake** rather
than a real miss: see :func:`reproducible_flake_nodeids`. Those matches are
routed to :func:`find_flake_suppressed` instead of :func:`find_false_negatives`
and reported separately, not dropped.

:mod:`tests._test_selection_health_report` turns the summary into prose and
JSON; ``tools/selection_health`` is the command that prints it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tests._test_selection_contexts import contexts_consulted
from tests._test_selection_graph import SelectionError, is_visual_path, run_git
from tests._test_selection_health_records import FullRunRecord, HealthRecords


#: The full suite's measured cost, in worker-seconds, from the Tier 1 research
#: report: 25,937 tests summed across twelve xdist workers. It is the baseline
#: a scoped run is credited against, and it is deliberately a constant: the
#: point of the metric is host demand avoided, not a re-measured wall time.
FULL_SUITE_WORKER_SECONDS = 3650.0

#: The governed full lane's measured wall clock: 232s at 28 workers, 26,042
#: tests, measured on athena at master `5da193482` on 2026-08-06 (see
#: `plans/202608/scoped_lane_latency.md`). A scoped run slower than this would
#: have finished sooner on the full lane instead, which is the defect this
#: module's `slow_runs` exists to surface. Deliberately a constant for the same
#: reason as `FULL_SUITE_WORKER_SECONDS`: it is a fixed crossover to measure
#: against, not a re-measured wall time on every report.
FULL_LANE_WALL_SECONDS = 232.0


# --------------------------------------------------------------------------
# False-negative detection
# --------------------------------------------------------------------------


AncestorOracle = Callable[[str, str], bool]


def git_ancestor_oracle(root: Path) -> AncestorOracle:
    """An ``is-ancestor`` predicate, memoised per commit pair.

    A commit this workspace has never fetched — a sibling workspace's manifest
    can name one — answers ``False`` rather than raising: an unverifiable
    ancestry claim must not be reported as a false negative.
    """
    cache: dict[tuple[str, str], bool] = {}

    def _is_ancestor(ancestor: str, descendant: str) -> bool:
        key = (ancestor, descendant)
        if key not in cache:
            try:
                run_git(root, "merge-base", "--is-ancestor", ancestor, descendant)
            except SelectionError:
                cache[key] = False
            else:
                cache[key] = True
        return cache[key]

    return _is_ancestor


def nodeid_test_file(nodeid: str) -> str:
    """The file part of a pytest node ID.

    Named subject-first rather than ``test_file_for_nodeid`` so importing it
    into a test module does not make pytest try to collect it.
    """
    return nodeid.split("::", 1)[0].replace("\\", "/")


@dataclass(frozen=True)
class FalseNegative:
    nodeid: str
    test_file: str
    selection_record: str
    selection_head: str | None
    selection_changed_files: tuple[str, ...]
    full_run_record: str
    full_run_head: str | None
    workspace: str
    rules: tuple[str, ...]


@dataclass(frozen=True)
class PreSchemaRecords:
    """Records with no correlation identity, and so not correlated at all."""

    selections: int = 0
    full_runs: int = 0

    @property
    def total(self) -> int:
        return self.selections + self.full_runs


def count_pre_schema_records(records: HealthRecords) -> PreSchemaRecords:
    """How much of the store predates the identity correlation requires.

    The store holds up to ``RETENTION_DAYS`` of records written before schema
    2, and those can only be dropped from the metric, never rescued: the
    workspace and change set they would need were never written down. A
    reader seeing "0 false negatives" is entitled to know how many records
    that zero was computed over.
    """
    return PreSchemaRecords(
        selections=sum(
            1 for selection in records.selections if selection.identity is None
        ),
        full_runs=sum(1 for full_run in records.full_runs if full_run.identity is None),
    )


def reproducible_flake_nodeids(full_runs: Sequence[FullRunRecord]) -> frozenset[str]:
    """Node IDs whose full-run failures share no change-set file in common.

    A genuine miss recurs only across the ancestors of the one diff that broke
    it, so every full run charging it shares that diff's files. A test whose
    failures instead span two or more full runs with **no** file in common
    cannot be attributed to any of those diffs — the common thread is the run
    itself (host load, xdist worker assignment, environment staleness), not
    the change. That is exactly the shape this project has already diagnosed
    by hand for the ACE-TUI test-isolation family (``sase-ct``) and the
    bead-mutation lock timeout (``sase-e2``): a different, unrelated diff each
    time, passing immediately in isolation.

    A hand-maintained node-ID list was considered and rejected for this rule:
    the real store already shows failures reproducing across unrelated diffs
    on nodes no bead had enumerated yet (an out-of-date ``sase_core_rs``
    binding failing ``test_malformed_header_block_leaves_authored_metadata_visible``
    identically in five unrelated workspaces), so a fixed list would already be
    behind. This check needs no maintenance and generalizes to whatever the
    next flake turns out to be.

    Requires at least two full runs with a recorded change set (schema 2+) for
    the same node; a node seen failing only once, or only in runs with no
    identity, is never called reproducible here.
    """
    change_sets_by_node: dict[str, list[frozenset[str]]] = {}
    for full_run in full_runs:
        if full_run.changed_files is None:
            continue
        for nodeid in full_run.failures:
            change_sets_by_node.setdefault(nodeid, []).append(full_run.changed_files)

    flakes: set[str] = set()
    for nodeid, change_sets in change_sets_by_node.items():
        unique = {frozenset(changed) for changed in change_sets}
        if len(unique) < 2:
            continue
        if not frozenset.intersection(*unique):
            flakes.add(nodeid)
    return frozenset(flakes)


def _correlate_full_run_failures(
    records: HealthRecords, *, is_ancestor: AncestorOracle
) -> list[FalseNegative]:
    """Every full-run failure an ancestor scoped selection excluded, unfiltered.

    A pair must plausibly describe *the same change* (see the module
    docstring): same workspace, scoped HEAD an ancestor of the full run's, and
    the full run's change set a superset of or equal to the scoped run's.
    Without all three, one workspace's flake is charged to another workspace's
    selection, which is what this correlator existed to avoid measuring.

    Escalated manifests are skipped because they ran everything: they excluded
    nothing and cannot have missed anything. Visual paths are skipped because
    the selector excludes them unconditionally and by design; ``just
    test-visual`` is their lane. Records with no identity — anything written
    before schema 2 — are skipped and counted by
    :func:`count_pre_schema_records`.

    Shared by :func:`find_false_negatives` and :func:`find_flake_suppressed`,
    which split this list on :func:`reproducible_flake_nodeids` rather than
    each re-walking the store.
    """
    candidates = [
        (selection, identity)
        for selection in records.selections
        if not selection.escalated
        and selection.head
        and (identity := selection.identity) is not None
    ]
    matches: list[FalseNegative] = []
    for full_run in records.full_runs:
        full_run_identity = full_run.identity
        if not full_run.head or not full_run.failures or full_run_identity is None:
            continue
        full_workspace, full_changed = full_run_identity
        related = [
            (selection, changed)
            for selection, (workspace, changed) in candidates
            if workspace == full_workspace and changed <= full_changed
        ]
        for nodeid in full_run.failures:
            test_file = nodeid_test_file(nodeid)
            if is_visual_path(test_file):
                continue
            for selection, changed in related:
                if test_file in selection.selected:
                    continue
                head = selection.head
                assert head is not None
                if not is_ancestor(head, full_run.head):
                    continue
                matches.append(
                    FalseNegative(
                        nodeid=nodeid,
                        test_file=test_file,
                        selection_record=selection.name,
                        selection_head=head,
                        selection_changed_files=tuple(sorted(changed)),
                        full_run_record=full_run.name,
                        full_run_head=full_run.head,
                        workspace=full_workspace,
                        rules=selection.rules,
                    )
                )
    return matches


def find_false_negatives(
    records: HealthRecords, *, is_ancestor: AncestorOracle
) -> list[FalseNegative]:
    """Match full-run failures against scoped runs that excluded them.

    See :func:`_correlate_full_run_failures` for the matching rule. A match
    whose node is a :func:`reproducible_flake_nodeids` member is excluded here
    and reported instead by :func:`find_flake_suppressed`: it is evidence the
    lane cannot act on, not a selection miss.
    """
    flaky = reproducible_flake_nodeids(records.full_runs)
    return [
        match
        for match in _correlate_full_run_failures(records, is_ancestor=is_ancestor)
        if match.nodeid not in flaky
    ]


def find_flake_suppressed(
    records: HealthRecords, *, is_ancestor: AncestorOracle
) -> list[FalseNegative]:
    """The other half of :func:`find_false_negatives`'s split: known flakes.

    Same matches, same matching rule — only routed here instead because their
    node is a :func:`reproducible_flake_nodeids` member. Excluded from the
    false-negative count, but never silently dropped: the health report counts
    and lists these too.
    """
    flaky = reproducible_flake_nodeids(records.full_runs)
    return [
        match
        for match in _correlate_full_run_failures(records, is_ancestor=is_ancestor)
        if match.nodeid in flaky
    ]


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _median(values: Sequence[float]) -> float | None:
    return _percentile(values, 0.5)


@dataclass(frozen=True)
class SlowRun:
    """A scoped run that took longer than the governed full lane would have.

    The eight runs this shape describes cost the epic's research 75% of its
    measured scoped-lane wall clock; see `plans/202608/scoped_lane_latency.md`.

    The comparison is wall clock against wall clock, so it stays meaningful at
    any :attr:`worker_count`: a run the middle gear widened is still a run the
    waiting agent would have had sooner from the full lane.
    """

    record: str
    duration: float
    selected_count: int
    rules: tuple[str, ...]
    #: The width the run executed at; ``1`` for every serial scoped run.
    worker_count: int = 1


@dataclass(frozen=True)
class SelectionHealth:
    scoped_runs: int = 0
    escalated_runs: int = 0
    full_runs: int = 0
    universe_count: int | None = None
    median_selected: float | None = None
    p90_selected: float | None = None
    median_duration: float | None = None
    p75_duration: float | None = None
    p90_duration: float | None = None
    max_duration: float | None = None
    slow_runs: tuple[SlowRun, ...] = ()
    #: How many unescalated runs executed at each granted worker width. A
    #: 130s run at four workers is not the same reading as a 130s serial one,
    #: and the duration percentiles above pool both — so the mix is reported
    #: rather than left for a reader to assume away.
    duration_widths: dict[int, int] = field(default_factory=dict)
    #: Runs the middle gear ran at a bounded width, and runs it was offered
    #: but could not lease for (which escalated instead).
    gear_runs: int = 0
    gear_refused_runs: int = 0
    worker_seconds_saved: float = 0.0
    rule_histogram: dict[str, int] = field(default_factory=dict)
    outcome_histogram: dict[str, int] = field(default_factory=dict)
    #: Scoped runs that reached the baseline cache at all — the denominator
    #: `context_runs` belongs over. The rest escalated to the full suite before
    #: contexts could matter.
    context_consulted_runs: int = 0
    context_runs: int = 0
    context_stale_runs: int = 0
    context_selected_total: int = 0
    false_negatives: tuple[FalseNegative, ...] = ()
    #: Matches :attr:`false_negatives` would otherwise contain, but excluded
    #: because the node is a `reproducible_flake_nodeids` member. Counted and
    #: shown, not dropped — see :func:`find_flake_suppressed`.
    flake_suppressed: tuple[FalseNegative, ...] = ()
    pre_schema: PreSchemaRecords = PreSchemaRecords()

    @property
    def escalation_rate(self) -> float | None:
        if not self.scoped_runs:
            return None
        return self.escalated_runs / self.scoped_runs

    @property
    def context_missing_runs(self) -> int:
        """Runs that looked for a baseline, found none, and narrowed anyway.

        This is the lane's real closure-only exposure, and the number phase
        `compensate`'s `no-baseline-depth-boost` is sized against.
        """
        return self.context_consulted_runs - self.context_runs

    @property
    def context_not_consulted_runs(self) -> int:
        return self.scoped_runs - self.context_consulted_runs

    @property
    def median_selected_ratio(self) -> float | None:
        if self.median_selected is None or not self.universe_count:
            return None
        return self.median_selected / self.universe_count


def summarize(
    records: HealthRecords, *, is_ancestor: AncestorOracle
) -> SelectionHealth:
    """Reduce the store to the numbers the project owner reads."""
    scoped = records.selections
    unescalated = [selection for selection in scoped if not selection.escalated]
    selected_counts = [float(selection.selected_count) for selection in unescalated]
    durations = [
        selection.duration
        for selection in unescalated
        if selection.duration is not None
    ]
    # Escalated runs record `duration: 0.0` (the runner hands off with `execv`
    # before it can time the full lane it triggered), so they are excluded
    # here rather than counted as fast; `escalated_runs` already says how many
    # runs' cost this leaves unmeasured, and the report states it explicitly.
    slow_runs = tuple(
        SlowRun(
            record=selection.name,
            duration=selection.duration,
            selected_count=selection.selected_count,
            rules=selection.rules,
            worker_count=selection.worker_count,
        )
        for selection in unescalated
        if selection.duration is not None
        and selection.duration > FULL_LANE_WALL_SECONDS
    )
    duration_widths: dict[int, int] = {}
    for selection in unescalated:
        if selection.duration is None:
            continue
        width = selection.worker_count
        duration_widths[width] = duration_widths.get(width, 0) + 1

    rule_histogram: dict[str, int] = {}
    outcome_histogram: dict[str, int] = {}
    for selection in scoped:
        for rule in selection.rules:
            rule_histogram[rule] = rule_histogram.get(rule, 0) + 1
        outcome_histogram[selection.outcome] = (
            outcome_histogram.get(selection.outcome, 0) + 1
        )

    # Worker-seconds, not wall seconds: a run the middle gear widened to four
    # workers spent four times its wall clock of host demand, and crediting it
    # as if it had been serial would inflate the one number this report leads
    # with.
    saved = sum(
        max(
            0.0,
            FULL_SUITE_WORKER_SECONDS
            - (selection.duration or 0.0) * selection.worker_count,
        )
        for selection in unescalated
    )
    universes = [
        int(selection.manifest.get("universe_count") or 0)
        for selection in scoped
        if selection.manifest.get("universe_count")
    ]

    # Only a run that actually reached the baseline cache can be counted for or
    # against it. A run a rule forced to the full suite never looked, and
    # charging it as "no baseline — static closure alone" is how a lane whose
    # real closure-only exposure is a couple of runs reads as half of them.
    consulted = [
        selection.contexts
        for selection in scoped
        if contexts_consulted(selection.contexts, escalated=selection.escalated)
    ]
    with_baseline = [contexts for contexts in consulted if contexts.get("baseline")]

    return SelectionHealth(
        scoped_runs=len(scoped),
        escalated_runs=len(scoped) - len(unescalated),
        full_runs=len(records.full_runs),
        universe_count=max(universes) if universes else None,
        median_selected=_median(selected_counts),
        p90_selected=_percentile(selected_counts, 0.9),
        median_duration=_median(durations),
        p75_duration=_percentile(durations, 0.75),
        p90_duration=_percentile(durations, 0.9),
        max_duration=max(durations) if durations else None,
        slow_runs=slow_runs,
        duration_widths=dict(sorted(duration_widths.items())),
        gear_runs=sum(1 for selection in unescalated if selection.worker_count > 1),
        gear_refused_runs=sum(1 for selection in scoped if selection.gear_refused),
        worker_seconds_saved=saved,
        rule_histogram=dict(sorted(rule_histogram.items())),
        outcome_histogram=dict(sorted(outcome_histogram.items())),
        context_consulted_runs=len(consulted),
        context_runs=len(with_baseline),
        context_stale_runs=sum(
            1 for contexts in with_baseline if contexts.get("stale")
        ),
        context_selected_total=sum(
            int(contexts.get("selected_count") or 0) for contexts in with_baseline
        ),
        false_negatives=tuple(find_false_negatives(records, is_ancestor=is_ancestor)),
        flake_suppressed=tuple(find_flake_suppressed(records, is_ancestor=is_ancestor)),
        pre_schema=count_pre_schema_records(records),
    )
