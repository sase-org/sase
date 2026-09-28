"""Pure selection-scoped header chip and Tool runs field (plan §3.7).

All rendering here is a pure function of in-memory state plus ``now``:
a :class:`~sase.core.tool_run.ToolRunNodeSummary` from the ``tool-runs``
lane, live glance rows overlaid from the app snapshot, and the wall clock.
Nothing stats, opens SQLite, or reads a log.

Chip policy (the header has no 1 s repaint loop, per D6, so every time is
a point-in-time snapshot, never a ticking relative age):

- a live run wins over settled history; silent outranks plain live;
- otherwise the most severe settled run per label wins (§3.2 severity),
  plus ``+N`` when other labels exist;
- live elapsed turns amber past the reference typical; settled times are
  absolute ``HH:MM``, never relative.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.tool.view_vocabulary import (
    SILENT_GLYPH,
    TOOL_RUN_ACCENT,
    WARNING_COLOR,
    header_chip_text,
    is_silent,
    severity_rank,
    style_for_bucket,
)

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent
    from sase.core.tool_run import ToolRunBrief, ToolRunGlance, ToolRunNodeSummary

FAILURE_STYLE = "bold #FF5F5F"
LIVE_STYLE = f"bold {TOOL_RUN_ACCENT}"
AMBER_STYLE = f"bold {WARNING_COLOR}"
_SHORT_ID_CELLS = 8


@dataclass(frozen=True)
class _HeaderRunChoice:
    """The one run behind the compact header chip."""

    run_id: str
    label: str
    text: str
    style: str
    extra_labels: int = 0


@dataclass(frozen=True)
class _ToolRunsFieldEntry:
    """One per-label entry of the expanded ``Tool runs`` field."""

    text: str
    style: str
    run_id: str


def _run_created_ts(run: Any) -> int:
    try:
        return int(getattr(run, "created_ts", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _is_live_state(run: Any) -> bool:
    return str(getattr(run, "state", "")) in {"created", "running"}


def _last_activity_ts(run: Any) -> float:
    try:
        return float(getattr(run, "last_activity_ts", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _elapsed_s(run: Any, now_ts: float) -> float:
    running_ts = getattr(run, "running_ts", None)
    created_ts = getattr(run, "created_ts", None)
    try:
        start = float(running_ts) if running_ts is not None else float(created_ts or 0)
    except (TypeError, ValueError):
        start = 0.0
    return max(0.0, now_ts - start)


def _order_live(
    primary: tuple[Any, ...], now_ts: float, silent_after_s: int
) -> tuple[Any, ...]:
    """Order live runs with the chip primary first (silent, then oldest)."""

    def _key(run: Any) -> tuple[int, int]:
        silent = 0 if is_silent(_last_activity_ts(run), now_ts, silent_after_s) else 1
        return (silent, _run_created_ts(run))

    return tuple(sorted(primary, key=_key))


def _live_choice(
    live: tuple[Any, ...],
    labels: list[str],
    *,
    now_ts: float,
    silent_after_s: int,
) -> _HeaderRunChoice | None:
    ordered = _order_live(live, now_ts, silent_after_s)
    if not ordered:
        return None
    primary = ordered[0]
    label = str(getattr(primary, "label", "") or "")
    extra = len([name for name in labels if name != label])
    run_id = str(getattr(primary, "run_id", ""))
    if is_silent(_last_activity_ts(primary), now_ts, silent_after_s):
        text = header_chip_text(
            label,
            "running",
            silent_age_s=max(0.0, now_ts - _last_activity_ts(primary)),
            extra_labels=extra,
        )
        return _HeaderRunChoice(
            run_id=run_id,
            label=label,
            text=text,
            style=FAILURE_STYLE,
            extra_labels=extra,
        )
    elapsed = _elapsed_s(primary, now_ts)
    typical_ms = getattr(primary, "typical_ms", None)
    try:
        typical_ms = int(typical_ms) if typical_ms is not None else None
    except (TypeError, ValueError):
        typical_ms = None
    current_stage = getattr(primary, "current_stage", None)
    stage = getattr(current_stage, "description", None) or None
    text = header_chip_text(
        label,
        "running",
        state=str(getattr(primary, "state", "running") or "running"),
        stop_requested=bool(getattr(primary, "stop_requested", False)),
        stage=stage,
        stages_done=int(getattr(primary, "stages_done", 0) or 0),
        stages_expected=getattr(primary, "stages_expected", None),
        elapsed_s=elapsed,
        typical_ms=typical_ms,
        extra_labels=extra,
    )
    style = LIVE_STYLE
    if typical_ms is not None and elapsed * 1000 > typical_ms:
        style = AMBER_STYLE
    return _HeaderRunChoice(
        run_id=run_id, label=label, text=text, style=style, extra_labels=extra
    )


def _brief_bucket(brief: ToolRunBrief) -> str:
    verdict = getattr(brief, "verdict", None)
    bucket = getattr(verdict, "bucket", None) if verdict is not None else None
    return str(bucket or "undetermined")


def _settled_choice(
    briefs: tuple[Any, ...],
    labels: list[str],
    *,
    now_ts: float,
    silent_after_s: int,
) -> _HeaderRunChoice | None:
    del now_ts, silent_after_s
    if not briefs:
        return None
    primary = min(
        briefs,
        key=lambda brief: (
            severity_rank(_brief_bucket(brief)),
            -_run_created_ts(brief),
        ),
    )
    label = str(getattr(primary, "label", "") or "")
    extra = len([name for name in labels if name != label])
    return _render_settled(primary, extra_labels=extra)


def _render_settled(primary: Any, *, extra_labels: int = 0) -> _HeaderRunChoice:
    verdict = getattr(primary, "verdict", None)
    text = header_chip_text(
        str(getattr(primary, "label", "") or ""),
        _brief_bucket(primary),
        duration_ms=getattr(primary, "duration_ms", None),
        settled_ts=getattr(primary, "settled_ts", None),
        new=int(getattr(verdict, "new", 0) or 0) if verdict is not None else 0,
        known=int(getattr(verdict, "known", 0) or 0) if verdict is not None else 0,
        unknown=int(getattr(verdict, "unknown", 0) or 0) if verdict is not None else 0,
        untriaged=_is_untriaged(verdict),
        terminal_cause=getattr(primary, "terminal_cause", None),
        extra_labels=extra_labels,
    )
    return _HeaderRunChoice(
        run_id=str(getattr(primary, "run_id", "")),
        label=str(getattr(primary, "label", "") or ""),
        text=text,
        style=style_for_bucket(_brief_bucket(primary)).color,
        extra_labels=extra_labels,
    )


def _is_untriaged(verdict: Any | None) -> bool:
    reasons = getattr(verdict, "reasons", ()) if verdict is not None else ()
    try:
        return "not_triaged" in tuple(reasons or ())
    except TypeError:
        return False


def _distinct_labels(
    live: tuple[Any, ...],
    briefs: tuple[Any, ...],
) -> list[str]:
    labels: list[str] = []
    for run in (*live, *briefs):
        label = str(getattr(run, "label", "") or "")
        if label and label not in labels:
            labels.append(label)
    return labels


def _select_header_run(
    live: tuple[Any, ...],
    latest_by_tool: tuple[Any, ...],
    fallback_runs: tuple[Any, ...] = (),
    *,
    now_ts: float,
    silent_after_s: int = 60,
) -> _HeaderRunChoice | None:
    """Pick the one run behind the compact header chip.

    A live run wins; otherwise the most severe settled run wins (§3.2).
    ``latest_by_tool`` carries one settled brief per label; *fallback_runs*
    covers summaries whose ``latest_by_tool`` is empty.
    """

    briefs = tuple(latest_by_tool) or tuple(fallback_runs)
    labels = _distinct_labels(tuple(live), briefs)
    if live:
        return _live_choice(
            tuple(live), labels, now_ts=now_ts, silent_after_s=silent_after_s
        )
    return _settled_choice(briefs, labels, now_ts=now_ts, silent_after_s=silent_after_s)


def header_chip_for_node(
    agent: object,
    summary: ToolRunNodeSummary | None,
    *,
    snapshot_runs: tuple[Any, ...] | list[Any] = (),
    snapshot_silent_after_s: int = 60,
    now_ts: float | None = None,
) -> tuple[str, str, str] | None:
    """Return ``(text, style, run_id)`` for the node's header chip, or None.

    The flag gates every surface; remote and clan rows never carry a chip
    (D15). Settled facts come from the ``tool-runs`` lane; live facts are
    overlaid from the glance snapshot so the chip moves without a summary
    reload.
    """

    from sase.ace.tui.tool_runs.flag import tool_runs_enabled
    from sase.ace.tui.tool_runs.summaries import node_live_runs as _overlay
    from sase.ace.tui.tool_runs.summaries import selector_for_agent

    if not tool_runs_enabled():
        return None
    if getattr(agent, "fleet_origin_alias", None):
        return None
    if bool(getattr(agent, "is_clan_container", False)):
        return None
    selector = selector_for_agent(agent)
    if selector is None:
        return None
    now = float(now_ts) if now_ts is not None else time.time()
    overlay = _overlay(tuple(snapshot_runs or ()), selector)
    summary_live: tuple[Any, ...] = tuple(getattr(summary, "live", ()) or ())
    overlay_ids = {str(getattr(run, "run_id", "")) for run in overlay}
    live = tuple(overlay) + tuple(
        run
        for run in summary_live
        if str(getattr(run, "run_id", "")) not in overlay_ids
    )
    briefs: tuple[Any, ...] = tuple(getattr(summary, "latest_by_tool", ()) or ())
    if not briefs and summary is not None:
        briefs = tuple(getattr(summary, "runs", ()) or ())
    choice = _select_header_run(
        live,
        briefs,
        now_ts=now,
        silent_after_s=int(snapshot_silent_after_s or 60),
    )
    if choice is None:
        return None
    return (choice.text, choice.style, choice.run_id)


def _short_id(run_id: str) -> str:
    return (run_id or "")[:_SHORT_ID_CELLS]


def _handoff_suffix(run: Any, selector: Any) -> str:
    """Annotate cross-node runs per §3.3 (handed-off or starter-owned)."""

    owner_kind = getattr(run, "owner_kind", None)
    owner_id = getattr(run, "owner_id", None)
    selector_owners = {tuple(item) for item in (getattr(selector, "owners", ()) or ())}
    if selector_owners:
        starter = getattr(run, "agent", None)
        if starter:
            return f" · {starter}"
        return ""
    if owner_kind == "monitor" and owner_id:
        return f" → monitor {owner_id}"
    if owner_kind == "proc" and owner_id:
        return f" → proc {owner_id}"
    return ""


def tool_runs_field_entries(
    agent: object,
    summary: ToolRunNodeSummary | None,
    *,
    snapshot_runs: tuple[Any, ...] | list[Any] = (),
    snapshot_silent_after_s: int = 60,
    now_ts: float | None = None,
) -> tuple[_ToolRunsFieldEntry, ...]:
    """Return one expanded-field entry per label, live winning per label."""

    from sase.ace.tui.tool_runs.flag import tool_runs_enabled
    from sase.ace.tui.tool_runs.summaries import node_live_runs as _overlay
    from sase.ace.tui.tool_runs.summaries import selector_for_agent

    if not tool_runs_enabled():
        return ()
    if getattr(agent, "fleet_origin_alias", None):
        return ()
    if bool(getattr(agent, "is_clan_container", False)):
        return ()
    selector = selector_for_agent(agent)
    if selector is None:
        return ()
    now = float(now_ts) if now_ts is not None else time.time()
    silent_after_s = int(snapshot_silent_after_s or 60)
    overlay = _overlay(tuple(snapshot_runs or ()), selector)
    settled: tuple[Any, ...] = ()
    if summary is not None:
        settled = tuple(getattr(summary, "latest_by_tool", ()) or ()) or tuple(
            getattr(summary, "runs", ()) or ()
        )
    by_label: dict[str, Any] = {}
    for brief in settled:
        label = str(getattr(brief, "label", "") or "")
        if label and label not in by_label:
            by_label[label] = brief
    live_by_label: dict[str, Any] = {}
    for run in _order_live(overlay, now, silent_after_s):
        label = str(getattr(run, "label", "") or "")
        if label and label not in live_by_label:
            live_by_label[label] = run
    entries: list[_ToolRunsFieldEntry] = []
    for label in (
        *live_by_label,
        *[name for name in by_label if name not in live_by_label],
    ):
        suffix = ""
        if label in live_by_label:
            run = live_by_label[label]
            run_id = str(getattr(run, "run_id", ""))
            suffix = _handoff_suffix(run, selector)
            if is_silent(_last_activity_ts(run), now, silent_after_s):
                text = (
                    f"{label} {SILENT_GLYPH} silent "
                    f"{_age_word(max(0.0, now - _last_activity_ts(run)))}"
                    f" {_short_id(run_id)}{suffix}"
                )
                entries.append(
                    _ToolRunsFieldEntry(text=text, style=FAILURE_STYLE, run_id=run_id)
                )
                continue
            progress = _live_progress(run, now)
            text = f"{label} {progress} {_short_id(run_id)}{suffix}"
            style = LIVE_STYLE
            typical_ms = getattr(run, "typical_ms", None)
            try:
                typical_ms = int(typical_ms) if typical_ms is not None else None
            except (TypeError, ValueError):
                typical_ms = None
            if typical_ms is not None and _elapsed_s(run, now) * 1000 > typical_ms:
                style = AMBER_STYLE
            entries.append(_ToolRunsFieldEntry(text=text, style=style, run_id=run_id))
            continue
        brief = by_label[label]
        run_id = str(getattr(brief, "run_id", ""))
        suffix = _handoff_suffix(brief, selector)
        fragment = _settled_fragment(brief)
        text = f"{label} {fragment} {_short_id(run_id)}{suffix}"
        entries.append(
            _ToolRunsFieldEntry(
                text=text,
                style=style_for_bucket(_brief_bucket(brief)).color,
                run_id=run_id,
            )
        )
    return tuple(entries)


def _age_word(seconds: float) -> str:
    from sase.tool.view_vocabulary import format_age

    return format_age(seconds)


def _live_progress(run: Any, now_ts: float) -> str:
    from sase.tool.view_vocabulary import format_age

    if str(getattr(run, "state", "")) == "created" and not bool(
        getattr(run, "stop_requested", False)
    ):
        return "starting"
    if bool(getattr(run, "stop_requested", False)):
        return "stopping"
    expected = getattr(run, "stages_expected", None)
    try:
        done = int(getattr(run, "stages_done", 0) or 0)
    except (TypeError, ValueError):
        done = 0
    in_flight = bool(getattr(run, "current_stage", None)) or _is_live_state(run)
    position = done + 1 if in_flight else done
    if expected is not None and int(expected) > 0 and 1 <= position <= int(expected):
        return f"{position}/{expected}"
    return format_age(_elapsed_s(run, now_ts))


def _settled_fragment(brief: Any) -> str:
    bucket = _brief_bucket(brief)
    style = style_for_bucket(bucket)
    verdict = getattr(brief, "verdict", None)
    new = int(getattr(verdict, "new", 0) or 0) if verdict is not None else 0
    known = int(getattr(verdict, "known", 0) or 0) if verdict is not None else 0
    unknown = int(getattr(verdict, "unknown", 0) or 0) if verdict is not None else 0
    if bucket == "new_failures":
        rest = f"{new} NEW"
        if known:
            rest += f" · {known} KNOWN"
        return f"{style.glyph} {rest}"
    if bucket == "known_only":
        return f"{style.glyph} known only · {known} KNOWN"
    if bucket == "undetermined":
        if _is_untriaged(verdict):
            return f"{style.glyph} untriaged"
        return f"{style.glyph} {unknown} UNKNOWN"
    if bucket == "pass":
        return f"{style.glyph}"
    cause = getattr(brief, "terminal_cause", None)
    if bucket == "killed":
        return f"{style.glyph} killed · {cause or 'signal'}"
    if bucket == "stopped":
        return f"{style.glyph} stopped"
    if bucket == "lost":
        return f"{style.glyph} lost · {cause}" if cause else f"{style.glyph} lost"
    return f"{style.glyph} {style.word}"


def header_run_id_for_agent(app: object, agent: Agent) -> str | None:
    """Return the full run id behind *agent*'s header chip, if any.

    Reads the cached ``tool-runs`` lane off the prompt panel plus the
    in-memory glance overlay; never touches the store, so copy-mode
    previews and actions stay on a keystroke-safe path. Returns None when
    the flag is off, the node has no runs, or the panel is unreachable.
    """

    if app is None or agent is None:
        return None
    try:
        from sase.ace.tui.tool_runs.flag import tool_runs_enabled

        if not tool_runs_enabled():
            return None
        from sase.ace.tui.tool_runs.snapshot import get_snapshot

        query_one = getattr(app, "query_one", None)
        if not callable(query_one):
            return None
        try:
            detail = query_one("#agent-detail-panel")
        except Exception:
            return None
        try:
            prompt_panel = detail.query_one("#agent-prompt-panel")
        except Exception:
            try:
                prompt_panel = query_one("#agent-prompt-panel")
            except Exception:
                return None
        from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
            get_cached_detail_header_summary,
        )

        summary = get_cached_detail_header_summary(prompt_panel, agent)
        node_summary = summary.tool_run_summary if summary is not None else None
        snapshot = get_snapshot()
        rendered = header_chip_for_node(
            agent,
            node_summary,
            snapshot_runs=snapshot.runs if snapshot is not None else (),
            snapshot_silent_after_s=(
                snapshot.silent_after_s if snapshot is not None else 60
            ),
        )
    except Exception:
        return None
    if rendered is None:
        return None
    return rendered[2] or None


__all__ = [
    "header_chip_for_node",
    "header_run_id_for_agent",
    "tool_runs_field_entries",
]
