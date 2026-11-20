"""Legacy flat scheduler state (status, metrics, errors, cycle results).

Facade preserving the historic ``sase.axe._state_scheduler`` import path.
The implementation now lives in the sibling section modules
``sase.axe._state_scheduler_status``,
``sase.axe._state_scheduler_shared``,
``sase.axe._state_scheduler_errors``, and
``sase.axe._state_scheduler_digests``; public API is re-exported through
``sase.axe.state``. Do not import from this module directly.
"""

from sase.axe._state_scheduler_digests import (
    mark_error_digest_sent,
    rotate_error_interval,
)
from sase.axe._state_scheduler_errors import (
    append_error,
    read_error_counts,
    read_errors,
)
from sase.axe._state_scheduler_shared import (
    ERROR_COUNTER_FILENAME,
    ERROR_COUNTER_SCHEMA_VERSION,
    ERROR_GROUP_SAMPLE_CHARS,
    ERROR_RING_CAP,
    ERROR_RING_FILENAME,
    ERROR_RING_PER_SIGNATURE_CAP,
)
from sase.axe._state_scheduler_status import (
    AxeMetrics,
    AxeStatus,
    CycleResult,
    read_cycle_result,
    read_metrics,
    read_output_log_tail,
    read_pid_file,
    read_status,
    remove_pid_file,
    write_cycle_result,
)

__all__ = [
    "ERROR_COUNTER_FILENAME",
    "ERROR_COUNTER_SCHEMA_VERSION",
    "ERROR_GROUP_SAMPLE_CHARS",
    "ERROR_RING_CAP",
    "ERROR_RING_FILENAME",
    "ERROR_RING_PER_SIGNATURE_CAP",
    "AxeMetrics",
    "AxeStatus",
    "CycleResult",
    "append_error",
    "mark_error_digest_sent",
    "read_cycle_result",
    "read_error_counts",
    "read_errors",
    "read_metrics",
    "read_output_log_tail",
    "read_pid_file",
    "read_status",
    "remove_pid_file",
    "rotate_error_interval",
    "write_cycle_result",
]
