"""Mounted ACE coverage for the Muse parser-to-Reply-card streaming path.

Split facade: the tests now live in
``test_live_reply_follow_mounted_reply``,
``test_live_reply_follow_mounted_workflow``, and
``test_live_reply_follow_mounted_session``. Shared streaming fixtures live in
:mod:`tests.ace.tui._live_reply_follow_mounted_helpers`. This module
re-exports the public names so the original import path keeps working. It
collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.test_live_reply_follow_mounted_reply import (
    test_gated_muse_stream_reaches_mounted_reply_before_terminal,
)
from tests.ace.tui.test_live_reply_follow_mounted_session import (
    test_gated_muse_stream_reaches_mounted_session_current_turn_reply,
)
from tests.ace.tui.test_live_reply_follow_mounted_workflow import (
    test_gated_muse_stream_reaches_mounted_workflow_root_reply,
    test_gated_muse_stream_reaches_mounted_workflow_step_reply,
)

__test__ = False

__all__ = [
    "test_gated_muse_stream_reaches_mounted_reply_before_terminal",
    "test_gated_muse_stream_reaches_mounted_session_current_turn_reply",
    "test_gated_muse_stream_reaches_mounted_workflow_root_reply",
    "test_gated_muse_stream_reaches_mounted_workflow_step_reply",
]
