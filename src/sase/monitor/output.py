"""Monitor facade for bounded supervised-shell output capture."""

from __future__ import annotations

from sase.shells.output import SHELL_MAX_OUTPUT_BYTES, OutputCapture

#: Retain at most this many bytes of monitor output (head + tail).
MONITOR_MAX_OUTPUT_BYTES = SHELL_MAX_OUTPUT_BYTES

__all__ = ["MONITOR_MAX_OUTPUT_BYTES", "OutputCapture"]
