"""Run-level Overview card for the ⊛ FINAL deck (epic sase-1b2, ``final-overview-card``).

Renders the plan in DAG order with selection reasons, configured-but-unselected
instances dimmed, the declaration timeline, controller cycles only when above one,
drift, run-level diagnostics, the runs ledger, calm skipped / not-reached /
unavailable states, and CLI pointers.

The renderer is presentation only: it reads the typed node view
(:class:`~sase.core.finalizer_run_view.FinalizerNodeView`, duck-typed so tests
can use light namespaces) and returns plain :class:`~rich.text.Text` lines.
It never outputs config values — only selection reasons, status words, and the
projection's own messages reach the card (plan §3.4 secrecy rule).
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.core.time import format_local
from sase.finalizers.view_vocabulary import (
    FINAL_GLYPH,
    STATE_STYLES,
    WARNING_COLOR,
    FinalizerStateStyle,
    instance_style,
)

#: CLI pointers footer (plan §4.15 mockup).
OVERVIEW_FOOTER = "sase final status <agent> · sase final list · sase final doctor"

#: Calm explanation for a handoff-skipped run (plan D8).
SKIPPED_EXPLANATION = "this turn handed off; its successor lands the work"

#: Fallback clock text when a declaration carries no timestamp.
_UNKNOWN_TIME = "--:--:--"

#: Cap for free-text tails (first message lines, drift, diagnostics), mirroring
#: the C5 120-character string cap.
_FREE_TEXT_CAP = 120


def _format_overview_duration(seconds: float) -> str:
    """Format a duration the way the Overview card mockup does (``6m02s``)."""
    if seconds >= 60:
        minutes = int(seconds // 60)
        rest = int(seconds % 60)
        return f"{minutes}m{rest:02d}s"
    return f"{seconds:.1f}s"


def _overview_instance_style(status: str | None) -> FinalizerStateStyle:
    """Return the shared style for a node-level instance *status*.

    Accepts both C5 per-instance codes (``not_triggered``) and §3.2 state
    words (``not triggered``); an unknown status renders as its raw word,
    dim, rather than a wrong label.
    """
    if status is None:
        status = ""
    normalized = str(status).strip()
    try:
        return instance_style(normalized)
    except Exception:  # pragma: no cover - defensive; instance_style is total
        pass
    direct = STATE_STYLES.get(normalized)
    if direct is not None:
        return direct
    lowered = normalized.lower().replace("_", " ").strip()
    for key, style in STATE_STYLES.items():
        if key == lowered:
            return style
    return FinalizerStateStyle(glyph="·", word=normalized or "unknown", color="dim")


def _run_disposition_style(disposition: str | None) -> FinalizerStateStyle:
    """Return the shared style for a run *disposition*."""
    key = str(disposition or "").strip().lower()
    mapping = {
        "active": "running",
        "ran": "success",
        "skipped": "skipped",
        "not_reached": "not reached",
        "not-reached": "not reached",
        "interrupted": "interrupted",
        "unavailable": "unavailable",
    }
    style_key = mapping.get(key)
    if style_key is None:
        return FinalizerStateStyle(glyph="·", word=key or "unknown", color="dim")
    return STATE_STYLES[style_key]


def _node_runs(node_view: Any) -> list[Any]:
    return list(getattr(node_view, "runs", ()) or ())


def _instances(node_view: Any) -> list[Any]:
    return list(getattr(node_view, "instances", ()) or ())


def _unselected(node_view: Any) -> list[Any]:
    return list(getattr(node_view, "unselected", ()) or ())


def _attempt_durations(run_instance: Any) -> float:
    total = 0.0
    for attempt in getattr(run_instance, "attempts", ()) or ():
        seconds = getattr(attempt, "duration_seconds", None)
        if isinstance(seconds, bool):
            continue
        try:
            total += float(seconds) if seconds is not None else 0.0
        except (TypeError, ValueError):
            continue
    return total


def _instance_durations(node_view: Any) -> dict[str, float]:
    """Return total attempt seconds per instance id across every run."""
    totals: dict[str, float] = {}
    for run in _node_runs(node_view):
        for item in getattr(run, "instances", ()) or ():
            instance_id = str(getattr(item, "instance_id", ""))
            totals[instance_id] = totals.get(instance_id, 0.0) + _attempt_durations(
                item
            )
    return totals


def _total_cycles(node_view: Any) -> int:
    return sum(int(getattr(run, "cycles", 0) or 0) for run in _node_runs(node_view))


def _shorten(text: str, budget: int) -> str:
    """Shorten free text to *budget* chars with an ellipsis marker."""
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= budget:
        return cleaned
    if budget <= 1:
        return "…"
    return cleaned[: budget - 1].rstrip() + "…"


def _fit_line(line: Text, width: int) -> Text:
    """Truncate *line* to *width* printable chars, preserving a tail marker."""
    if len(line.plain) <= width:
        return line
    if width <= 1:
        return Text("…")
    raw = line.plain[: width - 1].rstrip() + "…"
    return Text(raw, style="dim")


def _clock_text(moment: Any) -> str:
    try:
        value = None if moment is None or isinstance(moment, bool) else float(moment)
    except (TypeError, ValueError):
        return _UNKNOWN_TIME
    if value is None:
        return _UNKNOWN_TIME
    return format_local(value, "%H:%M:%S", default=_UNKNOWN_TIME)


def _declaration_style(status: str | None) -> FinalizerStateStyle:
    key = str(status or "").strip().lower()
    if key == "accepted":
        return STATE_STYLES["success"]
    if key in ("rejected", "failed"):
        return STATE_STYLES["failed"]
    if key == "recovered":
        return STATE_STYLES["success"]
    return FinalizerStateStyle(glyph="·", word=key or "unknown", color="dim")


def _node_status_style(node_view: Any) -> FinalizerStateStyle:
    glyph = str(getattr(node_view, "glyph", "") or "")
    status = str(getattr(node_view, "status", "") or "")
    for style in STATE_STYLES.values():
        if style.word == status:
            return style
    if glyph and status:
        return FinalizerStateStyle(glyph=glyph, word=status, color="dim")
    return FinalizerStateStyle(
        glyph=glyph or FINAL_GLYPH, word=status or "finalizers", color="dim"
    )


def _header_line(node_view: Any, durations: dict[str, float], *, width: int) -> Text:
    instances = _instances(node_view)
    style = _node_status_style(node_view)
    cycles = _total_cycles(node_view)
    total_seconds = sum(durations.values())
    runs = _node_runs(node_view)
    digest: str | None = None
    for run in runs:
        candidate = getattr(run, "plan_digest", None)
        if candidate:
            digest = str(candidate)
            break
    line = Text("OVERVIEW", style="bold")
    count = f"{len(instances)} selected" if instances else "nothing selected"
    line.append(f" · {count}", style="dim")
    line.append(f" · {style.glyph} {style.word}", style=style.color)
    if cycles > 1:
        line.append(f" · {cycles} cycles", style="dim")
    if total_seconds > 0:
        line.append(f" · {_format_overview_duration(total_seconds)}", style="dim")
    if digest:
        line.append(f" · plan {digest[:8]}", style="dim")
    return _fit_line(line, width)


def _plan_rows(
    node_view: Any, durations: dict[str, float], *, width: int
) -> list[Text]:
    lines: list[Text] = []
    blocked: dict[str, str] = {}
    waiting: dict[str, str] = {}
    for run in _node_runs(node_view):
        for item in getattr(run, "instances", ()) or ():
            instance_id = str(getattr(item, "instance_id", ""))
            blocker = getattr(item, "blocked_by", None)
            if blocker and instance_id not in blocked:
                blocked[instance_id] = str(blocker)
            linger = getattr(item, "waiting_on", None)
            if linger and instance_id not in waiting:
                waiting[instance_id] = str(linger)
    for item in _instances(node_view):
        instance_id = str(getattr(item, "instance_id", ""))
        status = getattr(item, "status", None)
        style = _overview_instance_style(status)
        provider = getattr(item, "provider_ref", None) or ""
        reason = str(getattr(item, "selection_reason", "") or "")
        after = [str(entry) for entry in (getattr(item, "after", ()) or ())]
        line = Text(f"  {style.glyph} {instance_id}", style=style.color)
        if provider and provider != instance_id:
            line.append(f"   {provider}", style="dim")
        detail = reason or "selected"
        if after:
            detail += f" · after {', '.join(after)}"
        blocker = blocked.get(instance_id)
        linger = waiting.get(instance_id)
        if blocker:
            detail += f" · not run (blocked by {blocker})"
        elif linger:
            detail += f" · after {linger}"
        line.append(f"    {detail}", style="dim")
        seconds = durations.get(instance_id, 0.0)
        if seconds > 0:
            line.append(f"  {_format_overview_duration(seconds)}", style="dim")
        lines.append(_fit_line(line, width))
    for item in _unselected(node_view):
        instance_id = str(getattr(item, "instance_id", ""))
        reason = str(getattr(item, "reason", "") or "")
        provider = getattr(item, "provider_ref", None) or ""
        line = Text(f"  ○ {instance_id}", style="dim")
        if provider and provider != instance_id:
            line.append(f"   {provider}", style="dim")
        suffix = f"configured · not selected ({reason})" if reason else "not selected"
        line.append(f"    {suffix}", style="dim")
        lines.append(_fit_line(line, width))
    return lines


def _declaration_lines(node_view: Any, *, width: int) -> list[Text]:
    runs = _node_runs(node_view)
    multi = len(runs) > 1
    lines: list[Text] = []
    for run in runs:
        declarations = list(getattr(run, "declarations", ()) or ())
        recovery = getattr(run, "recovery_turn", None)
        if not declarations and recovery is None:
            continue
        prefix = (
            f"{getattr(run, 'label', '') or getattr(run, 'run_id', '')} "
            if multi
            else ""
        )
        for entry in declarations:
            status = str(getattr(entry, "status", "") or "")
            style = _declaration_style(status)
            head = Text(
                "DECLARATION   " if not lines else "              ", style="dim"
            )
            head.append(
                f"{prefix}{_clock_text(getattr(entry, 't', None))} ", style="dim"
            )
            head.append(f"{style.glyph} {status}", style=style.color)
            code = getattr(entry, "code", None)
            if code:
                head.append(f"  {code}", style="dim")
            payload_count = getattr(entry, "payload_count", None)
            if isinstance(payload_count, bool):
                payload_count = None
            if payload_count is not None:
                try:
                    head.append(f"  {int(payload_count)} payloads", style="dim")
                except (TypeError, ValueError):
                    pass
            lines.append(_fit_line(head, width))
            first_line = getattr(entry, "first_line", None)
            if first_line:
                budget = max(8, min(_FREE_TEXT_CAP, width - 16))
                continuation = Text("              ", style="dim")
                continuation.append(_shorten(str(first_line), budget), style="dim")
                lines.append(_fit_line(continuation, width))
        if recovery is not None:
            ok = getattr(recovery, "ok", None)
            code = getattr(recovery, "code", None) or ""
            if ok is True:
                glyph, word, color = "✓", "recovery ok", STATE_STYLES["success"].color
            elif ok is False:
                glyph, word, color = (
                    "✗",
                    "recovery failed",
                    STATE_STYLES["failed"].color,
                )
            else:
                glyph, word, color = "·", "recovery turn", "dim"
            tail = Text("              ", style="dim")
            tail.append(f"{prefix}{glyph} {word}", style=color)
            if code:
                tail.append(f"  {code}", style="dim")
            lines.append(_fit_line(tail, width))
    return lines


def _controller_lines(node_view: Any, *, width: int) -> list[Text]:
    cycles = _total_cycles(node_view)
    if cycles <= 1:
        return []
    parts = [f"{cycles} cycles"]
    for run in _node_runs(node_view):
        if getattr(run, "reactivated", False):
            label = str(getattr(run, "label", "") or getattr(run, "run_id", ""))
            parts.append(f"{label} reactivated" if label else "reactivated")
    line = Text("CONTROLLER    ", style="dim")
    line.append(" · ".join(parts), style="dim")
    return [_fit_line(line, width)]


def _drift_lines(node_view: Any, *, width: int) -> list[Text]:
    seen: set[str] = set()
    lines: list[Text] = []
    for run in _node_runs(node_view):
        for entry in getattr(run, "drift", ()) or ():
            message = str(getattr(entry, "message", "") or "")
            if not message or message in seen:
                continue
            seen.add(message)
            budget = max(8, min(_FREE_TEXT_CAP, width - 4))
            line = Text("⚠ ", style=WARNING_COLOR)
            line.append(_shorten(message, budget), style=WARNING_COLOR)
            lines.append(_fit_line(line, width))
    return lines


def _diagnostic_lines(node_view: Any, *, width: int) -> list[Text]:
    seen: set[tuple[str, str]] = set()
    lines: list[Text] = []
    for run in _node_runs(node_view):
        for entry in getattr(run, "diagnostics", ()) or ():
            code = str(getattr(entry, "code", "") or "")
            message = str(getattr(entry, "message", "") or "")
            if not message or (code, message) in seen:
                continue
            seen.add((code, message))
            severity = str(getattr(entry, "severity", "") or "").lower()
            if severity == "error":
                color = STATE_STYLES["failed"].color
            elif severity in ("warning", "warn"):
                color = WARNING_COLOR
            else:
                color = "dim"
            budget = max(8, min(_FREE_TEXT_CAP, width - 4))
            line = Text("! " if severity == "error" else "· ", style=color)
            detail = f"{code} {message}".strip()
            line.append(_shorten(detail, budget), style=color)
            lines.append(_fit_line(line, width))
    return lines


def _run_ledger_entry(run: Any) -> tuple[str, str, str]:
    """Return ``(label, glyph, word)`` for one runs-ledger entry."""
    label = str(getattr(run, "label", "") or getattr(run, "run_id", "") or "run")
    disposition = str(getattr(run, "disposition", "") or "")
    reason = str(getattr(run, "reason", "") or "")
    key = disposition.strip().lower()
    if key == "ran":
        result = getattr(run, "result_status", None)
        if result:
            style = _overview_instance_style(str(result))
            return label, style.glyph, style.word
        return label, "✓", "ran"
    if key == "active":
        return label, STATE_STYLES["running"].glyph, "running"
    if key == "skipped":
        kind = ""
        if "handoff" in reason:
            marker = reason.split("handoff:", 1)[1] if "handoff:" in reason else ""
            kind = marker.split()[0].strip("· ") if marker else ""
            kind = f" · {kind} handoff" if kind else " · handoff"
        elif reason:
            kind = f" · {reason}"
        return label, "○", f"skipped{kind}"
    if key in ("not_reached", "not-reached"):
        return label, "–", "not reached"
    if key == "interrupted":
        return label, STATE_STYLES["interrupted"].glyph, "interrupted"
    if key == "unavailable":
        suffix = f" · {reason}" if reason else ""
        return label, "⚠", f"unavailable{suffix}"
    style = _run_disposition_style(disposition)
    suffix = f" · {reason}" if reason else ""
    return label, style.glyph, f"{style.word}{suffix}"


def _runs_lines(node_view: Any, *, width: int) -> list[Text]:
    runs = _node_runs(node_view)
    if not runs:
        return []
    show = len(runs) > 1 or any(
        str(getattr(run, "disposition", "") or "").strip().lower()
        in ("skipped", "not_reached", "not-reached", "unavailable", "interrupted")
        for run in runs
    )
    if not show:
        return []
    entries = [
        f"{label} {glyph} {word}"
        for label, glyph, word in (_run_ledger_entry(run) for run in runs)
    ]
    line = Text("RUNS          ", style="dim")
    line.append(" · ".join(entries), style="dim")
    lines = [_fit_line(line, width)]
    for run in runs:
        if str(getattr(run, "disposition", "") or "").strip().lower() != "skipped":
            continue
        label = str(getattr(run, "label", "") or getattr(run, "run_id", ""))
        explanation = Text(
            f"  ○ {label} skipped · handoff — {SKIPPED_EXPLANATION}"
            if label
            else f"  ○ skipped · handoff — {SKIPPED_EXPLANATION}",
            style="dim",
        )
        lines.append(_fit_line(explanation, width))
    return lines


def _unavailable_lines(node_view: Any, *, width: int) -> list[Text]:
    """Calm one-line reason when the RUNS ledger stays hidden.

    The ledger already covers every non-ran disposition, so this only fires
    for a lone ``ran``/``active`` run that still carries a reason worth
    surfacing.
    """
    runs = _node_runs(node_view)
    if len(runs) != 1:
        return []
    run = runs[0]
    key = str(getattr(run, "disposition", "") or "").strip().lower()
    if key not in ("ran", "active"):
        return []
    reason = str(getattr(run, "reason", "") or "")
    if not reason:
        return []
    style = _run_disposition_style(key)
    line = Text(f"{style.glyph} {style.word}", style="dim")
    budget = max(8, width - len(line.plain) - 3)
    line.append(f" · {_shorten(reason, budget)}", style="dim")
    return [_fit_line(line, width)]


def render_overview_preamble(node_view: Any, *, width: int = 120) -> list[Text]:
    """Render the Overview card preamble for a run-blocked card (plan §4.17).

    The preamble holds the node-level lines that belong above every run
    block: the header, the DAG-order plan rows, the controller line, and
    the CLI-pointer footer. Per-run declarations, drift, diagnostics and
    the runs ledger live inside each run's block instead.
    """
    width = max(20, int(width))
    durations = _instance_durations(node_view)
    lines = [_header_line(node_view, durations, width=width)]
    lines.extend(_plan_rows(node_view, durations, width=width))
    lines.extend(_controller_lines(node_view, width=width))
    return lines


def render_overview_ledger_lines(node_view: Any, *, width: int = 120) -> list[Text]:
    """Render the runs-ledger lines for runs without blocks (plan §4.17).

    In a run-blocked Overview card, ``active``/``ran``/``interrupted``
    runs live inside blocks; skipped, not-reached and unavailable runs
    appear only here, in the ledger, with the calm skipped explanation.
    """
    from .run_blocks import is_final_block_run

    width = max(20, int(width))
    runs = [run for run in _node_runs(node_view) if not is_final_block_run(run)]
    if not runs:
        return []
    entries = [
        f"{label} {glyph} {word}"
        for label, glyph, word in (_run_ledger_entry(run) for run in runs)
    ]
    line = Text("RUNS          ", style="dim")
    line.append(" · ".join(entries), style="dim")
    lines = [_fit_line(line, width)]
    for run in runs:
        if str(getattr(run, "disposition", "") or "").strip().lower() != "skipped":
            continue
        label = str(getattr(run, "label", "") or getattr(run, "run_id", ""))
        explanation = Text(
            f"  ○ {label} skipped · handoff — {SKIPPED_EXPLANATION}"
            if label
            else f"  ○ skipped · handoff — {SKIPPED_EXPLANATION}",
            style="dim",
        )
        lines.append(_fit_line(explanation, width))
    return lines


def render_overview_run_lines(run: Any, *, width: int = 120) -> list[Text]:
    """Render one run's Overview block body (plan §4.17).

    The body holds that run's ledger entry, its declaration timeline and
    recovery turn, its drift, and its run-level diagnostics. Skipped runs
    never earn blocks; their calm explanation stays in the node ledger.
    """
    width = max(20, int(width))
    label, glyph, word = _run_ledger_entry(run)
    lines = [_fit_line(Text(f"{label} {glyph} {word}", style="dim"), width)]
    lines.extend(_one_run_declaration_lines(run, width=width))
    lines.extend(_one_run_drift_lines(run, width=width))
    lines.extend(_one_run_diagnostic_lines(run, width=width))
    return lines


def _one_run_declaration_lines(run: Any, *, width: int) -> list[Text]:
    """Return the declaration timeline lines for one run."""
    lines: list[Text] = []
    for entry in getattr(run, "declarations", ()) or ():
        status = str(getattr(entry, "status", "") or "")
        style = _declaration_style(status)
        head = Text("DECLARATION   " if not lines else "              ", style="dim")
        head.append(f"{_clock_text(getattr(entry, 't', None))} ", style="dim")
        head.append(f"{style.glyph} {status}", style=style.color)
        code = getattr(entry, "code", None)
        if code:
            head.append(f"  {code}", style="dim")
        payload_count = getattr(entry, "payload_count", None)
        if isinstance(payload_count, bool):
            payload_count = None
        if payload_count is not None:
            try:
                head.append(f"  {int(payload_count)} payloads", style="dim")
            except (TypeError, ValueError):
                pass
        lines.append(_fit_line(head, width))
        first_line = getattr(entry, "first_line", None)
        if first_line:
            budget = max(8, min(_FREE_TEXT_CAP, width - 16))
            continuation = Text("              ", style="dim")
            continuation.append(_shorten(str(first_line), budget), style="dim")
            lines.append(_fit_line(continuation, width))
    recovery = getattr(run, "recovery_turn", None)
    if recovery is not None:
        ok = getattr(recovery, "ok", None)
        code = getattr(recovery, "code", None) or ""
        if ok is True:
            glyph, word, color = "✓", "recovery ok", STATE_STYLES["success"].color
        elif ok is False:
            glyph, word, color = (
                "✗",
                "recovery failed",
                STATE_STYLES["failed"].color,
            )
        else:
            glyph, word, color = "·", "recovery turn", "dim"
        tail = Text("              ", style="dim")
        tail.append(f"{glyph} {word}", style=color)
        if code:
            tail.append(f"  {code}", style="dim")
        lines.append(_fit_line(tail, width))
    return lines


def _one_run_drift_lines(run: Any, *, width: int) -> list[Text]:
    """Return the drift lines for one run."""
    seen: set[str] = set()
    lines: list[Text] = []
    for entry in getattr(run, "drift", ()) or ():
        message = str(getattr(entry, "message", "") or "")
        if not message or message in seen:
            continue
        seen.add(message)
        budget = max(8, min(_FREE_TEXT_CAP, width - 4))
        line = Text("⚠ ", style=WARNING_COLOR)
        line.append(_shorten(message, budget), style=WARNING_COLOR)
        lines.append(_fit_line(line, width))
    return lines


def _one_run_diagnostic_lines(run: Any, *, width: int) -> list[Text]:
    """Return the run-level diagnostic lines for one run."""
    seen: set[tuple[str, str]] = set()
    lines: list[Text] = []
    for entry in getattr(run, "diagnostics", ()) or ():
        code = str(getattr(entry, "code", "") or "")
        message = str(getattr(entry, "message", "") or "")
        if not message or (code, message) in seen:
            continue
        seen.add((code, message))
        severity = str(getattr(entry, "severity", "") or "").lower()
        if severity == "error":
            color = STATE_STYLES["failed"].color
        elif severity in ("warning", "warn"):
            color = WARNING_COLOR
        else:
            color = "dim"
        budget = max(8, min(_FREE_TEXT_CAP, width - 4))
        line = Text("! " if severity == "error" else "· ", style=color)
        detail = f"{code} {message}".strip()
        line.append(_shorten(detail, budget), style=color)
        lines.append(_fit_line(line, width))
    return lines


def render_overview_lines(node_view: Any, *, width: int = 120) -> list[Text]:
    """Render the Overview card body for *node_view* (plan §4.15).

    Sections mirror the plan mockup: header, DAG-order plan rows, the
    declaration timeline, ``CONTROLLER`` only when cycles exceed one, drift,
    run-level diagnostics, the runs ledger, calm hidden-ledger states, and
    CLI pointers. Every emitted line fits *width* printable characters.
    """
    width = max(20, int(width))
    durations = _instance_durations(node_view)
    lines = [_header_line(node_view, durations, width=width)]
    lines.extend(_plan_rows(node_view, durations, width=width))
    lines.extend(_declaration_lines(node_view, width=width))
    lines.extend(_controller_lines(node_view, width=width))
    lines.extend(_drift_lines(node_view, width=width))
    lines.extend(_diagnostic_lines(node_view, width=width))
    runs_lines = _runs_lines(node_view, width=width)
    if runs_lines:
        lines.extend(runs_lines)
    else:
        lines.extend(_unavailable_lines(node_view, width=width))
    lines.append(_fit_line(Text(OVERVIEW_FOOTER, style="dim"), width))
    return lines


__all__ = [
    "OVERVIEW_FOOTER",
    "SKIPPED_EXPLANATION",
    "render_overview_ledger_lines",
    "render_overview_lines",
    "render_overview_preamble",
    "render_overview_run_lines",
]
