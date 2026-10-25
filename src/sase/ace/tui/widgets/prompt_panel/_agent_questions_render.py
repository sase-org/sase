"""Pure Rich Text presenter for question-gate rounds.

This module renders :class:`NumberedQuestionRound` values (from
:mod:`sase.question_gate_turn.projection`) as Rich ``Text`` only: no
``Syntax`` or JSON renderables, so hint annotation and ``gate_phase_text``
keep working. It performs no I/O; callers inject ``now`` (a naive
local-time datetime like :func:`sase.core.time.local_now`) so tests can
pin the clock.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from rich.cells import cell_len
from rich.text import Text

from sase.core.time import get_timezone
from sase.gate_turn.naming import short_gate_turn_id
from sase.gate_turn.state import GATE_FAILURE_GLYPH_COLOR
from sase.question_gate_turn.projection import (
    NumberedQuestionRound,
    QuestionAnswerView,
    QuestionCancellationView,
    QuestionEntryView,
    QuestionOptionView,
    QuestionPolicyView,
    QuestionProvenanceView,
    QuestionRoundView,
)

from ...models.fold_state import FoldLevel

if TYPE_CHECKING:
    from ...models.agent_question_rounds import QuestionRoundStub

_PENDING_ACCENT = "#FFAF00"
_ANSWERED_ACCENT = "#5FD7FF"
_WARNING_STYLE = "bold #FFAF00"
_RECOMMENDED_STYLE = "bold #FFD75F"

_STATUS_WORDS: dict[str, tuple[str, str]] = {
    "pending": ("QUESTION", _PENDING_ACCENT),
    "settling": ("QUESTION", _PENDING_ACCENT),
    "answered": ("ANSWERED", _ANSWERED_ACCENT),
    "completed": ("ANSWERED", _ANSWERED_ACCENT),
    "timeout": ("QUESTION TIMED OUT", _PENDING_ACCENT),
    "timed_out": ("QUESTION TIMED OUT", _PENDING_ACCENT),
    "stopped": ("QUESTION CANCELLED", _PENDING_ACCENT),
    "cancelled": ("QUESTION CANCELLED", _PENDING_ACCENT),
    "failed": ("QUESTION FAILED", GATE_FAILURE_GLYPH_COLOR),
    "lost": ("QUESTION LOST", GATE_FAILURE_GLYPH_COLOR),
}
_UNKNOWN_STATUS_WORD = ("QUESTION UNKNOWN", "dim")

_PENDING_GATE_STATES = frozenset({"pending", "settling"})

_CHANNEL_LABELS = {
    "tui": "TUI",
    "telegram": "Telegram",
    "mobile": "mobile",
    "cli": "CLI",
}

_ONE_LINE_WIDTH = 100


class QuestionNumberCursor:
    """Accumulate continuous Q numbers across causal gate phases.

    Session Reply cards render every question gate phase in causal order;
    each phase takes its ``first_number`` from the cursor so questions
    number Q1…Qn continuously across rounds.
    """

    def __init__(self, start: int = 1) -> None:
        self._next = max(1, start)

    @property
    def next_number(self) -> int:
        """Return the number the next round's first question will take."""
        return self._next

    def take(self, count: int) -> int:
        """Return this round's first number and advance past ``count`` questions."""
        first = self._next
        self._next += max(0, count)
        return first


def _heading_gate_state(
    round: NumberedQuestionRound | QuestionRoundStub,
) -> str | None:
    if isinstance(round, NumberedQuestionRound):
        return round.view.gate_state
    return round.gate_state


def question_rounds_heading_suffix(
    rounds: Sequence[NumberedQuestionRound] | Sequence[QuestionRoundStub],
) -> Text:
    """Return a heading suffix like ``· 3 rounds · 1 awaiting answer``.

    Accepts the lane's full rounds or the zero-I/O first-paint stubs. Zero
    parts are omitted: an empty input renders empty, and a fully settled
    input renders only the round count.
    """
    text = Text()
    total = len(rounds)
    if total == 0:
        return text
    text.append(f" · {total} round{'s' if total != 1 else ''}", style="dim")
    awaiting = sum(
        1 for item in rounds if _heading_gate_state(item) in _PENDING_GATE_STATES
    )
    if awaiting:
        text.append(f" · {awaiting} awaiting answer", style="dim")
    return text


def _as_local(unix: float | None) -> datetime | None:
    if not isinstance(unix, (int, float)) or isinstance(unix, bool):
        return None
    try:
        return datetime.fromtimestamp(unix, tz=get_timezone()).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def _short_duration(seconds: float) -> str:
    """Format a duration compactly, dropping zero units (``23h``, ``3m``)."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return "".join(parts)


def _status_word(status: str) -> tuple[str, str]:
    return _STATUS_WORDS.get(status, _UNKNOWN_STATUS_WORD)


def _auto_policy_text(policy: QuestionPolicyView | None) -> str:
    bits: list[str] = []
    if policy is not None:
        if policy.profile:
            bits.append(policy.profile)
        if policy.rule and policy.value:
            bits.append(f"{policy.rule}={policy.value}")
        elif policy.rule:
            bits.append(policy.rule)
        elif policy.value:
            bits.append(policy.value)
    base = f"⚠ auto policy ({' · '.join(bits)})" if bits else "⚠ auto policy"
    return f"{base} · no human"


def _unknown_actor_text(status: str) -> str:
    if status == "answered":
        return "answered (source unknown)"
    return "source unknown"


def _provenance_text(view: QuestionRoundView) -> str | None:
    provenance = view.provenance
    if provenance is None:
        return _unknown_actor_text(view.status)
    actor = provenance.actor
    if actor == "auto_policy":
        return _auto_policy_text(provenance.policy)
    if actor == "human":
        label = _CHANNEL_LABELS.get(provenance.channel or "")
        return f"human via {label}" if label else "human"
    if actor == "agent":
        return f"agent via {provenance.channel or 'unknown'}"
    return _unknown_actor_text(view.status)


def _provenance_style(view: QuestionRoundView) -> str:
    if view.provenance is not None and view.provenance.actor == "auto_policy":
        return _WARNING_STYLE
    return ""


def _responded_at(provenance: QuestionProvenanceView | None) -> datetime | None:
    if provenance is None:
        return None
    return _as_local(provenance.responded_at_unix)


def _cancellation_detail(cancellation: QuestionCancellationView | None) -> str:
    """Return ``reason · source`` for a cancelled round (empty when unknown)."""
    if cancellation is None:
        return ""
    return " · ".join(
        part for part in (cancellation.reason, cancellation.source) if part
    )


def _header_segments(
    view: QuestionRoundView,
    now: datetime,
    deadline_unix: float | None,
) -> list[tuple[str, str]]:
    """Return the round header's trailing segments as ``(text, style)`` pairs."""
    segments: list[tuple[str, str]] = []
    if view.status == "pending":
        segments.append(("awaiting answer", ""))
        asked = _as_local(view.asked_at_unix)
        if asked is not None:
            segments.append((f"asked {asked:%H:%M}", ""))
        deadline = _as_local(deadline_unix)
        if deadline is not None:
            remaining = (deadline - now).total_seconds()
            if remaining > 0:
                segments.append((f"{_short_duration(remaining)} left", ""))
        return segments
    if view.status == "answered":
        provenance = _provenance_text(view)
        if provenance is not None:
            segments.append((provenance, _provenance_style(view)))
        asked = _as_local(view.asked_at_unix)
        responded = _responded_at(view.provenance)
        if asked is not None and responded is not None and responded >= asked:
            elapsed = (responded - asked).total_seconds()
            segments.append((f"{_short_duration(elapsed)} after asking", ""))
        if view.gate_state == "failed":
            segments.append(("follow-up failed", _WARNING_STYLE))
        return segments
    provenance = _provenance_text(view)
    if provenance is not None and view.provenance is not None:
        segments.append((provenance, _provenance_style(view)))
    reason = _cancellation_detail(view.cancellation)
    if reason:
        segments.append((reason, ""))
    return segments


def _round_header(
    round: NumberedQuestionRound,
    *,
    now: datetime,
    label_width: int,
) -> Text:
    """Return one round's header line (member label, status word, segments)."""
    header = Text()
    header.append(round.member_label.ljust(label_width))
    word, accent = _status_word(round.view.status)
    header.append("  ")
    header.append(word, style=f"bold {accent}" if accent != "dim" else "dim")
    for segment, style in _header_segments(round.view, now, round.deadline_unix):
        header.append("  ")
        header.append(segment, style=style or None)
    header.append("\n")
    return header


def _collapse_single_line(value: str) -> str:
    return " ".join(value.split())


def _clip_line(text: Text, width: int = _ONE_LINE_WIDTH) -> Text:
    """Truncate *text* in place so its plain form fits ``width`` cells."""
    if cell_len(text.plain) > width:
        text.truncate(width, overflow="ellipsis")
    return text


def _answer_feedback(answer: QuestionAnswerView | None) -> str:
    if answer is None:
        return ""
    return (answer.custom_feedback or "").strip()


def _answer_text(entry: QuestionEntryView) -> tuple[str | None, str | None]:
    """Return the settled answer display and its marker (either may be None)."""
    answer = entry.answer
    if answer is None:
        return None, None
    match = entry.recommendation_match
    feedback = _answer_feedback(answer)
    if match == "free_text":
        return f'"{answer.custom_feedback or ""}"', None
    if match == "other_text":
        return (f'"{feedback}"' if feedback else "Other"), "≠★"
    labels = ", ".join(answer.selected) if answer.selected else "—"
    if match == "followed":
        return labels, "★"
    if match == "different_option":
        return labels, "≠★"
    return labels, None


def _question_title(entry: QuestionEntryView) -> str:
    if entry.header:
        return entry.header
    return _collapse_single_line(entry.question)


def _question_line(
    entry: QuestionEntryView,
    number: int,
    *,
    pending: bool,
    clip: bool,
) -> Text:
    """Return one question line: clipped in EXPANDED, whole in FULLY_EXPANDED."""
    line = Text()
    line.append("  ")
    line.append(f"Q{number} ")
    title = _question_title(entry)
    line.append(_collapse_single_line(title) if clip else title)
    if entry.answer is None:
        if not entry.options and pending:
            line.append(" (free text, no recommendation)", style="dim")
        elif entry.options and pending:
            pass
        else:
            line.append(" → ")
            line.append("no answer", style="dim")
    else:
        answer, marker = _answer_text(entry)
        line.append(" → ")
        line.append(answer or "", style="dim" if pending else None)
        if marker is not None and not pending:
            line.append(f" {marker}", style=_marker_style(marker))
    if clip:
        _clip_line(line)
    line.append("\n")
    return line


def _marker_style(marker: str) -> str:
    if marker == "★":
        return _RECOMMENDED_STYLE
    return _WARNING_STYLE


def _options_line(entry: QuestionEntryView) -> Text | None:
    """Return the focus round's inline option list, or None when option-less."""
    if not entry.options:
        return None
    line = Text()
    line.append("     ")
    for index, option in enumerate(entry.options):
        if index:
            line.append("  ·  ", style="dim")
        if index == entry.recommended_index:
            line.append(
                f"★ {option.label} (recommended, listed first)",
                style=_RECOMMENDED_STYLE,
            )
        else:
            line.append(option.label)
    _clip_line(line)
    line.append("\n")
    return line


def _degraded_line(view: QuestionRoundView) -> Text:
    """Return the dim fallback line for partial/unavailable rounds."""
    line = Text()
    line.append("  answer details unavailable", style="dim")
    if view.gate_id:
        line.append(
            f" — sase gate show {short_gate_turn_id(view.gate_id)}",
            style="dim",
        )
    line.append("\n")
    return line


def _is_degraded(view: QuestionRoundView) -> bool:
    return view.data_state in ("partial", "unavailable")


def _append_full_option(
    text: Text,
    option: QuestionOptionView,
    *,
    recommended: bool,
) -> None:
    """Append one FULLY_EXPANDED option line, starring the recommended one."""
    text.append("    ")
    if recommended:
        text.append("★ ", style=_RECOMMENDED_STYLE)
        text.append(option.label, style=_RECOMMENDED_STYLE)
        text.append(" (recommended, listed first)", style="dim")
    else:
        text.append("· ", style="dim")
        text.append(option.label)
    if option.description:
        text.append(f" — {option.description}", style="dim")
    text.append("\n")


def _append_full_question(
    text: Text,
    entry: QuestionEntryView,
    number: int,
    *,
    pending: bool,
) -> None:
    """Append one FULLY_EXPANDED question block (never clipped, wraps)."""
    text.append_text(_question_line(entry, number, pending=pending, clip=False))
    if entry.header and entry.header != entry.question and entry.question:
        for raw in entry.question.rstrip().splitlines() or [""]:
            text.append(f"    {raw.rstrip()}\n", style="dim")
    for index, option in enumerate(entry.options):
        _append_full_option(text, option, recommended=index == entry.recommended_index)
    feedback = _answer_feedback(entry.answer)
    if feedback and entry.recommendation_match == "other_text":
        text.append(f'    - Other: "{feedback}"\n', style="dim")
    elif (
        feedback
        and entry.recommendation_match not in ("free_text", None)
        and "Other" not in (entry.answer.selected if entry.answer else ())
    ):
        text.append(f'    - Comment: "{feedback}"\n', style="dim")


def _append_full_round_extras(
    text: Text,
    round: NumberedQuestionRound,
) -> None:
    """Append a FULLY_EXPANDED round's note, cancellation, and exact times."""
    view = round.view
    if view.global_note:
        text.append("  ")
        text.append(f'Note: "{view.global_note}"\n', style="dim")
    cancellation = view.cancellation
    detail = _cancellation_detail(cancellation)
    if cancellation is not None and detail:
        text.append("  ")
        cancelled = _as_local(cancellation.cancelled_at_unix)
        stamp = f" at {cancelled:%Y-%m-%d %H:%M:%S}" if cancelled is not None else ""
        text.append(f"Cancelled: {detail}{stamp}\n", style="dim")
    asked = _as_local(view.asked_at_unix)
    responded = _responded_at(view.provenance)
    if asked is not None or responded is not None:
        text.append("  ")
        stamps = []
        if asked is not None:
            stamps.append(f"Asked: {asked:%Y-%m-%d %H:%M:%S}")
        if responded is not None:
            stamps.append(f"Answered: {responded:%Y-%m-%d %H:%M:%S}")
        text.append(" · ".join(stamps) + "\n", style="dim")


def _is_pending_round(round: NumberedQuestionRound) -> bool:
    return round.view.status == "pending"


def _focus_round(
    rounds: Sequence[NumberedQuestionRound],
) -> NumberedQuestionRound | None:
    """Return the pending round, else the latest round, else None."""
    for round in rounds:
        if _is_pending_round(round):
            return round
    return rounds[-1] if rounds else None


def render_question_rounds(
    rounds: Sequence[NumberedQuestionRound],
    *,
    level: FoldLevel,
    now: datetime,
) -> Text:
    """Return the section body for *rounds* in causal order.

    COLLAPSED renders no body; the mount shows only the heading.
    EXPANDED renders one header line per round and one line per question,
    plus the focus round's option list. FULLY_EXPANDED expands every
    round with wrapped text, descriptions, comments, notes, and times.
    """
    text = Text()
    ordered = list(rounds)
    if level == FoldLevel.COLLAPSED or not ordered:
        return text
    if level == FoldLevel.FULLY_EXPANDED:
        label_width = max(cell_len(item.member_label) for item in ordered)
        for item in ordered:
            pending = _is_pending_round(item)
            text.append_text(_round_header(item, now=now, label_width=label_width))
            if _is_degraded(item.view) and not item.view.entries:
                text.append_text(_degraded_line(item.view))
                continue
            number = item.first_number
            for entry in item.view.entries:
                _append_full_question(text, entry, number, pending=pending)
                number += 1
            _append_full_round_extras(text, item)
            if _is_degraded(item.view):
                text.append_text(_degraded_line(item.view))
        return text
    focus = _focus_round(ordered)
    label_width = max(cell_len(item.member_label) for item in ordered)
    for item in ordered:
        pending = _is_pending_round(item)
        text.append_text(_round_header(item, now=now, label_width=label_width))
        if _is_degraded(item.view) and not item.view.entries:
            text.append_text(_degraded_line(item.view))
            continue
        number = item.first_number
        for entry in item.view.entries:
            text.append_text(_question_line(entry, number, pending=pending, clip=True))
            if item is focus:
                options = _options_line(entry)
                if options is not None:
                    text.append_text(options)
            number += 1
        if _is_degraded(item.view):
            text.append_text(_degraded_line(item.view))
    return text


def render_question_round(
    round: NumberedQuestionRound,
    *,
    level: FoldLevel,
    now: datetime,
) -> Text:
    """Return the single-round render for GATE sections and Reply phases."""
    return render_question_rounds((round,), level=level, now=now)


def render_question_stub_lines(
    stubs: Sequence[QuestionRoundStub],
) -> Text:
    """Return the zero-I/O first-paint body: one dim line per stub.

    Each line carries the member label, the gate-state status word, and the
    gate label. Full question detail arrives later through the ``questions``
    lane; this path performs no bundle reads.
    """
    text = Text()
    if not stubs:
        return text
    width = max(cell_len(stub.member_label) for stub in stubs)
    for stub in stubs:
        word, _accent = _status_word(stub.gate_state or "unknown")
        line = Text()
        line.append(stub.member_label.ljust(width))
        line.append("  ")
        line.append(word)
        title = stub.gate_label or stub.gate_id or ""
        if title:
            line.append("  ")
            line.append(title)
        _clip_line(line)
        start = len(text)
        text.append_text(line)
        text.append("\n")
        text.stylize("dim", start, len(text))
    return text


__all__ = [
    "QuestionNumberCursor",
    "question_rounds_heading_suffix",
    "render_question_round",
    "render_question_rounds",
    "render_question_stub_lines",
]
