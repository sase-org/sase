"""Shared constants for the notification modal."""

from __future__ import annotations


# Action badge mapping
ACTION_BADGES: dict[str | None, str] = {
    "JumpToChangeSpec": "[CL]",
    "JumpToMentorReview": "[mentor]",
    "JumpToAgent": "[agent]",
    "Tmux": "[tmux]",
    "HITL": "[HITL]",
    "PlanApproval": "[plan]",
    "UserQuestion": "[question]",
    "ViewErrorReport": "[error]",
}


# Section taxonomy: (key, label, color). Order is render order.
SECTIONS: list[tuple[str, str, str]] = [
    ("priority", "PRIORITY", "#FF4444"),
    ("inbox", "INBOX", "#FFD700"),
    ("muted", "MUTED", "#5FAFAF"),
]

HEADER_ID_PREFIX = "hdr:"
DEFAULT_HINT_TEXT = (
    "Enter: select  x: dismiss  m: mute  s: snooze  e: edit  "
    "C-n/C-p: next/prev file  C-d/C-u: scroll  R: read all  q: close"
)
