"""Shared constants for the notification modal."""

from __future__ import annotations


# Action badge mapping
ACTION_BADGES: dict[str | None, str] = {
    "JumpToChangeSpec": "[CS]",
    "JumpToMentorReview": "[mentor]",
    "Tmux": "[tmux]",
    "HITL": "[HITL]",
    "LaunchApproval": "[launch]",
    "TaskTriage": "[task]",
    "BeadSnooze": "[snooze]",
    "PlanApproval": "[plan]",
    "EpicApproval": "[epic]",
    "UserQuestion": "[question]",
    "CustomGate": "[custom]",
    "ViewErrorReport": "[error]",
    "ViewReport": "[report]",
    "memory_review": "[memory]",
}

# Gate actions intentionally have explicit defaults. A notification-provided
# icon always wins, while non-gate actions use the same table for a coherent
# inbox rather than falling back to text-only rows.
ACTION_ICONS: dict[str | None, str] = {
    None: "🔔",
    "JumpToAgent": "🤖",
    "JumpToChangeSpec": "📋",
    "JumpToMentorReview": "👀",
    "Tmux": "🖥️",
    "HITL": "✋",
    "LaunchApproval": "🚀",
    "TaskTriage": "✦",
    "BeadSnooze": "◈",
    "PlanApproval": "📝",
    "EpicApproval": "🗺️",
    "UserQuestion": "❓",
    "CustomGate": "✨",
    "ViewErrorReport": "🚨",
    "ViewReport": "📊",
    "memory_review": "🧠",
}


def notification_icon(action: str | None, icon: str | None) -> str:
    """Return a notification's authored icon or its per-action default."""
    return icon or ACTION_ICONS.get(action, ACTION_ICONS[None])


HEADER_ID_PREFIX = "hdr:"
DEFAULT_HINT_TEXT = (
    "Enter: select  d: debug  m: mark  x: dismiss  M: mute  s: snooze  e: edit  V: view  Y: copy path  "
    "C-n/C-p: next/prev file  C-d/C-u: scroll  R: read all  []: tags  q: close"
)
QUESTION_HINT_TEXT = (
    "Enter: answer  d: debug  C-d/C-u: scroll  m: mark  x: dismiss  M: mute  "
    "s: snooze  []: tags  q: close"
)
GATE_HINT_TEXT = (
    "Enter: review  d: debug  C-n/C-p: file  C-d/C-u: scroll  m: mark  x: dismiss  "
    "M: mute  s: snooze  []: tags  q: close"
)
