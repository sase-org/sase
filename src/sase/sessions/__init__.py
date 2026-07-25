"""Live SASE session registry and shared session display identity."""

from __future__ import annotations

from .display import (
    DEAD_SESSION_MARK,
    NO_SESSION_MARK,
    SESSION_PALETTE,
    session_chip,
    session_color,
    session_display_label,
    short_session_handle,
)
from .registry import (
    SESSION_KIND_ACE,
    SessionIdentity,
    SessionRefError,
    current_session_id,
    latest_session,
    live_sessions,
    register_session,
    resolve_session_ref,
    session_record_path,
    sessions_dir,
    unregister_session,
)

__all__ = [
    "DEAD_SESSION_MARK",
    "NO_SESSION_MARK",
    "SESSION_KIND_ACE",
    "SESSION_PALETTE",
    "SessionIdentity",
    "SessionRefError",
    "current_session_id",
    "latest_session",
    "live_sessions",
    "register_session",
    "resolve_session_ref",
    "session_chip",
    "session_color",
    "session_display_label",
    "session_record_path",
    "sessions_dir",
    "short_session_handle",
    "unregister_session",
]
