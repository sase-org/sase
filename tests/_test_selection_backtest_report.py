"""Human-readable and machine-readable renderings of a selection backtest.

Split out of :mod:`tests._test_selection_backtest` for the same reason
:mod:`tests._test_selection_report` is split out of the selector: nothing here
feeds a decision the harness makes, it only decides how the numbers read.

Two rendering choices are load-bearing rather than cosmetic:

* **Skipped commits are itemised, never summed away.** A recall figure over 12
  commits and a recall figure over 40 are different claims, and the difference
  is invisible unless the report says how many commits could not contribute and
  why.
* **The contexts arm is labelled as tautological.** It is 1.0 by construction —
  the selector unions in the same coverage query the ground truth comes from —
  and a reader who takes it for independent corroboration has been misled by
  the report, not by the harness.
"""

from __future__ import annotations

from statistics import median
from typing import Any

from tests._test_selection_backtest import (
    ANCESTOR,
    CLOSURE_ARM,
    DESCENDANT,
    SKIP_EXPLANATIONS,
    UNION_ARM,
    ArmResult,
    BacktestReport,
    CommitReplay,
)


DIRECTION_LABELS = {
    ANCESTOR: "baseline is an ancestor (faithful replay)",
    DESCENDANT: "baseline is a descendant (approximate: ground truth is widened)",
}


def percentile(values: list[float], fraction: float) -> float:
    """The nearest-rank percentile of ``values``.

    Nearest-rank rather than interpolated: these samples are small enough that
    an interpolated p90 would report a recall no commit actually had.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * len(ordered)) - 1))
    return ordered[index]


def _arms(report: BacktestReport, name: str) -> list[ArmResult]:
    return [replay.arm(name) for replay in report.replays]


def arm_statistics(report: BacktestReport, name: str) -> dict[str, Any]:
    """Recall, blind-spot, and selection-size figures for one arm."""
    arms = _arms(report, name)
    if not arms:
        return {"arm": name, "commits": 0}
    recalls = [arm.recall for arm in arms]
    blind = [arm for arm in arms if arm.missed]
    sizes = [
        len(arm.selected) / replay.universe_count
        for arm, replay in zip(arms, report.replays, strict=True)
        if not arm.escalated and replay.universe_count
    ]
    return {
        "arm": name,
        "commits": len(arms),
        "recall_mean": sum(recalls) / len(recalls),
        "recall_median": median(recalls),
        "recall_p10": percentile(recalls, 0.10),
        "recall_worst": min(recalls),
        "perfect_commits": sum(1 for value in recalls if value >= 1.0),
        "blind_spot_commits": len(blind),
        "missed_total": sum(len(arm.missed) for arm in blind),
        "missed_worst": max((len(arm.missed) for arm in blind), default=0),
        "escalated_commits": sum(1 for arm in arms if arm.escalated),
        "selected_share_median": median(sizes) if sizes else 0.0,
        "selected_share_p90": percentile(sizes, 0.90),
    }


def backtest_payload(report: BacktestReport) -> dict[str, Any]:
    return {
        "baseline": None if report.baseline is None else report.baseline.sha,
        "limit": report.limit,
        "commits_examined": report.examined,
        "commits_measured": len(report.replays),
        "commits_skipped": len(report.skipped),
        "skip_counts": report.skip_counts(),
        "direction_counts": report.direction_counts(),
        "arms": [
            arm_statistics(report, CLOSURE_ARM),
            arm_statistics(report, UNION_ARM),
        ],
        "commits": [_commit_payload(replay) for replay in report.replays],
        "executed": report.executed,
        "probes": [
            {
                "commit": probe.sha,
                "missed": list(probe.missed),
                "returncode": probe.returncode,
                "summary": probe.summary,
            }
            for probe in report.probes
        ],
    }


def _commit_payload(replay: CommitReplay) -> dict[str, Any]:
    return {
        "commit": replay.sha,
        "subject": replay.subject,
        "direction": replay.direction,
        "changed_files": len(replay.changed_files),
        "ground_truth": len(replay.ground_truth),
        "universe": replay.universe_count,
        "arms": {
            arm.name: {
                "selected": len(arm.selected),
                "escalated": arm.escalated,
                "recall": arm.recall,
                "missed": list(arm.missed),
                "rules": list(arm.rules),
            }
            for arm in (replay.closure, replay.union)
        },
    }


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_report(report: BacktestReport, *, sample: int = 10) -> list[str]:
    lines: list[str] = []
    if report.baseline is None:
        lines.append(
            "no coverage-contexts baseline cached: nothing to measure recall "
            "against. Run `just refresh-contexts-baseline` first."
        )
        return lines

    lines.extend(_render_header(report))
    lines.append("")
    lines.extend(_render_arm(report, CLOSURE_ARM))
    lines.append("")
    lines.extend(_render_arm(report, UNION_ARM))
    if report.replays:
        lines.append("")
        lines.extend(_render_worst(report, sample=sample))
    if report.executed:
        lines.append("")
        lines.extend(_render_probes(report))
    return lines


def _render_header(report: BacktestReport) -> list[str]:
    assert report.baseline is not None
    lines = [
        f"baseline: {report.baseline.sha[:12]} ({report.baseline.path})",
        f"commits examined: {report.examined} (--limit {report.limit})",
        f"commits with usable ground truth: {len(report.replays)}",
    ]
    for direction, count in report.direction_counts().items():
        label = DIRECTION_LABELS.get(direction, direction)
        lines.append(f"  {count:>4}  {label}")
    lines.append(f"commits skipped: {len(report.skipped)}")
    for reason, count in report.skip_counts().items():
        explanation = SKIP_EXPLANATIONS.get(reason, "")
        lines.append(f"  {count:>4}  {reason} — {explanation}")
    return lines


def _render_arm(report: BacktestReport, name: str) -> list[str]:
    stats = arm_statistics(report, name)
    heading = {
        CLOSURE_ARM: (
            "closure-only — what a workspace with no cached baseline actually gets"
        ),
        UNION_ARM: (
            "closure+contexts — 1.0 by construction; the gap above is the exposure"
        ),
    }[name]
    lines = [heading]
    if not stats["commits"]:
        lines.append("  no commits measured")
        return lines
    lines.append(
        f"  recall: median {_percent(stats['recall_median'])}"
        f"  mean {_percent(stats['recall_mean'])}"
        f"  p10 {_percent(stats['recall_p10'])}"
        f"  worst {_percent(stats['recall_worst'])}"
    )
    lines.append(
        f"  perfect recall on {stats['perfect_commits']}/{stats['commits']} "
        f"commits ({stats['escalated_commits']} of them by escalation)"
    )
    lines.append(
        f"  blind spots: {stats['blind_spot_commits']} commit(s), "
        f"{stats['missed_total']} missed test file(s), "
        f"worst single commit {stats['missed_worst']}"
    )
    lines.append(
        f"  selection size: median {_percent(stats['selected_share_median'])} "
        f"of the suite, p90 {_percent(stats['selected_share_p90'])}"
    )
    return lines


def _render_worst(report: BacktestReport, *, sample: int) -> list[str]:
    ranked = sorted(report.replays, key=lambda replay: replay.closure.recall)[:sample]
    lines = [f"worst closure-only commits (up to {sample}):"]
    for replay in ranked:
        arm = replay.closure
        lines.append(
            f"  {replay.sha[:12]}  recall {_percent(arm.recall):>6}  "
            f"missed {len(arm.missed):>3}/{len(replay.ground_truth):<3}  "
            f"selected {len(arm.selected):>4}  {replay.subject[:56]}"
        )
    return lines


def _render_probes(report: BacktestReport) -> list[str]:
    lines = [
        "--execute probes (a missed test file is only a false negative if it fails)",
        "  caveat: the historical tests run against today's installed "
        "`sase_core_rs`; only `src/` is replayed.",
    ]
    if not report.probes:
        lines.append("  no commit had a closure-only blind spot to execute")
        return lines
    for probe in report.probes:
        verdict = "no failure" if probe.returncode == 0 else "FAILED"
        lines.append(
            f"  {probe.sha[:12]}  {len(probe.missed)} file(s)  "
            f"{verdict} (exit {probe.returncode}) — {probe.summary}"
        )
    return lines
