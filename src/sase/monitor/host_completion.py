"""Host completion receiver for prepared no-model monitor success.

Facade preserving the original public import path. Implementation lives in
``host_completion_settle``, ``host_completion_run``,
``host_completion_complete``, and the private ``_host_completion_shared``
module.
"""

from __future__ import annotations

from sase.monitor._host_completion_shared import (
    COMPLETED_BY_HOST_STATUS,
    DEFAULT_RECOVERY_ACTION,
    HOST_COMPLETED_OUTCOME,
    HOST_COMPLETION_IDENTITY,
    NEEDS_ATTENTION_STATUS,
)
from sase.monitor.host_completion_settle import settle_host_completion
from sase.monitor.host_completion_state import FINALIZING_STATUS, RECOVERY_STATUS

__all__ = [
    "DEFAULT_RECOVERY_ACTION",
    "COMPLETED_BY_HOST_STATUS",
    "FINALIZING_STATUS",
    "HOST_COMPLETED_OUTCOME",
    "HOST_COMPLETION_IDENTITY",
    "NEEDS_ATTENTION_STATUS",
    "RECOVERY_STATUS",
    "settle_host_completion",
]
