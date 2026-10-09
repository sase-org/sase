"""``sase autonomy explain`` — predict each decision exactly.

With an agent, this prints its live record's summary, the per-kind cells
with rule and source, the decisions so far from the host log, and the
coverage line. With ``-p``, it dry-runs a prompt's ``%auto`` through the
side-effect-free scan (``$(...)`` is never executed and is labeled as
unexpanded). With ``-g``, it prints the settled gate's deciding policy
block, which is the revision that decided it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from rich.console import Console
from rich.text import Text

from sase.autonomy.cli import read_gate_policy, resolve_agent_record
from sase.autonomy.cli_shared import (
    autonomy_lines,
    cells_for_record,
    predictions_for_record,
    summary_text,
)
from sase.autonomy.record import (
    COVERAGE_LINE,
    decision_sentence,
    read_decision_log,
    resolve_selection,
)

#: ``$(...)`` spans are dynamic: explain never executes them and labels
#: them as unexpanded instead.
_DYNAMIC_PATTERN = re.compile(r"\$\(")


def handle_autonomy_explain(args: argparse.Namespace) -> int:
    """Run ``sase autonomy explain``."""
    as_json = bool(getattr(args, "json", False))
    prompt = getattr(args, "prompt", None)
    gate = getattr(args, "gate", None)
    agent = getattr(args, "agent", None)
    if prompt is not None and gate is not None:
        print(
            "sase autonomy explain: --prompt and --gate cannot be combined",
            file=sys.stderr,
        )
        sys.exit(2)
    if prompt is not None:
        return _explain_prompt(str(prompt), as_json=as_json)
    if gate is not None:
        return _explain_gate(str(gate), as_json=as_json)
    if agent is None:
        print(
            "Usage: sase autonomy explain [AGENT] [-g/--gate ID] [-p/--prompt TEXT]",
            file=sys.stderr,
        )
        sys.exit(2)
    return _explain_agent(str(agent), as_json=as_json)


def _explain_agent(name: str, *, as_json: bool) -> int:
    resolved_name, _artifacts_dir, record = resolve_agent_record(name)
    predictions = predictions_for_record(record)
    entries = read_decision_log({"agent": resolved_name, "limit": 20})
    if as_json:
        print(json.dumps(_agent_payload(resolved_name, record, predictions, entries)))
        return 0
    console = Console()
    header = Text(f"Autonomy for {resolved_name}", style="bold")
    console.print(header, soft_wrap=True)
    console.print(_record_block(record), soft_wrap=True)
    console.print(Text("Predicted decisions", style="bold"), soft_wrap=True)
    for kind in ("plan", "epic_plan", "question"):
        console.print(_prediction_line(kind, predictions[kind]), soft_wrap=True)
    if entries:
        console.print(Text("Decisions so far", style="bold"), soft_wrap=True)
        for entry in entries:
            console.print(_log_line(entry), soft_wrap=True)
    else:
        console.print(Text("No autonomy decisions logged yet.", style="dim"))
    console.print(Text(COVERAGE_LINE, style="dim"), soft_wrap=True)
    return 0


def _agent_payload(
    name: str,
    record: dict[str, Any],
    predictions: dict[str, dict[str, Any]],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "agent": name,
        "record": {
            "profile": record.get("profile"),
            "selection": record.get("selection"),
            "source": record.get("source"),
            "revision": record.get("revision"),
            "digest": record.get("digest"),
        },
        "summary": summary_text(record),
        "cells": cells_for_record(record),
        "predictions": predictions,
        "decisions": entries,
        "coverage": COVERAGE_LINE,
    }


def _record_block(record: dict[str, Any]) -> Text:
    return autonomy_lines(record)


def _prediction_line(kind: str, decision: dict[str, Any]) -> Text:
    sentence = decision_sentence(decision, kind)
    line = Text(f"  {kind}: ", style="bold")
    line.append(sentence or _decision_fallback(decision))
    return line


def _decision_fallback(decision: dict[str, Any]) -> str:
    outcome = decision.get("outcome", "ask")
    rule = decision.get("rule", "?")
    return f"{outcome} · {rule}"


def _log_line(entry: dict[str, Any]) -> Text:
    line = Text("  ")
    decision = entry.get("decision")
    gate_kind = str(entry.get("gate_kind", ""))
    sentence = (
        decision_sentence(decision, gate_kind) if isinstance(decision, dict) else None
    )
    line.append(sentence or _decision_fallback(decision or {}))
    at = entry.get("at")
    gate_id = entry.get("gate_id")
    suffix = " ".join(part for part in (str(at or ""), str(gate_id or "")) if part)
    if suffix:
        line.append(f" · {suffix}", style="dim")
    return line


def _explain_prompt(prompt: str, *, as_json: bool) -> int:
    outcome = _dry_run_prompt(prompt)
    if as_json:
        print(json.dumps(outcome))
        return 0
    console = Console()
    if outcome["error"] is not None:
        console.print(Text(f"Invalid %auto: {outcome['error']}", style="bold red"))
        sys.exit(1)
    record = outcome["record"]
    assert record is not None
    console.print(Text(summary_text(record), style="bold"), soft_wrap=True)
    for kind in ("plan", "epic_plan", "question"):
        console.print(
            _prediction_line(kind, outcome["predictions"][kind]), soft_wrap=True
        )
    dynamic = outcome["dynamic_parts"]
    if dynamic:
        console.print(
            Text(
                f"{dynamic} dynamic $(...) part(s) left unexpanded.",
                style="dim",
            ),
            soft_wrap=True,
        )
    console.print(Text(COVERAGE_LINE, style="dim"), soft_wrap=True)
    return 0


def _dry_run_prompt(prompt: str) -> dict[str, Any]:
    """Resolve a prompt's ``%auto`` without side effects.

    Uses the side-effect-free scan, never executes ``$(...)``, and counts
    the dynamic parts left unexpanded. Returns ``{record, predictions,
    dynamic_parts, error}``; *error* carries the launch-exact message for
    an invalid spelling, with no record or predictions.
    """
    from sase.macro._directive_scan import scan_auto_directive
    from sase.macro.directives import extract_prompt_directives
    from sase.macro._exceptions import DirectiveError

    dynamic_parts = len(_DYNAMIC_PATTERN.findall(prompt))
    scan = scan_auto_directive(prompt)
    if scan is not None and scan.error is not None:
        return {
            "record": None,
            "predictions": {},
            "dynamic_parts": dynamic_parts,
            "error": scan.error,
        }
    try:
        _cleaned, directives = extract_prompt_directives(prompt)
    except DirectiveError as exc:
        return {
            "record": None,
            "predictions": {},
            "dynamic_parts": dynamic_parts,
            "error": str(exc),
        }
    # Mirror the launch path in `build_agent_meta` exactly: an enabled
    # argument wins, bare `%auto` is `""`, and anything else (absent,
    # `:manual`, `:off`) is `None`. A different mapping here would make
    # `explain -p` disagree with the runtime it predicts.
    if directives.auto_enabled and directives.auto_argument is not None:
        selection = directives.auto_argument
    elif directives.auto_enabled:
        selection = ""
    else:
        selection = None
    record = resolve_selection(selection, source="prompt", surface="explain")
    return {
        "record": record,
        "predictions": predictions_for_record(record),
        "dynamic_parts": dynamic_parts,
        "error": None,
    }


def _explain_gate(gate_ref: str, *, as_json: bool) -> int:
    kind, request_id, policy = read_gate_policy(gate_ref)
    sentence = decision_sentence(policy, kind)
    if as_json:
        print(
            json.dumps(
                {
                    "gate_kind": kind,
                    "request_id": request_id,
                    "policy": policy,
                    "sentence": sentence,
                    "coverage": COVERAGE_LINE,
                }
            )
        )
        return 0
    console = Console()
    header = Text(f"Autonomy for gate {kind}/{request_id}", style="bold")
    console.print(header, soft_wrap=True)
    console.print(Text(sentence or _decision_fallback(policy)), soft_wrap=True)
    revision = policy.get("revision")
    if revision is not None:
        console.print(Text(f"Decided at record revision {revision}.", style="dim"))
    console.print(Text(COVERAGE_LINE, style="dim"), soft_wrap=True)
    return 0


__all__ = ["handle_autonomy_explain"]
