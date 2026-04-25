"""Toast formatting for new notifications.

Produces a short, specific `(message, severity)` pair per Notification so the
TUI's poll loop can surface useful previews instead of a generic "N new
notification(s)" line. Also handles grouping for large batches.
"""

from __future__ import annotations

from typing import Literal, TYPE_CHECKING

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


def _truncate(text: str, limit: int = _MAX_NOTE_LEN) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _first_note(n: Notification) -> str:
    if n.notes:
        return n.notes[0].strip()
    return ""


def _severity_from_keywords(text: str, default: Severity = "information") -> Severity:
    lower = text.lower()
    if "fail" in lower or "error" in lower:
        return "error"
    if "success" in lower:
        return "information"
    return default


def _format_notification_toast(n: Notification) -> tuple[str, Severity]:
    """Return ``(message, severity)`` for a single new notification.

    Each branch falls back to ``notes[0]`` — and ultimately to a generic
    placeholder — if the identity fields the sender would normally provide
    are missing.
    """
    note = _first_note(n)
    action = n.action

    if action == "PlanApproval":
        agent_name = n.action_data.get("agent_name")
        plan_file = next(iter(n.files), None)
        plan_name = ""
        if plan_file:
            plan_name = plan_file.rsplit("/", 1)[-1]
        if agent_name and plan_name:
            return (f"Plan ready for @{agent_name}: {plan_name}", "warning")
        if note:
            return (note, "warning")
        return ("Plan ready for review", "warning")

    if action == "UserQuestion":
        agent_name = n.action_data.get("agent_name") or n.action_data.get(
            "agent_cl_name"
        )
        if agent_name and note:
            return (f"Question from @{agent_name}: {_truncate(note)}", "warning")
        if note:
            return (_truncate(note), "warning")
        return ("Claude is asking a question", "warning")

    if action == "HITL":
        return (note or "HITL waiting for input", "warning")

    if action == "ViewErrorReport":
        return (f"Axe: {note}" if note else "Axe errors", "error")

    if action == "JumpToChangeSpec":
        severity: Severity = "information"
        if note.lower().startswith("sync fail"):
            severity = "error"
        return (note or "ChangeSpec update", severity)

    if action == "JumpToMentorReview":
        return (note or "Mentor review ready", "information")

    if action == "JumpToAgent":
        return (note or "Agent update", _severity_from_keywords(note))

    # Tmux, None, or unknown actions
    return (note or _FALLBACK_MESSAGE, "information")


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
    "PlanApproval": ("plan", "plans"),
    "UserQuestion": ("question", "questions"),
    "HITL": ("HITL", "HITLs"),
    "ViewErrorReport": ("axe error", "axe errors"),
    "JumpToChangeSpec": ("sync", "syncs"),
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
