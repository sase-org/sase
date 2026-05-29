"""Shared constants for the notification modal."""

from __future__ import annotations


# Action badge mapping
ACTION_BADGES: dict[str | None, str] = {
    "JumpToChangeSpec": "[CL]",
    "JumpToMentorReview": "[mentor]",
    "Tmux": "[tmux]",
    "HITL": "[HITL]",
    "PlanApproval": "[plan]",
    "UserQuestion": "[question]",
    "ViewErrorReport": "[error]",
    "memory_review": "[memory]",
}


HEADER_ID_PREFIX = "hdr:"
DEFAULT_HINT_TEXT = (
    "Enter: select  m: mark  x: dismiss  M: mute  s: snooze  e: edit  V: image  Y: copy path  "
    "C-n/C-p: next/prev file  C-d/C-u: scroll  R: read all  []: tags  q: close"
)
