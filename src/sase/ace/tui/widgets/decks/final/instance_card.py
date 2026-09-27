"""Generic provider-neutral FINAL instance cards (epic sase-1b2, ``final-instance-cards``).

Every finalizer instance renders through :func:`build_instance_card_renderables`
from typed projection data only — no provider-specific branches live here.
Provider flavor comes from :mod:`enrichers`, which returns strictly
additional renderables. A hypothetical plugin instance therefore renders
completely through this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text

from sase.finalizers.view_vocabulary import (
    FAILURE_COLOR,
    FINAL_GLYPH,
    INSTANCE_STATUS_STYLES,
    REFUSED_COLOR,
    STATE_STYLES,
    SUCCESS_COLOR,
    WARNING_COLOR,
    instance_style,
)

#: Default card width used for truncating long single-line values.
INSTANCE_CARD_WIDTH = 120

#: Cap for deferral paths shown inline before the ``+N more`` suffix.
DEFERRAL_PATHS_SHOWN = 5


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


def _fit(line: str, width: int) -> str:
    """Truncate ``line`` to ``width`` cells with an ellipsis marker."""
    width = max(20, int(width))
    if len(line) <= width:
        return line
    return line[: max(0, width - 1)] + "…"


def _format_duration(seconds: Any) -> str | None:
    try:
        total = float(seconds)
    except (TypeError, ValueError):
        return None
    if total < 0:
        return None
    if total >= 60:
        return f"{int(total // 60)}m{int(total % 60):02d}s"
    return f"{total:.1f}s"


def _clock_text(moment: Any) -> str | None:
    if isinstance(moment, bool):
        return None
    if isinstance(moment, (int, float)):
        try:
            return datetime.fromtimestamp(moment).strftime("%H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _status_glyph_word(status: Any) -> tuple[str, str, str | None]:
    """Return ``(glyph, word, color)`` for a per-instance projection status.

    Unknown statuses render as a neutral ``•`` (plan §3.2 readers rule)
    instead of borrowing a wrong label.
    """
    raw = "" if status is None else str(status)
    key = INSTANCE_STATUS_STYLES.get(raw)
    if key is None:
        style = STATE_STYLES.get(raw)
        if style is not None:
            return style.glyph, style.word, style.color
        return "•", raw or "unknown", None
    style = instance_style(raw)
    return style.glyph, style.word, style.color


def _styled_span(text: Text, value: str, color: str | None) -> None:
    if color:
        text.append(value, style=color)
    else:
        text.append(value)


def _build_instance_header(
    instance_id: str,
    provider_ref: str | None,
    status: Any,
    *,
    attempt: Any = None,
    max_attempts: Any = None,
    warnings: int = 0,
    width: int = INSTANCE_CARD_WIDTH,
) -> Text:
    """Return the card header line for one instance."""
    glyph, word, color = _status_glyph_word(status)
    header = Text()
    header.append(str(instance_id), style="bold")
    if provider_ref:
        header.append(f" · {provider_ref}", style="dim")
    status_part = f"  {glyph} {word}" if glyph else f"  {word}"
    _styled_span(header, status_part, f"bold {color}" if color else "bold")
    try:
        current = int(attempt) if attempt is not None else 0
        total = int(max_attempts) if max_attempts is not None else 0
    except (TypeError, ValueError):
        current, total = 0, 0
    if total and total > 1:
        header.append(f" · attempt {current}/{total}", style="dim")
    try:
        warn_count = int(warnings or 0)
    except (TypeError, ValueError):
        warn_count = 0
    if warn_count > 0:
        header.append(f"  ⚠{warn_count}", style=f"dim {WARNING_COLOR}")
    plain = _fit(header.plain, width)
    if plain != header.plain:
        clipped = Text(plain)
        return clipped
    return header


def _build_context_lines(
    *,
    selection_reason: str | None,
    after: Any,
    trigger_kind: str | None,
    submission_required: Any,
    obligation_count: Any,
    payload_summary: Any,
    width: int = INSTANCE_CARD_WIDTH,
) -> list[Text]:
    """Return the why/trigger/declared context lines for one instance."""
    lines: list[Text] = []
    why = Text("why ", style="dim")
    why.append(str(selection_reason or "selected"))
    after_ids = _text_list(after)
    if after_ids:
        why.append(f" · after {', '.join(after_ids)}", style="dim")
    lines.append(Text(_fit(why.plain, width)))
    trigger = Text("trigger ", style="dim")
    trigger.append(str(trigger_kind or "scheduled"))
    if submission_required:
        trigger.append(" · submission required", style="dim")
    try:
        obligations = int(obligation_count or 0)
    except (TypeError, ValueError):
        obligations = 0
    if obligations > 0:
        trigger.append(
            f" · {obligations} obligation{'s' if obligations != 1 else ''}",
            style="dim",
        )
    lines.append(Text(_fit(trigger.plain, width)))
    summary: dict[str, str] = {}
    if isinstance(payload_summary, dict):
        summary = {str(key): str(item) for key, item in payload_summary.items()}
    declared = Text("declared ", style="dim")
    if summary:
        parts = []
        for key in sorted(summary):
            value = summary[key]
            if len(value) > 40:
                value = value[:39] + "…"
            parts.append(f"{key}={value}")
        declared.append(", ".join(parts))
    else:
        declared.append("—", style="dim")
    lines.append(Text(_fit(declared.plain, width)))
    return lines


def _attempt_header_text(attempt_number: Any, attempt: Any, *, collapsed: bool) -> str:
    number = attempt_number
    try:
        number = int(attempt_number)
    except (TypeError, ValueError):
        pass
    status = getattr(attempt, "status", "") or ""
    glyph, word, _ = _status_glyph_word(status)
    segments = [f"attempt {number}"]
    clock = _clock_text(getattr(attempt, "started_at", None))
    if clock and not collapsed:
        segments.append(clock)
    duration = _format_duration(getattr(attempt, "duration_seconds", None))
    if duration:
        segments.append(duration)
    code = getattr(attempt, "code", None)
    tail = f"{glyph} {code}" if code else f"{glyph} {word}"
    segments.append(tail.strip())
    if collapsed:
        return " · ".join(str(part) for part in segments if part)
    return " ─── ".join(str(part) for part in segments if part)


_STEP_STATE_GLYPHS = {
    "ok": "✓",
    "fail": "✗",
    "warn": "⚠",
    "start": "▶",
}

_STEP_STATE_COLORS = {
    "ok": SUCCESS_COLOR,
    "fail": FAILURE_COLOR,
    "warn": WARNING_COLOR,
    "start": "dim",
}


def _operation_outcome(operation: Any) -> tuple[str, str | None]:
    """Return ``(glyph, color)`` for one operation's outcome."""
    if getattr(operation, "timed_out", False):
        return "!", WARNING_COLOR
    returncode = getattr(operation, "returncode", None)
    if returncode is None or isinstance(returncode, bool):
        return "▶", "#FFD700"
    try:
        code = int(returncode)
    except (TypeError, ValueError):
        return "▶", "#FFD700"
    if code == 0:
        return "✓", SUCCESS_COLOR
    return "✗", FAILURE_COLOR


def _build_operation_lines(
    operation: Any, *, width: int = INSTANCE_CARD_WIDTH
) -> list[Text]:
    """Return the lines for one operation plus its indented steps."""
    lines: list[Text] = []
    glyph, color = _operation_outcome(operation)
    label = getattr(operation, "label", None) or getattr(operation, "op", "") or ""
    line = Text()
    _styled_span(
        line, f"{glyph} {label}".rstrip(), f"bold {color}" if color else "bold"
    )
    returncode = getattr(operation, "returncode", None)
    if isinstance(returncode, int) and not isinstance(returncode, bool):
        line.append(f"  exit {returncode}", style="dim")
    duration = _format_duration(getattr(operation, "duration_seconds", None))
    if duration:
        line.append(f" · {duration}", style="dim")
    if getattr(operation, "timed_out", False):
        line.append(" · timed out", style=WARNING_COLOR)
    lines.append(Text(_fit(line.plain, width)))
    steps = list(getattr(operation, "steps", ()) or ())
    warned = [step for step in steps if str(getattr(step, "state", "")) == "warn"]
    shown = [step for step in steps if str(getattr(step, "state", "")) != "warn"]
    for step in shown:
        state = str(getattr(step, "state", "") or "")
        mark = _STEP_STATE_GLYPHS.get(state, "·")
        step_color = _STEP_STATE_COLORS.get(state)
        entry = Text(f"    {mark} {getattr(step, 'step', '') or ''}")
        detail = getattr(step, "detail", None)
        if detail:
            entry.append(f" — {detail}", style="dim")
        if step_color:
            try:
                entry.stylize(step_color, 4, 5)
            except Exception:
                pass
        lines.append(Text(_fit(entry.plain, width)))
    if warned:
        first = str(getattr(warned[0], "step", "") or "")
        summary = f"    ⚠ {len(warned)} warning{'s' if len(warned) != 1 else ''}"
        if first:
            summary += f" ({first})"
        summary += " ›"
        entry = Text(_fit(summary, width), style=WARNING_COLOR)
        lines.append(entry)
    if getattr(operation, "steps_truncated", False):
        lines.append(Text("    … steps truncated", style="dim"))
    return lines


def _render_evidence_value(evidence: Any) -> str:
    """Return the typed display value for one evidence record."""
    value = getattr(evidence, "display", None) or getattr(evidence, "value", "")
    value = "" if value is None else str(value)
    kind = getattr(evidence, "evidence_type", None) or getattr(evidence, "type", None)
    kind = "" if kind is None else str(kind)
    if kind == "sha":
        short = value[:7] if len(value) >= 7 else value
        return f"{short}  ↗ commit view"
    if kind == "exit_code":
        return f"exit {value}"
    if kind == "duration":
        duration = _format_duration(value)
        return duration if duration is not None else value
    return value


def _build_evidence_lines(
    evidence_items: Any, *, headline: Any = None, width: int = INSTANCE_CARD_WIDTH
) -> list[Text]:
    """Return the typed evidence lines plus the headline evidence line."""
    lines: list[Text] = []
    for evidence in evidence_items or ():
        kind = getattr(evidence, "kind", "") or ""
        rendered = _render_evidence_value(evidence)
        etype = getattr(evidence, "evidence_type", None) or getattr(
            evidence, "type", None
        )
        line = Text(f"  {kind}: {rendered}".rstrip())
        if str(etype) == "exit_code":
            try:
                failed = int(str(getattr(evidence, "value", ""))) != 0
            except (TypeError, ValueError):
                failed = False
            line.stylize(FAILURE_COLOR if failed else SUCCESS_COLOR)
        lines.append(Text(_fit(line.plain, width)))
    if headline is not None:
        kind = getattr(headline, "kind", "") or ""
        rendered = _render_evidence_value(headline)
        lines.append(Text(_fit(f"  ★ headline {kind}: {rendered}".rstrip(), width)))
    return lines


def _build_diagnostic_lines(
    diagnostics: Any, *, width: int = INSTANCE_CARD_WIDTH
) -> list[Text]:
    """Return deduped diagnostic lines; superseded ones never paint red."""
    lines: list[Text] = []
    for diagnostic in diagnostics or ():
        severity = str(getattr(diagnostic, "severity", "") or "")
        code = str(getattr(diagnostic, "code", "") or "")
        message = str(getattr(diagnostic, "message", "") or "")
        if severity == "error":
            glyph, color = "✗", FAILURE_COLOR
        elif severity == "warning":
            glyph, color = "⚠", WARNING_COLOR
        elif severity == "superseded":
            glyph, color = "·", "dim"
        else:
            glyph, color = "·", None
        label = f"  {glyph} {code}: {message}" if code else f"  {glyph} {message}"
        if severity == "superseded":
            label += " (superseded)"
        line = Text(_fit(label.strip(), width))
        if color:
            line.stylize(color)
        lines.append(line)
    return lines


def _build_log_lines(
    instance_id: str, operations: Any, *, width: int = INSTANCE_CARD_WIDTH
) -> list[Text]:
    """Return the ``logs … v to open`` line for an instance's operations."""
    parts: list[str] = []
    for operation in operations or ():
        for log in getattr(operation, "logs", ()) or ():
            name = str(getattr(log, "name", "") or "")
            if not name:
                continue
            count = getattr(log, "line_count", None)
            if isinstance(count, int) and not isinstance(count, bool):
                parts.append(f"finalizers/{instance_id}/{name} ({count} lines)")
            else:
                parts.append(f"finalizers/{instance_id}/{name}")
    if not parts:
        return []
    seen: list[str] = []
    for part in parts:
        if part not in seen:
            seen.append(part)
    return [Text(_fit(f"  logs  {' · '.join(seen)}   v to open", width), style="dim")]


def _build_protocol_lines(
    protocol_files: Any, *, width: int = INSTANCE_CARD_WIDTH
) -> list[Text]:
    """Return the ``protocol … v to open`` line for plugin envelopes."""
    names = _text_list(protocol_files)
    if not names:
        return []
    return [
        Text(_fit(f"  protocol {' · '.join(names)}   v to open", width), style="dim")
    ]


def _build_terminal_state_lines(
    run_instance: Any, *, width: int = INSTANCE_CARD_WIDTH
) -> list[Text]:
    """Return the calm refused/deferred/not-run and failure-reason lines."""
    lines: list[Text] = []
    status = str(getattr(run_instance, "status", "") or "")
    refusal = getattr(run_instance, "refusal_reason", None)
    if status == "refused":
        detail = f"  ⊘ refused: {refusal}" if refusal else "  ⊘ refused"
        lines.append(Text(_fit(detail, width), style=REFUSED_COLOR))
    deferral = getattr(run_instance, "deferral", None)
    if status == "deferred" and deferral is not None:
        reason = str(getattr(deferral, "reason", "") or "")
        paths = _text_list(getattr(deferral, "paths", ()))
        shown = paths[:DEFERRAL_PATHS_SHOWN]
        suffix = ""
        if len(paths) > len(shown):
            suffix = f" +{len(paths) - len(shown)} more"
        detail = f"{reason} · {', '.join(shown)}{suffix}".strip(" ·")
        line = Text(f"  ⏸ deferred: {detail}".rstrip(), style=WARNING_COLOR)
        lines.append(Text(_fit(line.plain, width)))
    blocked = getattr(run_instance, "blocked_by", None)
    waiting = getattr(run_instance, "waiting_on", None)
    if status in ("not_run", "not_triggered", "waiting", "planned", "skipped"):
        glyph, word, _ = _status_glyph_word(status)
        detail = ""
        if blocked:
            detail = f" · blocked by {blocked}"
        elif waiting:
            detail = f" · after {waiting}"
        lines.append(Text(_fit(f"  {glyph} {word}{detail}", width), style="dim"))
    failure = getattr(run_instance, "failure_reason", None)
    if failure and status in ("failed",):
        lines.append(Text(_fit(f"  ✗ {failure}", width), style=FAILURE_COLOR))
    return lines


def _attempt_number(attempt: Any, fallback: int) -> int:
    try:
        return int(getattr(attempt, "attempt", fallback))
    except (TypeError, ValueError):
        return fallback


def _build_attempt_sections(
    run_instance: Any, *, width: int = INSTANCE_CARD_WIDTH
) -> list[Text]:
    """Return attempt sections: expanded latest, one-line older attempts.

    There is no interactive per-attempt fold store on the FINAL deck yet,
    so the rule is static: the latest attempt (and a failing latest
    attempt, which is the same slot) expands, every older attempt
    collapses to one summary line. A future fold store hooks in here and
    must never have an explicit user fold overridden by this default.
    """
    attempts = list(getattr(run_instance, "attempts", ()) or ())
    operations = list(getattr(run_instance, "operations", ()) or ())
    lines: list[Text] = []
    if not attempts:
        for operation in operations:
            lines.extend(_build_operation_lines(operation, width=width))
        return lines
    ordered = sorted(attempts, key=lambda item: _attempt_number(item, 0))
    *older, latest = ordered
    ops_by_attempt: dict[Any, list[Any]] = {}
    unscoped: list[Any] = []
    for operation in operations:
        key = getattr(operation, "attempt", None)
        if key is None:
            unscoped.append(operation)
        else:
            ops_by_attempt.setdefault(key, []).append(operation)
    for attempt in older:
        number = _attempt_number(attempt, 0)
        header = _attempt_header_text(number, attempt, collapsed=True)
        lines.append(Text(_fit(f"  ─── {header} ───", width), style="dim"))
    number = _attempt_number(latest, 0)
    header = _attempt_header_text(number, latest, collapsed=False)
    lines.append(Text(_fit(f"  ─── {header} ───", width), style="dim"))
    scoped = list(ops_by_attempt.get(number, []))
    for operation in unscoped:
        if operation not in scoped:
            scoped.append(operation)
    for operation in scoped:
        lines.extend(_build_operation_lines(operation, width=width))
    return lines


def _run_appearances(node_item: Any, runs: Any) -> list[tuple[str | None, Any]]:
    """Return ``(run_label, run_instance)`` pairs for one node instance."""
    instance_id = str(getattr(node_item, "instance_id", "") or "")
    pairs: list[tuple[str | None, Any]] = []
    for run in runs or ():
        label = getattr(run, "label", None) or getattr(run, "run_id", None)
        for item in getattr(run, "instances", ()) or ():
            if str(getattr(item, "instance_id", "") or "") == instance_id:
                pairs.append((str(label) if label else None, item))
    return pairs


def build_instance_card_renderables(
    node_item: Any,
    runs: Any,
    *,
    width: int = INSTANCE_CARD_WIDTH,
) -> tuple[Any, ...]:
    """Return the generic provider-neutral body for one instance card."""
    instance_id = str(getattr(node_item, "instance_id", "") or "")
    provider_ref = getattr(node_item, "provider_ref", None)
    provider_ref = str(provider_ref) if provider_ref else None
    status = getattr(node_item, "status", None)
    pairs = _run_appearances(node_item, runs)
    detail_items = [item for _, item in pairs]
    attempt: Any = None
    max_attempts: Any = None
    warnings = 0
    for item in detail_items:
        candidate = getattr(item, "max_attempts", None)
        try:
            if candidate is not None and int(candidate) > int(max_attempts or 0):
                max_attempts = candidate
                attempt = getattr(item, "attempt", None)
        except (TypeError, ValueError):
            pass
        try:
            warnings = max(warnings, int(getattr(item, "warnings", 0) or 0))
        except (TypeError, ValueError):
            pass
    renderables: list[Any] = [
        _build_instance_header(
            instance_id or "finalizer",
            provider_ref,
            status,
            attempt=attempt,
            max_attempts=max_attempts,
            warnings=warnings,
            width=width,
        )
    ]
    first = detail_items[0] if detail_items else None
    renderables.extend(
        _build_context_lines(
            selection_reason=getattr(node_item, "selection_reason", None)
            or (
                getattr(first, "selection_reason", None) if first is not None else None
            ),
            after=getattr(node_item, "after", None)
            or (getattr(first, "after", None) if first is not None else None),
            trigger_kind=getattr(first, "trigger_kind", None)
            if first is not None
            else None,
            submission_required=getattr(first, "submission_required", False)
            if first is not None
            else False,
            obligation_count=getattr(first, "obligation_count", 0)
            if first is not None
            else 0,
            payload_summary=getattr(first, "payload_summary", {})
            if first is not None
            else {},
            width=width,
        )
    )
    if not pairs:
        glyph, word, _ = _status_glyph_word(status)
        renderables.append(Text(f"  {glyph} {word}", style="dim"))
        return tuple(renderables)
    multi_run = len(pairs) > 1
    for label, item in pairs:
        if multi_run and label:
            renderables.append(Text(f"  ── {label} ──", style="dim"))
        renderables.extend(_build_attempt_sections(item, width=width))
        evidence = list(getattr(item, "evidence", ()) or ())
        headline = getattr(item, "headline", None)
        renderables.extend(
            _build_evidence_lines(evidence, headline=headline, width=width)
        )
        renderables.extend(
            _build_diagnostic_lines(getattr(item, "diagnostics", ()), width=width)
        )
        renderables.extend(_build_terminal_state_lines(item, width=width))
        renderables.extend(
            _build_log_lines(instance_id, getattr(item, "operations", ()), width=width)
        )
        renderables.extend(
            _build_protocol_lines(getattr(item, "protocol_files", ()), width=width)
        )
    renderables.append(
        Text(f"  {FINAL_GLYPH} export with E · search with ,/", style="dim")
    )
    return tuple(renderables)


__all__ = [
    "DEFERRAL_PATHS_SHOWN",
    "INSTANCE_CARD_WIDTH",
    "build_instance_card_renderables",
]
