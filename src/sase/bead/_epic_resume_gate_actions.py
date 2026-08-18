"""Host effects a human's EpicResume decision authorizes.

The gate offers only one action, so the check this module re-runs is that a
decision names ``resume`` — an adapter wired to the wrong effect still fails
loudly instead of launching an epic someone did not ask to resume.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.bead._epic_resume_gate_response import EpicResumeResponse
from sase.bead._epic_resume_gate_spec import (
    EPIC_RESUME_KIND,
    EPIC_RESUME_RESUME_OPTION_ID,
)
from sase.notification_gates.models import GateError

if TYPE_CHECKING:
    from sase.bead.epic_resume_launch import EpicResumeOrigin
    from sase.procs.models import Proc


def cancel_epic_resume(
    project: str,
    epic_id: str,
    *,
    reason: str,
    source: str = "ace",
) -> bool:
    """Cancel a pending epic-resume gate and settle its notification."""
    request_id = _find_pending_epic_resume(project, epic_id)
    if request_id is None:
        return False
    from sase.notification_gates.executor import cancel_gate
    from sase.notification_gates.paths import bundle_paths

    try:
        cancel_gate(
            bundle_paths(EPIC_RESUME_KIND, request_id).root,
            reason=reason,
            source=source,
        )
    except GateError as exc:
        if exc.code == "already_answered":
            return False
        raise
    return True


def resume_stalled_epic(
    decision: EpicResumeResponse,
    *,
    origin: EpicResumeOrigin | None = None,
) -> Proc:
    """Submit or reuse the detached epic resume selected by a human."""
    if decision.action != EPIC_RESUME_RESUME_OPTION_ID:
        raise GateError(
            "invalid_epic_resume_action",
            decision.action,
            "epic resume helper requires the resume action",
        )
    from sase.bead.epic_resume_launch import (
        epic_resume_origin_from_gate_source,
        submit_epic_resume_task,
    )

    return submit_epic_resume_task(
        decision.epic_id,
        project=decision.project,
        origin=(
            origin
            if origin is not None
            else epic_resume_origin_from_gate_source(decision.source)
        ),
    )


def _find_pending_epic_resume(project: str, epic_id: str) -> str | None:
    """Return the pending EpicResume request matching trusted payload fields."""
    from sase.notification_gates.durability import read_json_object
    from sase.notification_gates.paths import (
        CANCELLATION_FILENAME,
        REQUEST_FILENAME,
        RESPONSE_FILENAME,
        interaction_requests_dir,
    )

    kind_dir = interaction_requests_dir() / EPIC_RESUME_KIND
    try:
        bundles = sorted(kind_dir.iterdir(), key=lambda path: path.name)
    except (FileNotFoundError, OSError):
        return None

    for bundle in bundles:
        if not bundle.is_dir():
            continue
        if (bundle / RESPONSE_FILENAME).exists() or (
            bundle / CANCELLATION_FILENAME
        ).exists():
            continue
        try:
            envelope = read_json_object(bundle / REQUEST_FILENAME)
        except GateError:
            continue
        if envelope.get("kind") != EPIC_RESUME_KIND:
            continue
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("project") == project and payload.get("epic_id") == epic_id:
            request_id = envelope.get("request_id")
            if isinstance(request_id, str) and request_id:
                return request_id
    return None
