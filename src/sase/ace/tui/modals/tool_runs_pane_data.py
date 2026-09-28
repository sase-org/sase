"""Pure helpers for the Admin Center Tools pane (epic sase-1bt, admin-tools-pane).

All functions here are pure: filtering, ordering, and formatting over
in-memory ToolRun briefs, glance rows, failures groups, and catalog
entries. No SQLite, store stats, subprocesses, or reconciliation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolRunFocusTarget:
    """Deep-link target for one tool run inside Admin Center Tools."""

    run_id: str


@dataclass(frozen=True)
class _ToolRunsFilter:
    """Parsed ``/`` filter: scoped tokens plus free text."""

    tool: str | None = None
    state: str | None = None
    agent: str | None = None
    verdict: str | None = None
    text: str = ""


def _parse_tool_runs_filter(query: str) -> _ToolRunsFilter:
    """Parse a Runs ``/`` filter into scoped tokens and free text."""

    tool: str | None = None
    state: str | None = None
    agent: str | None = None
    verdict: str | None = None
    rest: list[str] = []
    for token in str(query or "").split():
        key, sep, value = token.partition(":")
        if sep and value:
            lowered = key.casefold()
            if lowered == "tool" and tool is None:
                tool = value.casefold()
                continue
            if lowered == "state" and state is None:
                state = value.casefold()
                continue
            if lowered == "agent" and agent is None:
                agent = value.casefold()
                continue
            if lowered == "verdict" and verdict is None:
                verdict = value.casefold()
                continue
        rest.append(token)
    return _ToolRunsFilter(
        tool=tool,
        state=state,
        agent=agent,
        verdict=verdict,
        text=" ".join(rest).casefold().strip(),
    )


def _brief_text(brief: object) -> str:
    parts = [
        str(getattr(brief, "run_id", "") or ""),
        str(getattr(brief, "label", "") or ""),
        str(getattr(brief, "tool_name", "") or ""),
        str(getattr(brief, "agent", "") or ""),
        str(getattr(brief, "project", "") or ""),
        str(getattr(brief, "owner_id", "") or ""),
    ]
    return " ".join(parts).casefold()


def _brief_matches(brief: object, filt: _ToolRunsFilter) -> bool:
    """Return whether *brief* satisfies the parsed filter."""

    if filt.tool:
        label = str(getattr(brief, "label", "") or "").casefold()
        tool_name = str(getattr(brief, "tool_name", "") or "").casefold()
        if filt.tool not in label and filt.tool not in tool_name:
            return False
    if filt.state:
        if filt.state != str(getattr(brief, "state", "") or "").casefold():
            return False
    if filt.agent:
        agent = str(getattr(brief, "agent", "") or "").casefold()
        owner = str(getattr(brief, "owner_id", "") or "").casefold()
        if filt.agent not in agent and filt.agent not in owner:
            return False
    if filt.verdict:
        bucket = ""
        verdict = getattr(brief, "verdict", None)
        if verdict is not None:
            bucket = str(getattr(verdict, "bucket", "") or "").casefold()
        if filt.verdict != bucket:
            return False
    if filt.text and filt.text not in _brief_text(brief):
        return False
    return True


def filter_briefs(
    briefs: list[object],
    query: str,
    *,
    project: str | None,
) -> list[object]:
    """Filter *briefs* by project scope and the ``/`` query."""

    filt = _parse_tool_runs_filter(query)
    kept: list[object] = []
    for brief in briefs:
        if project is not None:
            if str(getattr(brief, "project", "") or "") != project:
                continue
        if not _brief_matches(brief, filt):
            continue
        kept.append(brief)
    return kept


def order_runs(
    briefs: list[object],
    live_by_id: Mapping[str, object],
    *,
    now_ts: int,
    silent_after_s: int = 60,
) -> list[tuple[str, object]]:
    """Order runs silent-first, then live, then settled newest first.

    Returns ``(kind, brief)`` pairs where kind is ``silent``, ``live``,
    or ``settled``. Silence is TUI-derived from the glance row's
    ``last_activity_ts``; nothing is settled or reconciled here.
    """

    silent: list[object] = []
    live: list[object] = []
    settled: list[object] = []
    for brief in briefs:
        run_id = str(getattr(brief, "run_id", "") or "")
        glance = live_by_id.get(run_id)
        if glance is None:
            state = str(getattr(brief, "state", "") or "")
            if state in ("created", "running"):
                live.append(brief)
            else:
                settled.append(brief)
            continue
        try:
            last_activity = int(getattr(glance, "last_activity_ts", 0) or 0)
        except (TypeError, ValueError):
            last_activity = 0
        if max(0, int(now_ts) - last_activity) >= max(1, int(silent_after_s)):
            silent.append(brief)
        else:
            live.append(brief)

    def _created(item: object) -> int:
        try:
            return int(getattr(item, "created_ts", 0) or 0)
        except (TypeError, ValueError):
            return 0

    silent.sort(key=_created, reverse=True)
    live.sort(key=_created, reverse=True)
    settled.sort(key=_created, reverse=True)
    return (
        [("silent", item) for item in silent]
        + [("live", item) for item in live]
        + [("settled", item) for item in settled]
    )


def format_run_row(kind: str, brief: object) -> str:
    """Format one Runs list row: state mark, label, verdict, owner, id."""

    from sase.tool.view_vocabulary import style_for_bucket
    from sase.ace.tui.tool_runs.deck import (
        tool_run_bucket_words,
        tool_run_display_bucket,
    )

    run_id = str(getattr(brief, "run_id", "") or "")
    label = str(getattr(brief, "label", "") or "run")
    agent = str(getattr(brief, "agent", "") or "")
    owner_id = str(getattr(brief, "owner_id", "") or "")
    who = agent or owner_id or "—"
    bucket = tool_run_display_bucket(brief)
    style = style_for_bucket(bucket)
    words = tool_run_bucket_words(brief, bucket)
    if kind == "silent":
        mark = "⚒⚠"
    elif kind == "live":
        mark = "⚒"
    else:
        mark = style.glyph
    verdict = f" {words}" if words else ""
    return f"{mark} {label}{verdict}  {who}  {run_id[:8]}".rstrip()


def format_failure_row(group: dict[str, object]) -> str:
    """Format one Failures list row from a ``tool_run_failures`` group."""

    item_class = str(group.get("class", "") or group.get("bucket", "") or "?")
    tool = str(group.get("tool", "") or "")
    stage = str(group.get("stage_key", "") or group.get("stage", "") or "")
    display = str(group.get("display", "") or group.get("signature", "") or "")
    runs = group.get("runs", group.get("witness_runs", 0))
    agents = group.get("agents", group.get("witness_agents", 0))
    where = f"{tool} {stage}".strip()
    head = f"{item_class} {where}".strip() or item_class
    return f"{head}  {display[:80]}  {runs} runs · {agents} agents".rstrip()


__all__ = [
    "ToolRunFocusTarget",
    "filter_briefs",
    "format_failure_row",
    "format_run_row",
    "order_runs",
]
