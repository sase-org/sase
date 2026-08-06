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

    return f"scoped: {selection_part}; contexts baseline {baseline_status}"


def explain_lines(selection: Selection, *, sample: int = 20) -> list[str]:
    """Render why the selection looks the way it does."""
    lines = [summary_line(selection)]
    lines.append(f"rules fired: {', '.join(selection.rules) or 'none'}")
    lines.append(context_line(selection.contexts))
    if selection.escalated:
        lines.append("no per-file selection: the run escalates to the full suite")
        return lines
    lines.append(f"selected files (showing up to {sample}):")
    for path in selection.selected[:sample]:
        seed, hop = selection.explanations.get(path, ("?", -1))
        lines.append(f"  {path}  <- seed {seed} at hop {hop}")
    if len(selection.selected) > sample:
        lines.append(f"  ... and {len(selection.selected) - sample} more")
    return lines
