"""Shared constants for the notification modal."""

from __future__ import annotations


# Action badge mapping
ACTION_BADGES: dict[str | None, str] = {
    "JumpToPatch": "[CS]",
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
    "GateExecutionFailed": "[gate failed]",
    "ViewErrorReport": "[error]",
    "ViewReport": "[report]",
    "OpenLaunchControl": "[models]",
}

# Gate actions intentionally have explicit defaults. A notification-provided
# icon always wins, while non-gate actions use the same table for a coherent
# inbox rather than falling back to text-only rows.
ACTION_ICONS: dict[str | None, str] = {
    None: "🔔",
    "JumpToAgent": "🤖",
    "JumpToPatch": "📋",
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
    "GateExecutionFailed": "!",
    "ViewErrorReport": "🚨",
    "ViewReport": "📊",
    "OpenLaunchControl": "🎛️",
}


def notification_icon(action: str | None, icon: str | None) -> str:
    """Return a notification's authored icon or its per-action default."""
    return icon or ACTION_ICONS.get(action, ACTION_ICONS[None])


HEADER_ID_PREFIX = "hdr:"

# Positional tab shortcuts in display order: 1–9, then 0 for the tenth.
# Tabs after the tenth stay unnumbered. Bindings and the tag strip both
# consume this sequence so the rendered digits cannot drift from the keys.
NOTIFICATION_TAB_SHORTCUTS: tuple[str, ...] = (
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "0",
)
NOTIFICATION_TAB_HINT_TEXT = "1-0/[]: tab"


def notification_tab_shortcut(index: int) -> str | None:
    """Return the positional shortcut for tab ``index``, or ``None`` past the tenth."""
    if 0 <= index < len(NOTIFICATION_TAB_SHORTCUTS):
        return NOTIFICATION_TAB_SHORTCUTS[index]
    return None


DEFAULT_HINT_TEXT = (
    "Enter: select  d: debug  m: mark  x: dismiss  M: mute  s: snooze  e: edit  V: view  Y: copy path  "
    f"C-n/C-p: next/prev file  C-d/C-u: scroll  g/G: top/bot  R: read tab  S: sections  {NOTIFICATION_TAB_HINT_TEXT}  +: +1  q: close"
)
QUESTION_HINT_TEXT = (
    "Enter: answer  d: debug  C-d/C-u: scroll  g/G: top/bot  m: mark  x: dismiss  M: mute  "
    f"s: snooze  S: sections  {NOTIFICATION_TAB_HINT_TEXT}  +: +1  q: close"
)
GATE_HINT_TEXT = (
    "Enter: review  d: debug  C-n/C-p: file  C-d/C-u: scroll  g/G: top/bot  m: mark  x: dismiss  "
    f"M: mute  s: snooze  S: sections  {NOTIFICATION_TAB_HINT_TEXT}  +: +1  q: close"
)
