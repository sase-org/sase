"""Bead-flavored snooze picker for the Artifacts Beads pane.

The notification snooze modal answers "how long do I not want to see this
row"; a bead snooze answers "when should this work come back, and why did I
defer it". The two share :class:`DurationChoiceModal` so the keys and the
custom-duration field behave identically, but the presets here are measured
in the days a deferred task actually waits, the custom field accepts the
shared ``"<duration> [+<N>]"`` form every bead snooze surface accepts, and an
always-visible reason field records the "why" the wake gate later shows back.

An already-snoozed bead opens the same modal in re-snooze mode: the title
names the wake time it is replacing, and an extra choice cancels the snooze
outright rather than pushing it further out.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sase.bead.model import Issue
from sase.bead.snooze_presentation import snooze_summary
from sase.bead.snooze_time import parse_snooze_request
from sase.core.time import get_timezone

from .duration_choice_modal import (
    DurationAnnotation,
    DurationChoice,
    DurationChoiceModal,
)


@dataclass(frozen=True)
class BeadSnoozeRequest:
    """One resolved bead snooze: a wake time, a +1 target, and a reason."""

    until: str
    plus_ones: int | None = None
    reason: str = ""


class _BeadSnoozeCancel:
    """Sentinel choice asking to wake a snoozed bead now."""


CANCEL_BEAD_SNOOZE = _BeadSnoozeCancel()

type BeadSnoozeChoice = BeadSnoozeRequest | _BeadSnoozeCancel

_CUSTOM_PLACEHOLDER = "e.g., 2h, 3d, 1d12h, or '3d +2' to also wake at 2 more +1s"


def _next_morning(now: datetime | None = None) -> datetime:
    """Return 09:00 local on the day after *now*.

    Always the *next* day, never today: someone deferring a task at 06:00
    means "not during this session", not "in three hours".
    """
    reference = datetime.now(get_timezone()) if now is None else now
    return reference.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )


def _snooze_request(text: str) -> BeadSnoozeChoice:
    """Resolve one wake time through the shared snooze vocabulary.

    Presets and the custom field both come through here, so a preset can
    never resolve to a wake time the typed equivalent would be refused for.
    Its :class:`SnoozeTimeError` is a ``ValueError``, which is exactly what
    the modal base renders under the custom field.
    """
    request = parse_snooze_request(text)
    return BeadSnoozeRequest(until=request.until, plus_ones=request.plus_ones)


def _with_reason(choice: BeadSnoozeChoice, reason: str) -> BeadSnoozeChoice:
    """Attach the typed reason to a snooze; a cancel carries no reason."""
    if isinstance(choice, BeadSnoozeRequest):
        return replace(choice, reason=reason)
    return choice


def _bead_snooze_modal_title(issue: Issue) -> str:
    """Return the title naming the wake time a re-snooze would replace."""
    if issue.snooze is None:
        return f"Snooze {issue.id}"
    return f"Re-snooze {issue.id} · {snooze_summary(issue.snooze)}"


class BeadSnoozeModal(DurationChoiceModal[BeadSnoozeChoice, None]):
    """Pick a wake time, an optional +1 target, and a reason for one bead.

    Dismisses with a :class:`BeadSnoozeRequest`, the shared
    :data:`CANCEL_BEAD_SNOOZE` sentinel, or ``None`` on cancel.
    """

    def __init__(self, issue: Issue) -> None:
        choices: list[DurationChoice[BeadSnoozeChoice]] = [
            DurationChoice(
                key="1",
                title="4 hours",
                subtitle="Clear the rest of this work block.",
                value=lambda: _snooze_request("4h"),
                tone="primary",
            ),
            DurationChoice(
                key="2",
                title="Tomorrow morning",
                subtitle="Return at 9:00 AM local time.",
                value=lambda: _snooze_request(_next_morning().isoformat()),
            ),
            DurationChoice(
                key="3",
                title="3 days",
                subtitle="Let the work settle before triaging again.",
                value=lambda: _snooze_request("3d"),
            ),
            DurationChoice(
                key="4",
                title="1 week",
                subtitle="Defer until the next planning pass.",
                value=lambda: _snooze_request("7d"),
                tone="accent",
            ),
        ]
        if issue.snooze is not None:
            choices.append(
                DurationChoice(
                    key="x",
                    title="Cancel snooze",
                    subtitle="Wake it now and return it to triage.",
                    value=CANCEL_BEAD_SNOOZE,
                )
            )
        super().__init__(
            title=_bead_snooze_modal_title(issue),
            choices=choices,
            parse_custom=_snooze_request,
            custom_placeholder=_CUSTOM_PLACEHOLDER,
            annotation=DurationAnnotation(
                label="Reason (optional)",
                placeholder="Why is this deferred?",
                apply=_with_reason,
            ),
            id_prefix="bead-snooze",
            cancel_result=None,
        )


__all__ = [
    "CANCEL_BEAD_SNOOZE",
    "BeadSnoozeChoice",
    "BeadSnoozeModal",
    "BeadSnoozeRequest",
]
