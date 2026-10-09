"""``sase autonomy log`` — read the host autonomy decision log.

Entries are newest first, rendered with the core decision sentence. The
``--since`` DATE grammar is the existing ``sase.vcs_log.dates`` one; the
token passes straight to the core log reader, which accepts the same
forms.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from rich.console import Console
from rich.text import Text

from sase.autonomy.record import COVERAGE_LINE, decision_sentence, read_decision_log

#: Gate kinds the log can filter on. Mirrors the service's auto-allowable
#: kinds plus the privileged kinds that always ask (they never log rows,
#: so filtering on one is an honest empty result).
LOG_KIND_CHOICES = ("plan", "epic_plan", "question")

#: Decision outcomes the log can filter on.
LOG_OUTCOME_CHOICES = ("auto", "ask")


def handle_autonomy_log(args: argparse.Namespace) -> int:
    """Run ``sase autonomy log``."""
    as_json = bool(getattr(args, "json", False))
    query: dict[str, Any] = {"limit": 50}
    agent = getattr(args, "agent", None)
    if agent is not None:
        query["agent"] = str(agent)
    kind = getattr(args, "kind", None)
    if kind is not None:
        query["gate_kind"] = str(kind)
    since = getattr(args, "since", None)
    if since is not None:
        query["since"] = str(since)
    outcome = getattr(args, "outcome", None)
    if outcome is not None:
        query["outcome"] = str(outcome)
    try:
        entries = read_decision_log(query)
    except Exception as exc:
        print(f"sase autonomy log: {exc}", file=sys.stderr)
        sys.exit(1)
    if as_json:
        print(json.dumps({"entries": entries, "coverage": COVERAGE_LINE}))
        return 0
    console = Console()
    if not entries:
        console.print(Text("No autonomy decisions logged yet.", style="dim"))
        return 0
    for entry in entries:
        console.print(_entry_line(entry), soft_wrap=True)
    console.print(Text(COVERAGE_LINE, style="dim"), soft_wrap=True)
    return 0


def _entry_line(entry: dict[str, Any]) -> Text:
    line = Text("  ")
    decision = entry.get("decision")
    gate_kind = str(entry.get("gate_kind", ""))
    sentence = (
        decision_sentence(decision, gate_kind) if isinstance(decision, dict) else None
    )
    line.append(sentence or _entry_fallback(entry))
    agent = entry.get("agent")
    at = entry.get("at")
    suffix = " ".join(part for part in (str(agent or ""), str(at or "")) if part)
    if suffix:
        line.append(f" · {suffix}", style="dim")
    return line


def _entry_fallback(entry: dict[str, Any]) -> str:
    decision = entry.get("decision")
    if isinstance(decision, dict):
        outcome = decision.get("outcome", "ask")
        rule = decision.get("rule", "?")
        return f"{outcome} · {rule}"
    return "decision"


__all__ = ["LOG_KIND_CHOICES", "LOG_OUTCOME_CHOICES", "handle_autonomy_log"]
