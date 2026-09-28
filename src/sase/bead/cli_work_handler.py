"""Epic launch orchestration and compatibility helpers for ``sase bead work``.

The implementation lives in focused modules; this module keeps the historical
``sase.bead.cli_work_handler`` import surface intact. Patch the module that
defines a helper (``cli_work_handler_launch``, ``cli_work_handler_publish``,
...), not this facade.
"""

from __future__ import annotations

from sase.bead.cli_work_handler_entry import (
    BEAD_WORK_TIMING_ENV,
    handle_bead_work,
    make_bead_work_timer,
    preload_launch_imports,
)
from sase.bead.cli_work_handler_errors import (
    BeadWorkError,
    EpicGraphRelocatedError,
    EpicLaunchState,
)
from sase.bead.cli_work_handler_launch import (
    launch_epic_bead_work,
)
from sase.bead.cli_work_plan_snapshot import (
    epic_plan_snapshot_destination as epic_plan_snapshot_destination,
    epic_plan_source_path as epic_plan_source_path,
)
from sase.bead.cli_work_task import (
    TaskBeadWorkError as TaskBeadWorkError,
    TaskWorkResult as TaskWorkResult,
    launch_task_bead_work as launch_task_bead_work,
)

__all__ = [
    "BEAD_WORK_TIMING_ENV",
    "BeadWorkError",
    "EpicGraphRelocatedError",
    "EpicLaunchState",
    "TaskBeadWorkError",
    "TaskWorkResult",
    "epic_plan_snapshot_destination",
    "epic_plan_source_path",
    "handle_bead_work",
    "launch_epic_bead_work",
    "launch_task_bead_work",
    "make_bead_work_timer",
    "preload_launch_imports",
]
