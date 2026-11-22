"""Single-lumberjack scheduler loop.

A Lumberjack runs a subset of chops on a fixed interval using the
``schedule`` library.  The Orchestrator spawns one Lumberjack per
configured lumberjack definition (e.g. hooks, checks, comments,
housekeeping).
"""

from ._lumberjack_core import Lumberjack
from ._lumberjack_shared import LogCallback

__all__ = [
    "LogCallback",
    "Lumberjack",
]
