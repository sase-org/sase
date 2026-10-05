"""Pure parser for agy conversations (reported as unverifiable)."""

from __future__ import annotations

from typing import Any

from sase.instructions import fingerprints as fp


def observe_agy_session(conversation: dict[str, Any] | None) -> dict[str, Any]:
    """Reduce an agy conversation record to scoreboard observation fields."""
    directive: bool | None = None
    if isinstance(conversation, dict):
        blob = str(conversation.get("prompt", ""))
        if fp.AGY_DIRECTIVE_MARKER in blob:
            directive = True
    return {
        "contract_count": 0,
        "home": False,
        "project": None,
        "directive": directive,
        "native_full_count": 0,
        "foreign": None,
        "has_helper_template": False,
        "final_attempts": 0,
        "final_denied": 0,
        "final_accepted": 0,
    }


__all__ = ["observe_agy_session"]
