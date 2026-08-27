"""Compose the gate-shell follow-up agent's prompt after a gate settles.

Pure text formatting -- no I/O -- so the prompt shape is covered by golden
tests without needing a real gate bundle or spawned process. Mirrors
:mod:`sase.monitor.followup_prompt`'s security architecture: the routing
prefix (``#fork:``, ``%model:``, ``%effort:``) is deliberately live so the
follow-up inherits conversation and model routing, while the decision
metadata, reviewer note, command results, and output tail are enclosed in one
disabled xprompt region so none of it can be interpreted as a directive.
Only ``## Your next action`` -- the author-declared ``prompt`` -- is meant to
read as an instruction, and even that stays inside the disabled region
because it is untrusted relative to the model: the region hides directive
syntax from the xprompt processor, it does not grant the text authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sase.shells.prompt import (
    fenced_block,
    format_shell_duration,
    shell_routing_prefix,
    untrusted_output_section,
    widen_fence,
)
from sase.xprompt._disabled_regions import wrap_disabled_region

#: Per-option and total bounds on the JSON embedded in ``## Results``. These
#: bound the *prompt* only -- the full result stays on disk in
#: ``response.json``.
GATE_RESULT_MAX_CHARS = 4000
GATE_RESULTS_MAX_CHARS = 16000


@dataclass(frozen=True, slots=True)
class GateOptionOutcome:
    """One selected option's command outcome, for the ``## Results`` section."""

    option_id: str
    label: str
    command: str
    result: object


def format_gate_outcome_line(
    *,
    gate_state: str,
    selected_labels: tuple[str, ...],
    gate_timeout_seconds: float,
    reason: str | None,
) -> str:
    """Render the ``**Outcome**`` table cell for one settled gate state."""
    if gate_state in ("answered", "completed"):
        return "ANSWERED — " + ", ".join(selected_labels)
    if gate_state == "timeout":
        budget = format_shell_duration(gate_timeout_seconds)
        return f"TIMED OUT — no answer after {budget}"
    if gate_state == "stopped":
        return f"STOPPED — {reason or 'cancelled'}"
    if gate_state == "failed":
        return f"FAILED — {reason or 'unknown error'}"
    if gate_state == "lost":
        return f"LOST — {reason or 'unknown error'}"
    return gate_state.upper()


def compose_gate_followup_prompt(
    *,
    fork_target: str | None,
    model: str | None,
    reasoning_effort: str | None,
    next_model: str | None,
    answered: bool,
    title: str,
    gate_ref: str,
    outcome_line: str,
    answered_via: str | None = None,
    opened_at: str | None = None,
    answered_at: str | None = None,
    options: tuple[GateOptionOutcome, ...] = (),
    reviewer_note: str | None = None,
    output: tuple[str, ...] = ("results",),
    output_text: str = "",
    tail_lines: int = 200,
    gate_log_path: str | None = None,
    workspace_degraded_reason: str | None = None,
    next_action: str,
) -> str:
    """Compose the gate-shell follow-up agent's full prompt.

    ``answered`` selects the ``# Gate answered`` / ``# Gate unanswered``
    heading. ``output`` controls which of the results/tail/log-pointer
    sections render, in that fixed order; ``"none"`` anywhere in the tuple
    suppresses all three. An unanswered gate has no completed commands, so
    the ``## Results`` section is omitted entirely rather than emitted empty,
    regardless of ``output``.
    """
    heading = "# Gate answered" if answered else "# Gate unanswered"
    rows: list[tuple[str, str]] = [("Outcome", outcome_line)]
    if answered_via is not None:
        rows.append(("Answered via", answered_via))
    if opened_at is not None:
        rows.append(("Opened", opened_at))
    if answered_at is not None:
        rows.append(("Answered", answered_at))
    if options:
        rows.append(("Commands", f"{len(options)} of {len(options)} completed"))
    rows.append(("Gate", gate_ref))
    table = "\n".join(f"| **{label}** | {value} |" for label, value in rows)

    sections = [
        heading,
        "",
        f"**Decision:** {title}",
        "",
        "| | |",
        "| --- | --- |",
        table,
        "",
    ]
    if reviewer_note:
        sections.extend(fenced_block("Reviewer note", reviewer_note))

    suppress_output = "none" in output
    if options and "results" in output and not suppress_output:
        sections.extend(["## Results", ""])
        for option, body in _bounded_results(options):
            sections.append(f"### {option.option_id} — `{option.command}`")
            sections.append("")
            fence = widen_fence(body)
            sections.extend([f"{fence}json", body, fence, ""])
    if "tail" in output and not suppress_output:
        sections.extend(
            untrusted_output_section(
                f"## Last {tail_lines} lines of output", output_text, tail_lines
            )
        )
    if "file" in output and not suppress_output and gate_log_path:
        sections.extend(["## Gate log", "", f"`{gate_log_path}`", ""])
    if workspace_degraded_reason:
        sections.extend(["## Follow-up workspace", "", workspace_degraded_reason, ""])
    sections.extend(["## Your next action", "", next_action])

    body = wrap_disabled_region("\n".join(sections))
    prefix = shell_routing_prefix(fork_target, model, reasoning_effort, next_model)
    return f"{prefix}\n{body}" if prefix else body


def _bounded_results(
    options: tuple[GateOptionOutcome, ...],
) -> list[tuple[GateOptionOutcome, str]]:
    """Render each option's result JSON, bounded per-option and in total."""
    rendered: list[tuple[GateOptionOutcome, str]] = []
    total = 0
    for option in options:
        body = _bounded_json(option.result, GATE_RESULT_MAX_CHARS)
        remaining = GATE_RESULTS_MAX_CHARS - total
        if remaining <= 0:
            body = f"… {len(body)} characters elided: total results exceed the bound …"
        elif len(body) > remaining:
            elided = len(body) - remaining
            body = f"{body[:remaining]}\n… {elided} characters elided …"
        total += len(body)
        rendered.append((option, body))
    return rendered


def _bounded_json(value: object, max_chars: int) -> str:
    text = json.dumps(value, indent=2, sort_keys=True)
    if len(text) <= max_chars:
        return text
    elided = len(text) - max_chars
    return f"{text[:max_chars]}\n… {elided} characters elided …"


__all__ = [
    "GATE_RESULT_MAX_CHARS",
    "GATE_RESULTS_MAX_CHARS",
    "GateOptionOutcome",
    "compose_gate_followup_prompt",
    "format_gate_outcome_line",
]
