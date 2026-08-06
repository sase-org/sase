"""Render a :class:`~tests._test_selection_health.SelectionHealth` for a reader.

Two renderings of the same summary: prose for a human running
``tools/selection_health``, and a flat JSON payload for anything that would
rather parse than read. Nothing here computes; if a number is missing from a
report it is missing from :func:`tests._test_selection_health.summarize`.
"""

from __future__ import annotations

from typing import Any

from tests._test_selection_health import (
    FULL_LANE_WALL_SECONDS,
    FULL_SUITE_WORKER_SECONDS,
    FalseNegative,
    SelectionHealth,
)
from tests._test_selection_health_store import HEALTH_SCHEMA


def _format_count(value: float | None, *, universe: int | None) -> str:
    if value is None:
        return "n/a"
    if universe:
        return f"{value:.0f} ({value / universe:.1%} of {universe})"
    return f"{value:.0f}"


def _format_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}s"


def render_report(health: SelectionHealth) -> list[str]:
    """Render the store as prose a human can act on, not a JSON dump."""
    lines = ["Diff-scoped test selection health", ""]
    if not health.scoped_runs and not health.full_runs:
        lines.append("No runs recorded yet. Run `just check` to record one.")
        return lines

    rate = health.escalation_rate
    lines.extend(
        [
            f"scoped runs recorded:   {health.scoped_runs}",
            f"  escalated to full:    {health.escalated_runs}"
            + (f" ({rate:.1%})" if rate is not None else ""),
            "  median selected:      "
            + _format_count(health.median_selected, universe=health.universe_count),
            "  p90 selected:         "
            + _format_count(health.p90_selected, universe=health.universe_count),
            f"  median duration:      {_format_seconds(health.median_duration)}",
            f"  p75 duration:         {_format_seconds(health.p75_duration)}",
            f"  p90 duration:         {_format_seconds(health.p90_duration)}",
            f"  max duration:         {_format_seconds(health.max_duration)}",
            f"full-lane runs recorded: {health.full_runs}",
            "",
            "worker-seconds avoided vs. running the full suite instead: "
            f"{health.worker_seconds_saved:,.0f}"
            f" (~{health.worker_seconds_saved / 60:,.0f} worker-minutes, "
            f"at {FULL_SUITE_WORKER_SECONDS:,.0f}s per full run)",
            "",
        ]
    )

    lines.append("broadening rules fired:")
    if health.rule_histogram:
        for rule, count in health.rule_histogram.items():
            lines.append(f"  {count:>4}  {rule}")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append("scoped run outcomes:")
    if health.outcome_histogram:
        for outcome, count in health.outcome_histogram.items():
            lines.append(f"  {count:>4}  {outcome}")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.extend(_render_slow_runs(health))
    lines.append("")

    lines.extend(_render_contexts(health))
    lines.append("")

    lines.extend(_render_false_negatives(health))
    lines.extend(_render_flake_suppressed(health))
    return lines


def _render_slow_runs(health: SelectionHealth) -> list[str]:
    """The latency-regression counter: scoped runs slower than the full lane.

    A scoped run this slow would have finished sooner running everything, so
    this is the number that would have caught the epic's defect on day one —
    a latency signal, distinct from `false negatives`' correctness one.
    """
    if not health.scoped_runs:
        return ["scoped runs slower than the full lane: no scoped runs recorded"]
    lines = [
        "scoped runs slower than the full lane "
        f"({_format_seconds(FULL_LANE_WALL_SECONDS)}): "
        f"{len(health.slow_runs)} of {health.scoped_runs}",
    ]
    if health.escalated_runs:
        lines.append(
            f"  {health.escalated_runs} escalated run(s) not counted here: cost "
            "not measured (handed off to the full lane before the runner could "
            "time it)"
        )
    for slow in sorted(health.slow_runs, key=lambda run: run.duration, reverse=True):
        lines.append(
            f"  {slow.record}: {_format_seconds(slow.duration)}, "
            f"{slow.selected_count} file(s) selected, "
            f"rules: {', '.join(slow.rules) or 'none'}"
        )
    return lines


def _render_contexts(health: SelectionHealth) -> list[str]:
    """Whether per-test coverage ground truth is reaching these runs at all.

    This is the reading that says whether contexts earn their CI cost: runs
    with no baseline got the static closure alone, and a high stale count next
    to a non-zero false-negative count is the signal to refresh more often.

    The denominator is deliberately the *consulted* runs, not every scoped run.
    A run a rule forced to the full suite never reached the baseline cache and
    executed every test regardless, so counting it as one that ran on the static
    closure alone overstates the lane's exposure — by an order of magnitude on
    a store where roughly half the runs escalate.
    """
    if not health.scoped_runs:
        return ["coverage contexts: no scoped runs recorded"]
    consulted = health.context_consulted_runs
    without = health.context_missing_runs
    lines = [
        "coverage contexts:",
        f"  runs that consulted it: {consulted} of {health.scoped_runs}"
        f" ({health.context_not_consulted_runs} escalated before it mattered)",
        f"  runs with a baseline:  {health.context_runs} of {consulted}",
        f"  runs without one:      {without} (static closure alone)",
        f"  runs on a stale one:   {health.context_stale_runs}",
        f"  test files contributed: {health.context_selected_total} (cumulative)",
    ]
    if without and not health.context_runs:
        lines.append("  Run `just refresh-contexts-baseline` to cache one.")
    return lines


#: Stated in the report because a metric whose matching rule is invisible is a
#: metric nobody can argue with — and this rule is the whole phase.
_MATCHING_RULE_LINES = (
    "  matching rule: a scoped run is charged with a full-run failure only when",
    "  both records name the same workspace, the scoped run's HEAD is an ancestor",
    "  of the full run's, and the full run's change set covers the scoped run's.",
)


def _render_pre_schema(health: SelectionHealth) -> list[str]:
    pre_schema = health.pre_schema
    if not pre_schema.total:
        return []
    return [
        f"  {pre_schema.total} record(s) predate schema {HEALTH_SCHEMA} "
        f"({pre_schema.selections} scoped, {pre_schema.full_runs} full-lane),",
        "  carry no workspace or change set, and are excluded from correlation.",
    ]


def _render_false_negatives(health: SelectionHealth) -> list[str]:
    if not health.false_negatives:
        return [
            "false negatives: 0",
            "  No full-run failure has ever been excluded by a scoped run over an",
            "  ancestor of the same change.",
            *_MATCHING_RULE_LINES,
            *_render_pre_schema(health),
        ]
    # One missed test excluded by twenty ancestor selections is one problem,
    # not twenty; group so the headline number is the number of tests.
    grouped: dict[str, list[FalseNegative]] = {}
    for false_negative in health.false_negatives:
        grouped.setdefault(false_negative.nodeid, []).append(false_negative)

    lines = [
        f"false negatives: {len(grouped)}"
        f" ({len(health.false_negatives)} scoped run/failure matches)",
        *_MATCHING_RULE_LINES,
        *_render_pre_schema(health),
    ]
    for nodeid, matches in sorted(grouped.items()):
        rules = sorted({rule for match in matches for rule in match.rules})
        # Repetition across *unrelated* change sets is the signature of a flake
        # rather than a selection miss: a genuinely missed test is missed by
        # the selections over the one change that should have selected it.
        change_sets = {match.selection_changed_files for match in matches}
        lines.append(f"  {nodeid}")
        lines.append(
            f"    failed in {matches[0].full_run_record} "
            f"(head {(matches[0].full_run_head or '?')[:12]})"
        )
        lines.append(
            f"    excluded by {len(matches)} scoped run(s), first "
            f"{matches[0].selection_record} "
            f"(head {(matches[0].selection_head or '?')[:12]})"
        )
        lines.append(f"    distinct change sets: {len(change_sets)}")
        if len(change_sets) > 1:
            lines.append(
                "    matched across unrelated changes; suspect a flake before a miss"
            )
        lines.append(f"    rules across those runs: {', '.join(rules) or 'none'}")
    lines.extend(
        [
            "",
            "  Known flakes are already excluded from this count (see",
            "  flake-suppressed below); a non-zero count here means the selection",
            "  heuristic itself is unsound as tuned. Raise SASE_TEST_SELECTION_DEPTH",
            "  to 3 or add the missed tests to tests/contract_manifest.txt, then",
            "  re-measure.",
        ]
    )
    return lines


def _render_flake_suppressed(health: SelectionHealth) -> list[str]:
    """Matches excluded from the count above because the node is a known flake.

    Shown, not dropped: a reader who only sees a small false-negative count
    should not have to wonder whether the metric is quietly discarding
    evidence to get there.
    """
    if not health.flake_suppressed:
        return []
    grouped: dict[str, list[FalseNegative]] = {}
    for suppressed in health.flake_suppressed:
        grouped.setdefault(suppressed.nodeid, []).append(suppressed)

    lines = [
        "",
        f"flake-suppressed: {len(grouped)}"
        f" ({len(health.flake_suppressed)} scoped run/failure matches)",
        "  Excluded from false negatives above: each failed in full runs whose",
        "  change sets share no file, so no one diff explains the failure.",
        "  See reproducible_flake_nodeids in tests/_test_selection_health.py.",
    ]
    for nodeid in sorted(grouped):
        lines.append(f"  {nodeid}")
    return lines


def _false_negative_payload(false_negative: FalseNegative) -> dict[str, Any]:
    return {
        "nodeid": false_negative.nodeid,
        "test_file": false_negative.test_file,
        "selection_record": false_negative.selection_record,
        "selection_head": false_negative.selection_head,
        "selection_changed_files": list(false_negative.selection_changed_files),
        "full_run_record": false_negative.full_run_record,
        "full_run_head": false_negative.full_run_head,
        "workspace": false_negative.workspace,
        "rules": list(false_negative.rules),
    }


def health_payload(health: SelectionHealth) -> dict[str, Any]:
    """The same summary, for anything that would rather parse than read."""
    return {
        "schema": HEALTH_SCHEMA,
        "scoped_runs": health.scoped_runs,
        "escalated_runs": health.escalated_runs,
        "escalation_rate": health.escalation_rate,
        "full_runs": health.full_runs,
        "universe_count": health.universe_count,
        "median_selected": health.median_selected,
        "median_selected_ratio": health.median_selected_ratio,
        "p90_selected": health.p90_selected,
        "median_duration": health.median_duration,
        "p75_duration": health.p75_duration,
        "p90_duration": health.p90_duration,
        "max_duration": health.max_duration,
        "full_lane_wall_seconds": FULL_LANE_WALL_SECONDS,
        "slow_runs": [
            {
                "record": slow.record,
                "duration": slow.duration,
                "selected_count": slow.selected_count,
                "rules": list(slow.rules),
            }
            for slow in health.slow_runs
        ],
        "worker_seconds_saved": health.worker_seconds_saved,
        "rule_histogram": health.rule_histogram,
        "outcome_histogram": health.outcome_histogram,
        "context_consulted_runs": health.context_consulted_runs,
        "context_not_consulted_runs": health.context_not_consulted_runs,
        "context_runs": health.context_runs,
        "context_missing_runs": health.context_missing_runs,
        "context_stale_runs": health.context_stale_runs,
        "context_selected_total": health.context_selected_total,
        "pre_schema_selections": health.pre_schema.selections,
        "pre_schema_full_runs": health.pre_schema.full_runs,
        "false_negatives": [
            _false_negative_payload(false_negative)
            for false_negative in health.false_negatives
        ],
        "flake_suppressed": [
            _false_negative_payload(suppressed)
            for suppressed in health.flake_suppressed
        ],
    }
