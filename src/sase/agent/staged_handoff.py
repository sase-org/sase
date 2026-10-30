"""Host-facing staged-handoff API.

Implementation lives in private modules grouped by storage, admission,
record construction, and receipt handling. Public imports remain available
through this module for existing callers.
"""

from __future__ import annotations

from sase.agent._staged_handoff_store import (
    HANDOFF_LOCK_FILENAME,
    STAGED_HANDOFF_FILENAME,
    STAGED_HANDOFF_RECEIPT_FILENAME,
    STAGED_HANDOFF_RESPONSE_FILENAME,
    STAGING_RESERVATION_FILENAME,
    HostStageAdmission,
    HostStageIdentity,
    StagedHandoffError,
    acquire_handoff_locks,
    discard_staged_handoff,
    read_staged_handoff,
    read_staged_handoff_response,
    release_staging_reservation,
    release_staging_reservation_locked,
    staged_handoffs_enabled,
    write_staged_handoff_response,
)
from sase.agent._staged_handoff_admission import (
    acquire_staging_reservation,
    admit_stage,
    occupying_handoff_names,
    write_staged_handoff,
)
from sase.agent._staged_handoff_records import (
    build_gate_staged_record,
    build_monitor_staged_record,
    build_pipe_staged_record,
    build_plan_staged_record,
    build_questions_staged_record,
)
from sase.agent._staged_handoff_receipts import (
    read_adoption_receipt,
    receipt_authorizes,
    write_adoption_receipt,
)

__all__ = [
    "HANDOFF_LOCK_FILENAME",
    "STAGED_HANDOFF_FILENAME",
    "STAGED_HANDOFF_RECEIPT_FILENAME",
    "STAGED_HANDOFF_RESPONSE_FILENAME",
    "STAGING_RESERVATION_FILENAME",
    "HostStageAdmission",
    "HostStageIdentity",
    "StagedHandoffError",
    "acquire_handoff_locks",
    "acquire_staging_reservation",
    "admit_stage",
    "build_gate_staged_record",
    "build_monitor_staged_record",
    "build_pipe_staged_record",
    "build_plan_staged_record",
    "build_questions_staged_record",
    "discard_staged_handoff",
    "occupying_handoff_names",
    "read_adoption_receipt",
    "read_staged_handoff",
    "read_staged_handoff_response",
    "receipt_authorizes",
    "release_staging_reservation_locked",
    "release_staging_reservation",
    "staged_handoffs_enabled",
    "write_adoption_receipt",
    "write_staged_handoff",
    "write_staged_handoff_response",
]
