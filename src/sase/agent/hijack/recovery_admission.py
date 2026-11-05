"""Durable typed admission for keep-work recovery attempts.

The attempt descriptor is prepared before the hijack CAS but is not a launch
request until the CAS wins. A typed admission bundle then makes that exact
attempt coordinator-readable. Its dispatcher reconstructs the strict
successor launch from the persisted descriptor rather than allocating a new
workspace or successor identity.
"""

from __future__ import annotations

from sase.agent.hijack._recovery_admission_common import (
    LOGICAL_ID,
    RECOVERY_ADMISSION_METADATA_KEY,
    RECOVERY_ADMISSION_SCHEMA_VERSION,
    RECOVERY_ADMISSION_SOURCE_SURFACE,
    RECOVERY_REQUESTS_SUBDIR,
    TYPED_LAUNCHES_SUBDIR,
    is_hijack_recovery_typed_request,
)
from sase.agent.hijack._recovery_admission_dispatch import (
    dispatch_recovery_admission,
)
from sase.agent.hijack._recovery_admission_dispatcher import (
    make_hijack_recovery_agent_dispatcher,
)
from sase.agent.hijack._recovery_admission_observe import (
    cancel_recovery_admission_for_rollback,
    cancel_recovery_admission_request,
    observe_recovery_admission,
    resume_recovery_admission,
)
from sase.agent.hijack._recovery_admission_prepare import (
    persist_prepared_recovery_descriptor,
    prepare_recovery_admission_descriptor,
    remove_prepared_recovery_descriptor,
)

__all__ = [
    "RECOVERY_ADMISSION_METADATA_KEY",
    "RECOVERY_ADMISSION_SCHEMA_VERSION",
    "RECOVERY_ADMISSION_SOURCE_SURFACE",
    "cancel_recovery_admission_request",
    "cancel_recovery_admission_for_rollback",
    "dispatch_recovery_admission",
    "is_hijack_recovery_typed_request",
    "make_hijack_recovery_agent_dispatcher",
    "observe_recovery_admission",
    "persist_prepared_recovery_descriptor",
    "prepare_recovery_admission_descriptor",
    "remove_prepared_recovery_descriptor",
    "resume_recovery_admission",
]
