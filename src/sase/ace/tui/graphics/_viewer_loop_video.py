"""Inspect-first video view for the terminal artifact viewer.

Opening a video shows a frame, a decile storyboard, and a status line.
Motion is opt-in on space; the sequence loop consumes the inspect outcome.
"""

from __future__ import annotations

from ._viewer_loop_video_view import run_video_inspect

__all__ = [
    "run_video_inspect",
]
