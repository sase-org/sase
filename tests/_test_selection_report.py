"""Human-readable renderings of a selection.

Split out of :mod:`tests._test_selection` so neither half grows past the
repository's per-file line budget. Nothing here feeds a decision: these lines
exist so an agent reading ``just check`` output, or a human running
``tools/select_tests --explain``, can see why the run looks the way it does.
"""

from __future__ import annotations

from typing import Any

from tests._test_selection import Selection
from tests._test_selection_contexts import ContextSelection, contexts_consulted
from tests._test_selection_gear import ScopedGear
from tests._test_selection_timings import REASON_ESCALATED


def summary_line(selection: Selection) -> str:
    rules = ", ".join(selection.rules) or "none"
    if selection.escalated:
        return (
            f"test selection escalated to the full suite "
            f"(rules: {rules}); {selection.universe_count} test files in scope"
        )
    return (
        f"selected {len(selection.selected)} of {selection.universe_count} "
        f"test files (rules: {rules})"
    )


def context_line(contexts: ContextSelection) -> str:
    """One line describing what per-test coverage contributed, if anything."""
    if not contexts.consulted:
        return (
            "coverage contexts: not consulted — the run escalates to the full "
            "suite, so ground truth had nothing to add"
        )
    if contexts.baseline_sha is None:
        return (
            "coverage contexts: no baseline cached "
            "(run `just refresh-contexts-baseline`); static closure only"
        )
    freshness = "stale" if contexts.stale else "fresh"
    distance = (
        "unknown" if contexts.distance is None else f"{contexts.distance} commits"
    )
    return (
        f"coverage contexts: baseline {contexts.baseline_sha[:12]} ({freshness}, "
        f"{distance} behind HEAD) matched {len(contexts.matched_files)} changed "
        f"file(s) and contributed {len(contexts.selected)} test file(s)"
    )


def budget_line(selection: Selection) -> str:
    """One line describing the serial-runtime budget and what it decided.

    Printed whether or not `RULE_SERIAL_BUDGET_EXCEEDED` fired: an agent
    looking at a 400-file selection that stayed scoped should be able to read
    "estimated 180s, budget 232s" and understand why, without re-deriving it
    from the manifest.
    """
    budget = selection.options.max_serial_seconds
    timings = selection.timings
    if timings.reason == REASON_ESCALATED:
        return (
            "serial budget: not evaluated — a change-set rule escalated before "
            "there was a selection to cost"
        )
    if not timings.available or timings.seconds is None:
        return (
            f"serial budget: no estimate ({timings.reason}; "
            f"{timings.covered_count}/{timings.covered_count + timings.missing_count} "
            f"files covered, floor {timings.min_coverage:.0%}) — "
            f"the {selection.options.max_ratio:.0%} file-count ratio decides instead"
        )
    verdict = "over" if timings.seconds > budget else "within"
    return (
        f"serial budget: estimated {timings.seconds:.0f}s against a {budget:.0f}s "
        f"budget ({verdict}; {timings.coverage:.0%} of the selection covered by "
        f"the timing table)"
    )


def gear_line(gear: ScopedGear) -> str:
    """One line describing what the middle gear was granted, or why not.

    Printed only on the runs that reached the gear at all — a selection the
    serial budget rejected — so it always has something to say.
    """
    if gear.granted:
        return (
            f"middle gear: running the over-budget selection at "
            f"{gear.worker_count} worker(s), leased from the suite gate "
            f"(ceiling {gear.ceiling})"
        )
    return (
        f"middle gear: no bounded lease ({gear.reason}); escalating rather "
        "than queueing for one"
    )


def manifest_summary_line(manifest: dict[str, Any]) -> str:
    """The scoped lane's one-line summary, rebuilt from its persisted manifest.

    `summary_line`/`context_line` render a live `Selection`; `run_silent`
    discards a scoped run's stdout+stderr on success before either can reach
    the terminal. This renders the same facts from the JSON manifest
    `tools/run_pytest` already persists, so a `check` step that runs after
    `run_silent` returns — outside its captured region — can still show what
    a passing scoped run decided.
    """
    escalated = bool(manifest.get("escalated"))
    rules = ", ".join(manifest.get("rules_fired") or ()) or "none"
    universe_count = int(manifest.get("universe_count") or 0)
    contexts = manifest.get("contexts") or {}
    baseline_sha = contexts.get("baseline")
    if not contexts_consulted(contexts, escalated=escalated):
        baseline_status = "not consulted"
    elif baseline_sha is None:
        baseline_status = "missing"
    else:
        baseline_status = "stale" if contexts.get("stale") else "present"

    if escalated:
        selection_part = f"escalated to the full suite (rules: {rules})"
    else:
        selected_count = int(manifest.get("selected_count") or 0)
        share = 0.0 if universe_count == 0 else 100 * selected_count / universe_count
        selection_part = (
            f"selected {selected_count} of {universe_count} test files "
            f"({share:.1f}%; rules: {rules})"
        )

    return (
        f"scoped: {selection_part}; contexts baseline {baseline_status}"
        f"{_manifest_budget_clause(manifest)}"
        f"{_manifest_gear_clause(manifest)}"
    )


def _manifest_gear_clause(manifest: dict[str, Any]) -> str:
    """`; gear 4 workers` or `; gear refused (tokens-unavailable)`.

    Silent on the runs that never reached the gear, which is most of them. On
    the runs that did, it is the difference between "escalated" and "ran the
    same selection four-wide", and that is not something to leave to whoever
    later reads the manifest.
    """
    gear = manifest.get("gear")
    if not isinstance(gear, dict):
        return ""
    if gear.get("granted"):
        return f"; gear {gear.get('worker_count')} workers"
    return f"; gear refused ({gear.get('reason') or 'unknown'})"


def _manifest_budget_clause(manifest: dict[str, Any]) -> str:
    """`; est 118s/232s`, when the manifest costed a selection at all.

    Compact because it rides on the one line an agent sees after a passing
    scoped run, and silent when there was no estimate: a run the ratio decided
    has no budget comparison to report, and inventing one would be worse than
    saying nothing.
    """
    timings = manifest.get("timings") or {}
    estimate = timings.get("estimated_serial_seconds")
    budget = manifest.get("max_serial_seconds")
    if estimate is None or budget is None:
        return ""
    return f"; est {float(estimate):.0f}s/{float(budget):.0f}s"


def explain_lines(selection: Selection, *, sample: int = 20) -> list[str]:
    """Render why the selection looks the way it does."""
    lines = [summary_line(selection)]
    lines.append(f"rules fired: {', '.join(selection.rules) or 'none'}")
    changed_inputs = selection.manifest.get("baseline", {}).get(
        "environment_changed_inputs"
    )
    if changed_inputs:
        lines.append(f"environment inputs changed: {', '.join(changed_inputs)}")
    lines.append(context_line(selection.contexts))
    lines.append(budget_line(selection))
    if selection.escalated:
        if selection.gear_candidate:
            # `--explain` runs the selector without running anything, so this
            # is the most it can honestly say: whether the run *would* be
            # offered to the gear, not what the gate would answer.
            lines.append(
                f"the middle gear would be offered these "
                f"{len(selection.gear_candidate)} file(s) at a bounded, "
                "non-blocking lease before the run escalates"
            )
        else:
            lines.append("no per-file selection: the run escalates to the full suite")
        return lines
    lines.append(f"selected files (showing up to {sample}):")
    for path in selection.selected[:sample]:
        seed, hop = selection.explanations.get(path, ("?", -1))
        lines.append(f"  {path}  <- seed {seed} at hop {hop}")
    if len(selection.selected) > sample:
        lines.append(f"  ... and {len(selection.selected) - sample} more")
    return lines
