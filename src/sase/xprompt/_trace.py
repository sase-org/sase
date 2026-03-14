"""Expansion trace for xprompt reference resolution."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field


@dataclass
class ExpansionRecord:
    """Record of a single xprompt expansion."""

    iteration: int
    name: str
    source_path: str | None
    positional_args: list[str]
    named_args: dict[str, str]
    expanded_text: str


@dataclass
class ExpansionTrace:
    """Accumulated trace of all xprompt expansions."""

    records: list[ExpansionRecord] = field(default_factory=list)
    total_iterations: int = 0

    def add(
        self,
        *,
        iteration: int,
        name: str,
        source_path: str | None,
        positional_args: list[str],
        named_args: dict[str, str],
        expanded_text: str,
    ) -> None:
        self.records.append(
            ExpansionRecord(
                iteration=iteration,
                name=name,
                source_path=source_path,
                positional_args=positional_args,
                named_args=named_args,
                expanded_text=expanded_text,
            )
        )


def _truncate(text: str, max_len: int = 120) -> str:
    """Truncate text for display, preserving newline indication."""
    text = text.replace("\n", "\\n")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _format_args(positional: list[str], named: dict[str, str]) -> str:
    parts: list[str] = []
    for arg in positional:
        parts.append(_truncate(arg, 60))
    for k, v in named.items():
        parts.append(f"{k}={_truncate(v, 50)}")
    return ", ".join(parts) if parts else "(none)"


def format_trace(trace: ExpansionTrace) -> str:
    """Format an expansion trace for human-readable display.

    Returns a multi-line string showing each expansion step grouped by
    iteration, with source file, arguments, and truncated output.
    """
    if not trace.records:
        return "No xprompt references were expanded."

    lines: list[str] = []
    lines.append(
        f"Expansion trace: {len(trace.records)} reference(s) "
        f"resolved in {trace.total_iterations} iteration(s)"
    )
    lines.append("")

    current_iter = -1
    for rec in trace.records:
        if rec.iteration != current_iter:
            current_iter = rec.iteration
            lines.append(f"--- iteration {current_iter} ---")

        source = rec.source_path or "unknown"
        lines.append(f"  #{rec.name}  ({source})")
        lines.append(f"    args: {_format_args(rec.positional_args, rec.named_args)}")
        lines.append(f"    => {_truncate(rec.expanded_text)}")

    return "\n".join(lines)


def format_circular_ref_diagnostic(trace: ExpansionTrace, max_iter: int) -> str:
    """Format a diagnostic message for circular reference detection.

    Analyzes the expansion history to identify which xprompt names
    recur across iterations, indicating a cycle.
    """
    # Collect expansion names per iteration
    iter_names: dict[int, list[str]] = {}
    for rec in trace.records:
        iter_names.setdefault(rec.iteration, []).append(rec.name)

    # Find names that recur across recent iterations (cycle members).
    # In an alternating cycle (#a → #b → #a), each iteration only
    # contains one of the names, so we look for names appearing in
    # at least 2 of the last 10 iterations.
    recent_iters = sorted(iter_names.keys())[-10:]
    if len(recent_iters) < 2:
        return (
            f"Maximum xprompt expansion depth ({max_iter}) exceeded. "
            "Check for circular references."
        )

    from collections import Counter

    name_counts: Counter[str] = Counter()
    for it in recent_iters:
        for name in iter_names[it]:
            name_counts[name] += 1
    cycle_candidates = {name for name, count in name_counts.items() if count >= 2}

    lines: list[str] = [
        f"Maximum xprompt expansion depth ({max_iter}) exceeded.",
    ]

    if cycle_candidates:
        cycle_str = ", ".join(f"#{n}" for n in sorted(cycle_candidates))
        lines.append(f"Likely circular reference involving: {cycle_str}")
        lines.append("")
        lines.append("Last few iterations:")
        for it in recent_iters[-5:]:
            names = ", ".join(f"#{n}" for n in iter_names[it])
            lines.append(f"  iteration {it}: expanded {names}")
    else:
        lines.append("Check for circular references.")

    return "\n".join(lines)


def print_trace(trace: ExpansionTrace) -> None:
    """Print the expansion trace to stderr."""
    print(format_trace(trace), file=sys.stderr)
