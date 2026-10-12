"""Shared harness for the split deck-cards tests.

Public helpers used by more than one split module live here under public
names so no new module imports a ``_``-prefixed name from another new
module.
"""

from __future__ import annotations

from typing import Any

from sase.core.tool_run import ToolRunBrief, ToolRunVerdictSummary

__all__ = [
    "make_brief",
    "make_verdict",
]


def make_verdict(bucket: str, **counts: Any) -> ToolRunVerdictSummary:
    return ToolRunVerdictSummary(
        bucket=bucket,
        new=int(counts.get("new", 0)),
        known=int(counts.get("known", 0)),
        unknown=int(counts.get("unknown", 0)),
    )


def make_brief(
    run_id: str,
    label: str = "check",
    bucket: str = "pass",
    *,
    state: str = "succeeded",
    created_ts: int = 1000,
    settled_ts: int | None = 1500,
    duration_ms: int | None = 252000,
    typical_ms: int | None = 253000,
    agent: str | None = "0t9--code",
    owner_kind: str | None = None,
    owner_id: str | None = None,
    terminal_cause: str | None = None,
    **counts: Any,
) -> ToolRunBrief:
    return ToolRunBrief(
        run_id=run_id,
        label=label,
        state=state,
        created_ts=created_ts,
        verdict=make_verdict(bucket, **counts),
        tool_name="check",
        agent=agent,
        owner_kind=owner_kind,
        owner_id=owner_id,
        terminal_cause=terminal_cause,
        settled_ts=settled_ts,
        duration_ms=duration_ms,
        typical_ms=typical_ms,
    )
