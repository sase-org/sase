"""Shared constants for the notification modal."""

from __future__ import annotations


# Action badge mapping
ACTION_BADGES: dict[str | None, str] = {
    "JumpToChangeSpec": "[CS]",
    "JumpToMentorReview": "[mentor]",
    "Tmux": "[tmux]",
    "HITL": "[HITL]",
    "LaunchApproval": "[launch]",
    "PlanApproval": "[plan]",
    "UserQuestion": "[question]",
    "ViewErrorReport": "[error]",
    "memory_review": "[memory]",
}


HEADER_ID_PREFIX = "hdr:"
DEFAULT_HINT_TEXT = (
    "Enter: select  m: mark  x: dismiss  M: mute  s: snooze  e: edit  V: view  Y: copy path  "
    "C-n/C-p: next/prev file  C-d/C-u: scroll  R: read all  []: tags  q: close"
)
QUESTION_HINT_TEXT = (
    "Enter: answer  C-d/C-u: scroll  m: mark  x: dismiss  M: mute  "
    "s: snooze  []: tags  q: close"
)
