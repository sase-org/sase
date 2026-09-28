"""LLM Calls and slow-tool join logic for run-links."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from rich.text import Text

from sase.ace.tui.tool_runs._links_shared import is_live_run, run_bucket
from sase.ace.tui.tool_runs.links_commands import extract_run_ids, is_tool_run_command
from sase.ace.tui.tool_runs.links_suffixes import suffix_text_with_jump

__all__ = [
    "CALL_WINDOW_SLOP_S",
    "match_llm_call_to_run",
    "match_llm_calls_to_runs",
    "pick_context_run",
    "slow_suffixes_for_entries",
]

#: Seconds of slop on either side of a call window for the primary join.
CALL_WINDOW_SLOP_S = 2.0


def _call_command(entry: Any) -> str:
    target = ""
    try:
        target = str(getattr(entry, "compact_target", "") or "")
    except Exception:
        target = ""
    detail = ""
    try:
        detail = str(getattr(entry, "detail", "") or "")
    except Exception:
        detail = ""
    return f"{target} {detail}".strip()


def _call_output_text(entry: Any) -> str:
    parts: list[str] = []
    for attr in ("detail", "compact_target"):
        try:
            value = getattr(entry, attr, "")
            if isinstance(value, str) and value:
                parts.append(value)
            elif value is not None and not isinstance(value, str):
                parts.append(str(value))
        except Exception:
            continue
    try:
        summaries = getattr(entry, "tool_response_summary", None)
        if isinstance(summaries, dict):
            for key in (
                "stdout_preview",
                "stderr_preview",
                "output_preview",
                "content_preview",
                "result_preview",
                "preview",
            ):
                value = summaries.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)
                    break
    except Exception:
        pass
    return "\n".join(parts)


def _parse_entry_ts(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _entry_window(entry: Any) -> tuple[float, float] | None:
    start = _parse_entry_ts(getattr(entry, "recorded_at", None))
    if start is None:
        return None
    end = _parse_entry_ts(getattr(entry, "completed_at", None))
    if end is None:
        try:
            duration_ms = getattr(entry, "duration_ms", None)
            end = (
                start + max(0.0, float(duration_ms) / 1000.0)
                if duration_ms is not None
                else start
            )
        except (TypeError, ValueError):
            end = start
    if end < start:
        end = start
    return (start, end)


def match_llm_call_to_run(
    entry: Any,
    runs: Any,
    *,
    now_ts: float | None = None,
) -> Any | None:
    """Return the run behind one LLM Calls row, or None.

    Non-Bash rows never match. Tool-run Bash rows match by scrape-first
    fallback (32-hex id from the call output), else by the primary join:
    ``created_ts`` inside the call window ± slop and a label/tool token
    in the command. Nearest ``created_ts`` wins.
    """

    del now_ts
    if getattr(entry, "tool_name", None) != "Bash":
        return None
    runs = tuple(runs or ())
    if not runs:
        return None
    command = _call_command(entry)
    if not is_tool_run_command(command):
        return None
    output = _call_output_text(entry)
    scraped = extract_run_ids(output)
    if scraped:
        by_id = {str(getattr(run, "run_id", "") or ""): run for run in runs}
        for candidate in scraped:
            if candidate in by_id:
                return by_id[candidate]
        lowered = output.lower()
        for run in runs:
            run_id = str(getattr(run, "run_id", "") or "")
            if run_id and run_id.lower() in lowered:
                return run
    window = _entry_window(entry)
    if window is None:
        return None
    start, end = window
    lowered_command = command.lower()
    candidates: list[tuple[float, Any]] = []
    for run in runs:
        try:
            created = float(getattr(run, "created_ts", 0) or 0)
        except (TypeError, ValueError):
            continue
        if created < start - CALL_WINDOW_SLOP_S or created > end + CALL_WINDOW_SLOP_S:
            continue
        label = str(getattr(run, "label", "") or "").lower()
        tool = str(getattr(run, "tool_name", "") or "").lower()
        if (label and label in lowered_command) or (tool and tool in lowered_command):
            midpoint = (start + end) / 2.0
            candidates.append((abs(created - midpoint), run))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def match_llm_calls_to_runs(
    entries: Any,
    runs: Any,
    *,
    now_ts: float | None = None,
) -> dict[int, Any]:
    """Return ``{id(entry): run}`` for matched LLM Calls rows."""

    links: dict[int, Any] = {}
    for entry in entries or ():
        try:
            matched = match_llm_call_to_run(entry, runs, now_ts=now_ts)
        except Exception:
            matched = None
        if matched is not None:
            try:
                links[id(entry)] = matched
            except Exception:
                continue
    return links


def pick_context_run(runs: Any, *, now_ts: float | None = None) -> Any | None:
    """Pick the Context card run: live wins, else the most severe settled."""

    from sase.tool.view_vocabulary import severity_rank

    ordered = tuple(runs or ())
    if not ordered:
        return None
    now = float(now_ts) if now_ts is not None else time.time()
    del now
    live = [run for run in ordered if is_live_run(run)]
    if live:

        def _live_key(run: Any) -> tuple[int, int]:
            try:
                created = int(getattr(run, "created_ts", 0) or 0)
            except (TypeError, ValueError):
                created = 0
            stopping = 0 if bool(getattr(run, "stop_requested", False)) else 1
            return (stopping, created)

        return sorted(live, key=_live_key)[0]

    def _settled_key(run: Any) -> tuple[int, int]:
        try:
            created = int(getattr(run, "created_ts", 0) or 0)
        except (TypeError, ValueError):
            created = 0
        return (severity_rank(run_bucket(run)), -created)

    return sorted(ordered, key=_settled_key)[0]


def slow_suffixes_for_entries(
    entries: Any,
    runs: Any,
    *,
    now_ts: float | None = None,
) -> dict[int, Text]:
    """Return ``{id(entry): suffix}`` for tool-run slow-tool rows.

    Only Bash rows whose command names a tool run participate; every
    other row is absent from the map so its render stays byte-identical.
    Settled runs resolve through the same nearest-window join as LLM
    Calls; live glance runs match on label/tool token containment alone
    (a running row has no call end yet).
    """

    now = float(now_ts) if now_ts is not None else time.time()
    out: dict[int, Text] = {}
    for entry in entries or ():
        if getattr(entry, "tool_name", None) != "Bash":
            continue
        command = _call_command(entry)
        if not is_tool_run_command(command):
            continue
        matched = match_llm_call_to_run(entry, runs, now_ts=now)
        if matched is None:
            matched = _live_token_match(command, runs)
        if matched is None:
            continue
        try:
            out[id(entry)] = suffix_text_with_jump(matched, prefix="·", now_ts=now)
        except Exception:
            continue
    return out


def _live_token_match(command: str, runs: Any) -> Any | None:
    """Return the best live run whose label/tool token names *command*."""

    lowered = str(command or "").lower()
    best: Any | None = None
    best_created = -1
    for run in runs or ():
        if not is_live_run(run):
            continue
        label = str(getattr(run, "label", "") or "").lower()
        tool = str(getattr(run, "tool_name", "") or "").lower()
        if (label and label in lowered) or (tool and tool in lowered):
            try:
                created = int(getattr(run, "created_ts", 0) or 0)
            except (TypeError, ValueError):
                created = 0
            if created >= best_created:
                best_created = created
                best = run
    return best
