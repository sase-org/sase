"""Links from LLM Calls, slow-tool rows, and Context cards to ToolRuns.

Plan §3.9 (epic sase-1bt, phase ``run-links``): a Bash row whose command
runs ``sase tool run …`` (or a ``sase monitor start`` wrapping one) gains a
verdict suffix and a jump to the run's block; a running or settled
``sase tool run`` row in the Main deck slow-tool list gains a live-stage or
verdict suffix; monitor and named-proc Context cards gain a ``Tool run``
row. All rendering here is pure: callers pass in-memory summaries plus
``now`` and never stat, open SQLite, or read a log.

Join rule (the core brief/glance wires carry no ``display_argv``, so the
match is time plus command tokens, not argv equality):

- same node (the caller scopes ``runs`` to the node already);
- run ``created_ts`` within ``[call start − 2 s, call end + 2 s]``;
- the call command names a tool run (``sase tool run`` or a wrapping
  ``sase monitor start``) and either carries the run's label/tool token
  or yields the run id through the scrape fallback;
- fallback: the 32-hex run id scraped from the call output, which the
  compact footer prints (``sase tool show <id> -l``).

When several runs fall in one call window, the nearest ``created_ts``
wins. Non-tool Bash rows never match.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any

from rich.text import Text

from sase.tool.view_vocabulary import (
    TOOL_RUN_ACCENT,
    TOOL_RUN_GLYPH,
    format_age,
    style_for_bucket,
)

#: Seconds of slop on either side of a call window for the primary join.
CALL_WINDOW_SLOP_S = 2.0

#: Pseudo-target prefix for run-block jumps (never a real path). Mirrors
#: the ``toolrun-log:`` scheme in
#: :mod:`sase.ace.tui.tool_runs.hints`; the suffix click handler and
#: ``v`` hint mode both resolve through it.
TOOLRUN_JUMP_TARGET_PREFIX = "toolrun-jump:"

_HEX_RUN_ID_RE = re.compile(r"\b[0-9a-f]{32}\b")
_TOOL_RUN_COMMAND_RE = re.compile(r"\bsase\b.*\btool\b.*\brun\b")
_MONITOR_START_RE = re.compile(r"\bsase\b.*\bmonitor\b.*\bstart\b")


def is_tool_run_command(command: str | None) -> bool:
    """Return True when *command* runs (or wraps) ``sase tool run``."""

    if not command:
        return False
    text = str(command)
    return bool(_TOOL_RUN_COMMAND_RE.search(text) or _MONITOR_START_RE.search(text))


def extract_run_ids(text: str | None) -> tuple[str, ...]:
    """Return 32-hex run ids found in *text*, in order, deduped."""

    if not text:
        return ()
    seen: set[str] = set()
    found: list[str] = []
    for match in _HEX_RUN_ID_RE.findall(str(text)):
        if match not in seen:
            seen.add(match)
            found.append(match)
    return tuple(found)


def tool_run_jump_target(run_id: str) -> str | None:
    """Return the ``toolrun-jump:<run_id>`` target, or None when blank."""

    clean = str(run_id or "").strip()
    if not clean:
        return None
    return f"{TOOLRUN_JUMP_TARGET_PREFIX}{clean}"


def run_id_from_jump_target(target: str) -> str | None:
    """Return the run id carried by a ``toolrun-jump:`` target, if any."""

    if not isinstance(target, str):
        return None
    if not target.startswith(TOOLRUN_JUMP_TARGET_PREFIX):
        return None
    run_id = target[len(TOOLRUN_JUMP_TARGET_PREFIX) :].strip()
    return run_id or None


def run_jump_hint_label(run_id: str) -> str:
    """Return the ``⚒ run <8hex>`` hint label for one run."""

    return f"⚒ run {str(run_id or '')[:8]}"


def visible_tool_run_jump_targets(
    runs: Any,
) -> list[tuple[str, str]]:
    """Return ``(label, target)`` jump pairs for *runs* in order."""

    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for run in runs or ():
        run_id = str(getattr(run, "run_id", "") or "").strip()
        if not run_id or run_id in seen:
            continue
        target = tool_run_jump_target(run_id)
        if target is None:
            continue
        seen.add(run_id)
        entries.append((run_jump_hint_label(run_id), target))
    return entries


def _run_bucket(run: Any) -> str:
    verdict = getattr(run, "verdict", None)
    bucket = str(getattr(verdict, "bucket", "") or "")
    if bucket:
        return bucket
    state = str(getattr(run, "state", "") or "")
    if state in ("created", "running"):
        return "running"
    return "undetermined"


def _is_live(run: Any) -> bool:
    return str(getattr(run, "state", "") or "") in ("created", "running")


def _elapsed_s(run: Any, now_ts: float) -> float:
    running_ts = getattr(run, "running_ts", None)
    created_ts = getattr(run, "created_ts", None)
    try:
        start = float(running_ts) if running_ts is not None else float(created_ts or 0)
    except (TypeError, ValueError):
        start = 0.0
    return max(0.0, now_ts - start)


def _last_activity_ts(run: Any) -> float:
    try:
        return float(getattr(run, "last_activity_ts", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _short_suffix_fragment(run: Any, *, now_ts: float) -> str:
    """Return the ``<label> <progress|bucket words>`` fragment for *run*."""

    from sase.tool.view_vocabulary import is_silent

    label = str(getattr(run, "label", "") or "run")
    if _is_live(run):
        silent_after = 60
        try:
            from sase.ace.tui.tool_runs.snapshot import get_snapshot

            snapshot = get_snapshot()
            silent_after = int(getattr(snapshot, "silent_after_s", 60) or 60)
        except Exception:
            silent_after = 60
        if is_silent(_last_activity_ts(run), now_ts, silent_after):
            return f"{label} silent {format_age(max(0.0, now_ts - _last_activity_ts(run)))}"
        if str(getattr(run, "state", "")) == "created" and not bool(
            getattr(run, "stop_requested", False)
        ):
            return f"{label} starting"
        if bool(getattr(run, "stop_requested", False)):
            return f"{label} stopping"
        expected = getattr(run, "stages_expected", None)
        try:
            done = int(getattr(run, "stages_done", 0) or 0)
        except (TypeError, ValueError):
            done = 0
        in_flight = bool(getattr(run, "current_stage", None)) or _is_live(run)
        position = done + 1 if in_flight else done
        try:
            expected_int = int(expected) if expected is not None else None
        except (TypeError, ValueError):
            expected_int = None
        if expected_int and 1 <= position <= expected_int:
            return f"{label} {position}/{expected_int}"
        return f"{label} {format_age(_elapsed_s(run, now_ts))}"
    bucket = _run_bucket(run)
    style = style_for_bucket(bucket)
    verdict = getattr(run, "verdict", None)
    try:
        new = int(getattr(verdict, "new", 0) or 0)
    except (TypeError, ValueError):
        new = 0
    try:
        known = int(getattr(verdict, "known", 0) or 0)
    except (TypeError, ValueError):
        known = 0
    try:
        unknown = int(getattr(verdict, "unknown", 0) or 0)
    except (TypeError, ValueError):
        unknown = 0
    if bucket == "new_failures":
        rest = f"{new} NEW"
        if known:
            rest += f" · {known} KNOWN"
        return f"{label} {style.glyph} {rest}"
    if bucket == "known_only":
        return f"{label} {style.glyph} known only · {known} KNOWN"
    if bucket == "undetermined":
        reasons = getattr(verdict, "reasons", ()) if verdict is not None else ()
        try:
            untriaged = "not_triaged" in tuple(reasons or ())
        except TypeError:
            untriaged = False
        if untriaged:
            return f"{label} {style.glyph} untriaged"
        return f"{label} {style.glyph} {unknown} UNKNOWN"
    if bucket == "pass":
        return f"{label} {style.glyph}"
    if bucket == "killed":
        return f"{label} {style.glyph} killed"
    if bucket == "stopped":
        return f"{label} {style.glyph} stopped"
    if bucket == "lost":
        return f"{label} {style.glyph} lost"
    return f"{label} {style.glyph} {style.word}"


def llm_call_run_suffix_text(run: Any, *, now_ts: float | None = None) -> str:
    """Return the ``→ ⚒ <fragment>`` suffix for an LLM Calls row."""

    now = float(now_ts) if now_ts is not None else time.time()
    return f"→ {TOOL_RUN_GLYPH} {_short_suffix_fragment(run, now_ts=now)}"


def slow_tool_run_suffix_text(run: Any, *, now_ts: float | None = None) -> str:
    """Return the ``· ⚒ <fragment>`` suffix for a slow-tool row."""

    now = float(now_ts) if now_ts is not None else time.time()
    return f"· {TOOL_RUN_GLYPH} {_short_suffix_fragment(run, now_ts=now)}"


def context_tool_run_line(run: Any, *, now_ts: float | None = None) -> Text:
    """Return the Context card ``Tool run`` value for *run*.

    ``⚒ check ✗ 3 NEW · 04349ecf``: glyph, label, bucket words, and the
    8-hex short id. Pure: no store, no log, no clock beyond *now_ts*.
    """

    now = float(now_ts) if now_ts is not None else time.time()
    fragment = _short_suffix_fragment(run, now_ts=now)
    short_id = str(getattr(run, "run_id", "") or "")[:8]
    text = Text()
    text.append(f"{TOOL_RUN_GLYPH} {fragment}", style="")
    if short_id:
        text.append(f" · {short_id}", style="dim")
    _stamp_jump_meta(text, str(getattr(run, "run_id", "") or ""))
    return text


def _stamp_jump_meta(text: Text, run_id: str) -> None:
    """Stamp the run-block jump target onto *text* as click metadata."""

    if not run_id:
        return
    try:
        from rich.style import Style

        from sase.ace.tui.widgets.prompt_panel._section_navigation import (
            DECK_BLOCK_META_KEY,
        )

        text.stylize(
            Style(meta={DECK_BLOCK_META_KEY: run_id}),
            0,
            len(text.plain),
        )
    except Exception:
        return


def suffix_text_with_jump(
    run: Any, *, prefix: str, now_ts: float | None = None
) -> Text:
    """Return a styled suffix Text stamped with the run-block jump meta."""

    now = float(now_ts) if now_ts is not None else time.time()
    fragment = _short_suffix_fragment(run, now_ts=now)
    run_id = str(getattr(run, "run_id", "") or "")
    bucket = _run_bucket(run)
    if _is_live(run):
        try:
            from sase.tool.view_vocabulary import is_silent

            silent = is_silent(_last_activity_ts(run), now, _snapshot_silent_after_s())
        except Exception:
            silent = False
        style = "bold #FF5F5F" if silent else f"bold {TOOL_RUN_ACCENT}"
    else:
        try:
            style = str(style_for_bucket(bucket).color or "")
        except Exception:
            style = ""
    text = Text(f"{prefix} {TOOL_RUN_GLYPH} {fragment}", style=style)
    _stamp_jump_meta(text, run_id)
    return text


def _snapshot_silent_after_s() -> int:
    try:
        from sase.ace.tui.tool_runs.snapshot import get_snapshot

        return int(getattr(get_snapshot(), "silent_after_s", 60) or 60)
    except Exception:
        return 60


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
    live = [run for run in ordered if _is_live(run)]
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
        return (severity_rank(_run_bucket(run)), -created)

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
        if not _is_live(run):
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


def context_row_for_agent(
    agent: object,
    summary: Any | None,
    *,
    snapshot_runs: Any = (),
    snapshot_silent_after_s: int = 60,
    now_ts: float | None = None,
) -> Text | None:
    """Return the Context card ``Tool run`` value for *agent*, or None.

    Pure: settled facts come from the ``tool-runs`` lane, live facts
    overlay from the glance snapshot, and remote/clan rows never carry
    a row (D15). Returns None when the node has no selector or no runs.
    """

    if getattr(agent, "fleet_origin_alias", None):
        return None
    if bool(getattr(agent, "is_clan_container", False)):
        return None
    try:
        from sase.ace.tui.tool_runs.summaries import (
            node_live_runs as _overlay,
        )
        from sase.ace.tui.tool_runs.summaries import selector_for_agent
    except Exception:
        return None
    try:
        selector = selector_for_agent(agent)
    except Exception:
        return None
    if selector is None:
        return None
    now = float(now_ts) if now_ts is not None else time.time()
    try:
        live = _overlay(tuple(snapshot_runs or ()), selector)
    except Exception:
        live = ()
    settled: tuple[Any, ...] = ()
    if summary is not None:
        try:
            settled = tuple(getattr(summary, "latest_by_tool", ()) or ()) or tuple(
                getattr(summary, "runs", ()) or ()
            )
        except Exception:
            settled = ()
    live_ids = {str(getattr(run, "run_id", "")) for run in live}
    extra = [run for run in settled if str(getattr(run, "run_id", "")) not in live_ids]
    combined = (*live, *extra)
    if not combined:
        return None
    picked = pick_context_run(combined, now_ts=now)
    if picked is None:
        return None
    try:
        return context_tool_run_line(picked, now_ts=now)
    except Exception:
        return None


def _live_snapshot_runs() -> tuple[Any, ...]:
    """Return the in-memory glance runs, or () when unavailable."""

    try:
        from sase.ace.tui.tool_runs.snapshot import get_snapshot

        snapshot = get_snapshot()
        return tuple(getattr(snapshot, "runs", ()) or ())
    except Exception:
        return ()


def node_runs_for_agent(
    agent: object,
    node_summary: Any | None = None,
    *,
    snapshot_runs: Any | None = None,
) -> tuple[Any, ...]:
    """Return the agent-scoped runs for link matching (no I/O).

    Settled facts come from *node_summary* (falling back to the LRU-only
    cached entry, never a store load); live facts overlay from the
    in-memory glance snapshot. Returns () when the node has no selector
    or it has no runs.
    """

    try:
        from sase.ace.tui.tool_runs.summaries import (
            cached_node_summary_for_selector,
        )
        from sase.ace.tui.tool_runs.summaries import node_live_runs as _overlay
        from sase.ace.tui.tool_runs.summaries import selector_for_agent
    except Exception:
        return ()
    try:
        selector = selector_for_agent(agent)
    except Exception:
        return ()
    if selector is None:
        return ()
    summary = node_summary
    if summary is None:
        try:
            summary = cached_node_summary_for_selector(selector)
        except Exception:
            summary = None
    runs = tuple(snapshot_runs) if snapshot_runs is not None else _live_snapshot_runs()
    try:
        live = _overlay(runs, selector)
    except Exception:
        live = ()
    settled: tuple[Any, ...] = ()
    if summary is not None:
        try:
            settled = tuple(getattr(summary, "latest_by_tool", ()) or ()) or tuple(
                getattr(summary, "runs", ()) or ()
            )
        except Exception:
            settled = ()
    live_ids = {str(getattr(run, "run_id", "")) for run in live}
    extra = tuple(
        run for run in settled if str(getattr(run, "run_id", "")) not in live_ids
    )
    return (*live, *extra)


def run_links_for_agent_entries(
    agent: object,
    entries: Any,
    node_summary: Any | None = None,
    *,
    snapshot_runs: Any | None = None,
    now_ts: float | None = None,
) -> dict[int, Any]:
    """Return ``{id(entry): run}`` for *agent*'s LLM Calls rows (no I/O)."""

    try:
        runs = node_runs_for_agent(agent, node_summary, snapshot_runs=snapshot_runs)
    except Exception:
        return {}
    if not runs:
        return {}
    try:
        return match_llm_calls_to_runs(entries, runs, now_ts=now_ts)
    except Exception:
        return {}


def slow_suffixes_for_agent_sources(
    agent: object,
    sources: Any,
    node_summary: Any | None = None,
    *,
    snapshot_runs: Any | None = None,
    now_ts: float | None = None,
) -> dict[int, Text]:
    """Return ``{id(entry): suffix}`` for *agent*'s slow-tool rows (no I/O)."""

    try:
        runs = node_runs_for_agent(agent, node_summary, snapshot_runs=snapshot_runs)
    except Exception:
        return {}
    if not runs:
        return {}
    entries: list[Any] = []
    for source in sources or ():
        try:
            entries.extend(tuple(getattr(source, "entries", ()) or ()))
        except Exception:
            continue
    try:
        return slow_suffixes_for_entries(entries, runs, now_ts=now_ts)
    except Exception:
        return {}


def context_row_for_agent_cached(
    agent: object,
    node_summary: Any | None = None,
    *,
    snapshot_runs: Any | None = None,
    now_ts: float | None = None,
) -> Text | None:
    """Return the Context card ``Tool run`` value using cached state (no I/O).

    Like :func:`context_row_for_agent` but resolves the node summary from
    the LRU and the live runs from the glance snapshot when the caller
    has no ``tool-runs`` lane at hand, so render paths without lane
    access stay keystroke-safe.
    """

    try:
        runs = node_runs_for_agent(agent, node_summary, snapshot_runs=snapshot_runs)
    except Exception:
        return None
    if not runs:
        return None
    try:
        picked = pick_context_run(runs, now_ts=now_ts)
    except Exception:
        return None
    if picked is None:
        return None
    try:
        return context_tool_run_line(picked, now_ts=now_ts)
    except Exception:
        return None


__all__ = [
    "CALL_WINDOW_SLOP_S",
    "TOOLRUN_JUMP_TARGET_PREFIX",
    "context_row_for_agent",
    "context_row_for_agent_cached",
    "context_tool_run_line",
    "extract_run_ids",
    "is_tool_run_command",
    "llm_call_run_suffix_text",
    "match_llm_call_to_run",
    "match_llm_calls_to_runs",
    "node_runs_for_agent",
    "pick_context_run",
    "run_id_from_jump_target",
    "run_jump_hint_label",
    "run_links_for_agent_entries",
    "slow_suffixes_for_agent_sources",
    "slow_suffixes_for_entries",
    "slow_tool_run_suffix_text",
    "suffix_text_with_jump",
    "tool_run_jump_target",
    "visible_tool_run_jump_targets",
]
