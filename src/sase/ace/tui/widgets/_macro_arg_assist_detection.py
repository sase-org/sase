"""Cursor detection helpers for macro argument assist (facade)."""

from __future__ import annotations

from ._macro_arg_assist_detection_contexts import (
    accepted_macro_arg_hint,
    detect_macro_arg_completion_at_cursor,
    detect_macro_arg_hint_at_cursor,
)

__all__ = [
    "accepted_macro_arg_hint",
    "detect_macro_arg_completion_at_cursor",
    "detect_macro_arg_hint_at_cursor",
]
