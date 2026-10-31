"""Internal staged-monitor transaction: persist, adopt, and clean up.

Facade preserving the original :mod:`sase.monitor.start_stage` import path.
The implementation lives next door:

- :mod:`sase.monitor.start_stage_persist` (stage/persist, no proc submit)
- :mod:`sase.monitor.start_stage_adopt` (launch/adopt from frozen payload)
- :mod:`sase.monitor.start_stage_cleanup` (unwind unstarted resources)
- :mod:`sase.monitor._start_stage_shared` (helpers shared across the split)

Public ``start_monitor`` stays on the immediate path until activation.
"""

from __future__ import annotations

from .start_stage_adopt import launch_from_persisted_payload
from .start_stage_cleanup import cleanup_staged_monitor
from .start_stage_persist import stage_monitor

__all__ = [
    "cleanup_staged_monitor",
    "launch_from_persisted_payload",
    "stage_monitor",
]
