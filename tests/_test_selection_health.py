"""Aggregate and expose diff-scoped test-selection health.

The correlation engine lives in :mod:`tests._test_selection_health_correlation`;
this module keeps the stable public import surface while reducing stored health
records to the summary rendered by :mod:`tests._test_selection_health_report`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from tests._test_selection_contexts import contexts_consulted
from tests._test_selection_health_correlation import (
    AncestorOracle,
    CollectibleNodeIdOracle,
    CommitOrderOracle,
    FalseNegative,
    PreSchemaRecords,
    collectible_nodeid_oracle,
    count_pre_schema_records,
    find_false_negatives,
    find_flake_suppressed,
    git_ancestor_oracle,
    git_commit_order_oracle,
    nodeid_test_file,
    reproducible_flake_nodeids,
    stale_flake_nodeids,
    unresolved_commit_order_count,
)
from tests._test_selection_health_records import HealthRecords


__all__ = [
    "FULL_LANE_WALL_SECONDS",
    "FULL_SUITE_WORKER_SECONDS",
    "AncestorOracle",
    "CollectibleNodeIdOracle",
    "CommitOrderOracle",
    "FalseNegative",
    "PreSchemaRecords",
    "SelectionHealth",
    "SlowRun",
    "collectible_nodeid_oracle",
    "count_pre_schema_records",
    "find_false_negatives",
    "find_flake_suppressed",
    "git_ancestor_oracle",
    "git_commit_order_oracle",
    "nodeid_test_file",
    "reproducible_flake_nodeids",
    "stale_flake_nodeids",
    "summarize",
    "unresolved_commit_order_count",
]


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
    records: HealthRecords,
    *,
    is_ancestor: AncestorOracle,
    commit_order: CommitOrderOracle | None = None,
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
        false_negatives=tuple(
            find_false_negatives(
                records, is_ancestor=is_ancestor, commit_order=commit_order
            )
        ),
        flake_suppressed=tuple(
            find_flake_suppressed(
                records, is_ancestor=is_ancestor, commit_order=commit_order
            )
        ),
        pre_schema=count_pre_schema_records(records),
    )
