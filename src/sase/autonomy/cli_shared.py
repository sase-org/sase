"""Shared render helpers for the ``%auto`` inspect surfaces.

This module is a leaf: it imports only the autonomy adapter, the core
bindings through it, and Rich. ``sase agent show`` and ``sase gate show``
import from here so every surface renders one record the same way without
creating import cycles.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.text import Text

from sase.autonomy.record import (
    COVERAGE_LINE,
    decision_sentence,
    evaluate,
    summarize_record,
)

#: Gate kinds ``explain`` predicts, with the standard option IDs and
#: executable capabilities of each kind's automatic selection. This mirrors
#: the gate service's kinds (``sase.autonomy.gates``): ``plan`` approves and
#: archives, ``epic_plan`` approves, and ``question`` takes the first
#: option. The explain-equals-runtime property test pins that these stay
#: identical to what gate creation decides.
EXPLAIN_STANDARD_REQUESTS: dict[str, dict[str, list[str]]] = {
    "plan": {
        "option_ids": ["approve", "commit"],
        "capabilities": ["approve_archive"],
    },
    "epic_plan": {
        "option_ids": ["approve"],
        "capabilities": ["approve"],
    },
    "question": {
        "option_ids": ["submit"],
        "capabilities": ["first"],
    },
}

#: Display order for the per-kind prediction rows.
EXPLAIN_KIND_ORDER = ("plan", "epic_plan", "question")


def predictions_for_record(
    record: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Evaluate *record* against every explainable gate kind through core.

    A ``None`` record is Manual and asks everywhere. Each prediction is
    normalized through the gate service's policy block, so it equals the
    block gate creation would durably record (a manual decision is stored
    with rule ``manual``), which is what the explain-equals-runtime
    property test asserts.
    """
    from sase.autonomy.gates import policy_block_for_decision

    predictions: dict[str, dict[str, Any]] = {}
    for kind in EXPLAIN_KIND_ORDER:
        standard = EXPLAIN_STANDARD_REQUESTS[kind]
        decision = evaluate(
            record,
            kind,
            standard["option_ids"],
            standard["capabilities"],
        )
        predictions[kind] = policy_block_for_decision(decision)
    return predictions


def summary_text(record: Mapping[str, Any]) -> str:
    """Return the one-line core summary for *record*."""
    summary = summarize_record(record)
    if summary is not None:
        sentence = summary.get("sentence")
        if isinstance(sentence, str) and sentence:
            return sentence
    profile = record.get("profile", "manual")
    return f"Autonomy profile: {profile}."


def cells_for_record(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the per-kind ``[{kind, glyph, effect, rule}]`` cells."""
    summary = summarize_record(record)
    if summary is not None:
        cells = summary.get("cells")
        if isinstance(cells, list):
            return [dict(cell) for cell in cells if isinstance(cell, dict)]
    return []


def _record_source(record: Mapping[str, Any]) -> str:
    """Return the record's source (``prompt``/``tui``/``cli``/...)."""
    source = record.get("source")
    return str(source) if source else "unknown"


def autonomy_lines(record: Mapping[str, Any]) -> Text:
    """Render the shared Autonomy section body for one record."""
    body = Text()
    body.append(summary_text(record))
    body.append("\n")
    for cell in cells_for_record(record):
        line = Text("\n  ")
        glyph = cell.get("glyph")
        if glyph:
            line.append(f"{glyph} ", style="bold")
        line.append(f"{cell.get('kind', '?')}: ", style="bold")
        line.append(str(cell.get("effect", "")))
        rule = cell.get("rule")
        if rule:
            line.append(f" · rule {rule}", style="dim")
        body.append(line)
    body.append(f"\n\nSource: {_record_source(record)}", style="dim")
    revision = record.get("revision")
    if revision is not None:
        body.append(f" · revision {revision}", style="dim")
    body.append(f"\n{COVERAGE_LINE}", style="dim")
    return body


def policy_line_text(policy: Mapping[str, Any], gate_kind: str) -> Text:
    """Render one gate's ``Policy:`` line from its durable policy block."""
    sentence = decision_sentence(policy, gate_kind)
    line = Text("Policy: ", style="dim")
    if sentence:
        line.append(sentence)
    else:
        line.append(_policy_fallback(policy))
    return line


def _policy_fallback(policy: Mapping[str, Any]) -> str:
    profile = policy.get("profile", "?")
    outcome = policy.get("outcome", "ask")
    rule = policy.get("rule", "?")
    return f"{profile} · {outcome} · {rule}"


__all__ = [
    "EXPLAIN_KIND_ORDER",
    "EXPLAIN_STANDARD_REQUESTS",
    "autonomy_lines",
    "cells_for_record",
    "policy_line_text",
    "predictions_for_record",
    "summary_text",
]
