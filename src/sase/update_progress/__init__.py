"""Live, streaming progress timelines for `sase update`.

Presentation-only package: imports only rich and the standard library plus
``sase.core.paths`` (deferred) and the package version (deferred), so it
cannot create backend import cycles.
"""

from __future__ import annotations

from .events import (
    NULL_PROGRESS,
    TERMINAL_STATUSES,
    NullProgress,
    OutputSink,
    StepSpec,
    StepStatus,
    UpdateProgress,
    step,
)
from .fanout import FanOutProgress
from .log_sink import UpdateLogSink
from .render_live import LiveTimelineRenderer
from .render_plain import PlainTimelineRenderer
from .session import RendererKind, UpdateProgressSession, select_renderer
from .styles import (
    FINAL_GLYPH,
    STATUS_GLYPH,
    STATUS_STYLE,
    format_duration,
    format_span,
    format_stamp,
)
from .timeline import StepSnapshot, TimelineModel, elapsed, walk

__all__ = [
    "FINAL_GLYPH",
    "STATUS_GLYPH",
    "STATUS_STYLE",
    "FanOutProgress",
    "LiveTimelineRenderer",
    "NullProgress",
    "NULL_PROGRESS",
    "OutputSink",
    "PlainTimelineRenderer",
    "RendererKind",
    "StepSnapshot",
    "StepSpec",
    "StepStatus",
    "TERMINAL_STATUSES",
    "TimelineModel",
    "UpdateLogSink",
    "UpdateProgress",
    "UpdateProgressSession",
    "elapsed",
    "format_duration",
    "format_span",
    "format_stamp",
    "select_renderer",
    "step",
    "walk",
]
