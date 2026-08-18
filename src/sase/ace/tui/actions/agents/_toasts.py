"""Toast formatting for new notifications.

Produces a short, specific `(message, severity)` pair per Notification so the
TUI's poll loop can surface useful previews instead of a generic "N new
notification(s)" line. Also handles grouping for large batches.

A plan/epic toast's tier and epic phase/wave/size counts are read from
``Notification.action_data`` (see ``sase.sdd.plan_summary`` for the codec),
not recomputed here: this module does zero I/O and cannot fail on the render
path. TaskTriage and BeadSnooze chips are read the same way, through
``gate_chip_from_action_data``. One accepted limitation follows from that: a
snoozed-then-resurfaced notification re-toasts the counts recorded when the
gate was created, even if the reviewer has since edited the plan inside the
gate bundle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TYPE_CHECKING

from sase.notification_gates.presentation import (
    GateChip,
    gate_chip_from_action_data,
)
from sase.phase_size_presentation import (
    PHASE_SIZE_ABBREVIATIONS,
    PHASE_SIZE_ACCENTS,
    PhaseSizeValue,
)
from sase.plan_tier_presentation import (
    GENERIC_PLAN_ACCENT,
    GENERIC_PLAN_LABEL,
    PlanTierValue,
    normalize_plan_tier_value,
    plan_tier_presentation,
)
from sase.project_display_names import (
    humanize_cl_names_in_text,
    humanize_vcs_refs_in_text,
)
from sase.sdd.plan_display import (
    COLOR_PLAN_PATH_BASENAME,
    COLOR_PLAN_PRIMARY,
    PLAN_PROVENANCE_AGENT_STYLE,
)
from sase.sdd.plan_summary import decode_plan_counts

if TYPE_CHECKING:
    from sase.notifications import Notification


Severity = Literal["information", "warning", "error"]

# Cap for notes[0] excerpts included in toasts. Textual truncates long toasts
# anyway; this keeps them legible.
_MAX_NOTE_LEN = 60

# Threshold above which per-poll batches are consolidated into grouped toasts
# instead of one toast per notification.
_BATCH_THRESHOLD = 4

_FALLBACK_MESSAGE = "New notification"


def _markup_safe(text: str) -> str:
    """Escape ``[`` so Textual's markup parser cannot swallow it as a tag.

    ``textual.markup.escape`` is not enough here: its regex only escapes tags
    starting with ``[a-z#/@]``, so an uppercase run like ``[URGENT]`` passes
    through untouched and Textual still silently deletes it when rendering
    with ``markup=True``. A plain backslash-escape of every ``[`` round-trips
    correctly for every case that matters here (uppercase tags, embedded
    backslashes, a trailing backslash). Apply this last: humanize, then
    truncate, then escape — truncating already-escaped text can cut a ``\\[``
    in half.
    """
    return text.replace("[", "\\[")


def _truncate(text: str, limit: int = _MAX_NOTE_LEN) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _first_note(n: Notification) -> str:
    if n.notes:
        return _humanize_text(n.notes[0].strip())
    return ""


def _second_note(n: Notification) -> str:
    if len(n.notes) < 2:
        return ""
    return _humanize_text(n.notes[1].strip())


def _chip_toast_markup(chip: GateChip) -> str:
    body = f"{_markup_safe(chip.glyph)} {_markup_safe(chip.label)}"
    if chip.color is not None:
        return f"[bold {chip.color}]{body}[/]"
    return f"[bold]{body}[/]"


def _severity_from_keywords(text: str, default: Severity = "information") -> Severity:
    lower = text.lower()
    if "fail" in lower or "error" in lower:
        return "error"
    if "success" in lower:
        return "information"
    return default


def _resolve_plan_tier(n: Notification) -> PlanTierValue | None:
    """Resolve a notification's plan tier via a layered, always-total fallback.

    Prefers the tier the gate itself stored, then the request kind, then the
    coarser notification action, so legacy in-flight gates built before this
    field existed still resolve to the right tier word (or fall back to the
    generic "Plan" wording when nothing identifies a tier at all).
    """
    tier = normalize_plan_tier_value(n.action_data.get("plan_tier"))
    if tier is not None:
        return tier
    request_kind = n.action_data.get("request_kind")
    if request_kind == "epic_plan":
        return "epic"
    if request_kind == "plan":
        return "tale"
    if n.action == "EpicApproval":
        return "epic"
    if n.action == "PlanApproval":
        return "tale"
    return None


def _plan_tier_label_and_style(tier: PlanTierValue | None) -> tuple[str, str]:
    if tier is None:
        return GENERIC_PLAN_LABEL, f"bold {GENERIC_PLAN_ACCENT}"
    presentation = plan_tier_presentation(tier)
    return presentation.label, presentation.rich_style


def _count_phrase_markup(count: int, singular: str) -> str:
    unit = singular if count == 1 else f"{singular}s"
    return f"[{COLOR_PLAN_PRIMARY}]{count}[/] [dim]{unit}[/]"


def _size_count_markup(size: PhaseSizeValue, count: int) -> str:
    abbreviation = PHASE_SIZE_ABBREVIATIONS[size]
    accent = PHASE_SIZE_ACCENTS[size]
    return f"{count} [bold {accent}]{abbreviation}[/]"


def _epic_detail_line(action_data: Mapping[str, str]) -> str | None:
    """Return the epic phase/wave/size summary line, or ``None`` if unstored."""
    summary = decode_plan_counts(action_data)
    if summary is None or summary.tier != "epic":
        return None

    parts = [_count_phrase_markup(summary.phase_count, "phase")]
    if summary.wave_count is not None:
        parts.append(_count_phrase_markup(summary.wave_count, "wave"))
    for size, count in summary.size_counts:
        parts.append(_size_count_markup(size, count))
    return " [dim]·[/] ".join(parts)


def _plan_toast(n: Notification) -> tuple[str, Severity]:
    """Build the tier-aware toast for a ``PlanApproval``/``EpicApproval``."""
    tier = _resolve_plan_tier(n)
    tier_label, tier_style = _plan_tier_label_and_style(tier)
    tier_markup = f"[{tier_style}]{tier_label}[/]"

    raw_agent_name = n.action_data.get("agent_name")
    agent_name = _humanize_text(str(raw_agent_name)) if raw_agent_name else ""
    original_plan_file = n.action_data.get("original_plan_file", "").strip()
    plan_file = original_plan_file or next(iter(n.files), "")
    plan_name = plan_file.rsplit("/", 1)[-1] if plan_file else ""
    note = _first_note(n)

    if plan_name:
        basename_markup = f"[{COLOR_PLAN_PATH_BASENAME}]{_markup_safe(plan_name)}[/]"
        if agent_name:
            agent_markup = (
                f"[{PLAN_PROVENANCE_AGENT_STYLE}]@{_markup_safe(agent_name)}[/]"
            )
            message = f"{tier_markup} ready for {agent_markup}: {basename_markup}"
        else:
            message = f"{tier_markup} ready for review: {basename_markup}"
    elif note:
        message = _markup_safe(note)
    else:
        message = f"{tier_markup} ready for review"

    if tier == "epic":
        detail_line = _epic_detail_line(n.action_data)
        if detail_line:
            message = f"{message}\n{detail_line}"

    return (message, "warning")


def _bead_gate_toast(n: Notification) -> tuple[str, Severity]:
    """Build the chip-aware toast for ``TaskTriage`` and ``BeadSnooze``."""
    note = _first_note(n)
    chip = gate_chip_from_action_data(n.action_data)
    if chip is not None:
        message = _chip_toast_markup(chip)
        if note:
            message = f"{message}  {_markup_safe(note)}"
    elif note:
        message = _markup_safe(note)
    else:
        message = _FALLBACK_MESSAGE

    detail = _second_note(n)
    if detail:
        message = f"{message}\n[dim]{_markup_safe(_truncate(detail))}[/]"
    return (message, "warning")


def _format_notification_toast(n: Notification) -> tuple[str, Severity]:
    """Return ``(message, severity)`` for a single new notification.

    Each branch falls back to ``notes[0]`` — and ultimately to a generic
    placeholder — if the identity fields the sender would normally provide
    are missing.
    """
    note = _first_note(n)
    action = n.action

    if action in {"PlanApproval", "EpicApproval"}:
        return _plan_toast(n)

    if action == "UserQuestion":
        raw_agent_name = n.action_data.get("agent_name") or n.action_data.get(
            "agent_cl_name"
        )
        agent_name = _humanize_text(str(raw_agent_name)) if raw_agent_name else ""
        if agent_name and note:
            return (
                f"Question from @{_markup_safe(agent_name)}: "
                f"{_markup_safe(_truncate(note))}",
                "warning",
            )
        if note:
            return (_markup_safe(_truncate(note)), "warning")
        return ("Claude is asking a question", "warning")

    if action == "HITL":
        return (_markup_safe(note) if note else "HITL waiting for input", "warning")

    if action == "LaunchApproval":
        return (
            _markup_safe(note) if note else "Launch approval requested",
            "warning",
        )

    if action in {"TaskTriage", "BeadSnooze"}:
        return _bead_gate_toast(n)

    if action == "ViewErrorReport":
        return (f"Axe: {_markup_safe(note)}" if note else "Axe errors", "error")

    if action == "ViewReport":
        return (_markup_safe(note) if note else "Report available", "information")

    if action in {"JumpToPatch", "JumpToChangeSpec"}:  # legacy compatibility alias
        severity: Severity = "information"
        if note.lower().startswith("sync fail"):
            severity = "error"
        return (_markup_safe(note) if note else "Patch update", severity)

    if action == "JumpToMentorReview":
        return (_markup_safe(note) if note else "Mentor review ready", "information")

    if action == "JumpToAgent":
        return (
            _markup_safe(note) if note else "Agent update",
            _severity_from_keywords(note),
        )

    # Tmux, None, or unknown actions
    return (_markup_safe(note) if note else _FALLBACK_MESSAGE, "information")


def _humanize_text(text: str) -> str:
    return humanize_cl_names_in_text(humanize_vcs_refs_in_text(text))


def _severity_bucket(severity: Severity) -> str:
    return {"warning": "warnings", "error": "errors", "information": "updates"}[
        severity
    ]


def format_batch_toasts(
    notifications: list[Notification],
) -> list[tuple[str, Severity]]:
    """Return toasts to emit for a batch of newly-arrived notifications.

    Policy:

    - 0 notifications: empty list.
    - 1-3 notifications: one toast per notification (specific text).
    - 4+ notifications: one grouped toast per severity bucket summarising the
      count and action breakdown.
    """
    if not notifications:
        return []

    if len(notifications) < _BATCH_THRESHOLD:
        return [_format_notification_toast(n) for n in notifications]

    per_severity: dict[Severity, list[Notification]] = {
        "warning": [],
        "error": [],
        "information": [],
    }
    for n in notifications:
        _, sev = _format_notification_toast(n)
        per_severity[sev].append(n)

    toasts: list[tuple[str, Severity]] = []
    # Preserve a deterministic, urgency-first ordering.
    for sev in ("error", "warning", "information"):
        items = per_severity[sev]  # type: ignore[index]
        if not items:
            continue
        bucket = _severity_bucket(sev)  # type: ignore[arg-type]
        breakdown = _action_breakdown(items)
        count = len(items)
        if breakdown:
            msg = f"{count} {bucket}: {breakdown}"
        else:
            msg = f"{count} {bucket}"
        toasts.append((msg, sev))  # type: ignore[arg-type]
    return toasts


_ACTION_LABELS: dict[str | None, tuple[str, str]] = {
    "PlanApproval": ("tale", "tales"),
    "EpicApproval": ("epic", "epics"),
    "UserQuestion": ("question", "questions"),
    "HITL": ("HITL", "HITLs"),
    "LaunchApproval": ("launch approval", "launch approvals"),
    "TaskTriage": ("task triage", "task triages"),
    "BeadSnooze": ("snoozed task", "snoozed tasks"),
    "ViewErrorReport": ("axe error", "axe errors"),
    "ViewReport": ("report", "reports"),
    "JumpToPatch": ("sync", "syncs"),
    "JumpToChangeSpec": ("sync", "syncs"),  # legacy compatibility alias
    "JumpToMentorReview": ("mentor review", "mentor reviews"),
    "JumpToAgent": ("agent update", "agent updates"),
    "Tmux": ("tmux", "tmux"),
}


def _action_breakdown(notifications: list[Notification]) -> str:
    counts: dict[str | None, int] = {}
    for n in notifications:
        counts[n.action] = counts.get(n.action, 0) + 1
    parts: list[str] = []
    for action, count in counts.items():
        singular, plural = _ACTION_LABELS.get(action, ("notification", "notifications"))
        label = singular if count == 1 else plural
        parts.append(f"{count} {label}")
    return ", ".join(parts)
