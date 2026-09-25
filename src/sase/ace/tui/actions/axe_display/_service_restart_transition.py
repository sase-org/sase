"""Expected service-host restart transition for ACE's own restart.

Pure helpers so the TUI can treat its own ``--restart-service`` restart as
an expected transition instead of an outage. No disk I/O here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.service.platform_models import SERVICE_HOST_LIFECYCLE_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from sase.ace.tui._service_health import ServiceHealth
    from sase.service.status import ServiceStatusSnapshot

SERVICE_RESTART_POST_START_GRACE_SECONDS = 20.0
SERVICE_RESTART_TRANSITION_HARD_CAP_SECONDS = (
    SERVICE_HOST_LIFECYCLE_TIMEOUT_SECONDS + SERVICE_RESTART_POST_START_GRACE_SECONDS
)


@dataclass(frozen=True)
class ServiceRestartTransition:
    """Expected restart window started just before the restart request."""

    requested_at: float
    deadline: float


def restart_transition_settled(
    transition: ServiceRestartTransition,
    snapshot: ServiceStatusSnapshot | None,
    health: ServiceHealth,
) -> bool:
    """Return True once a new-generation healthy snapshot has landed.

    The generation check is required: without it the old host's pre-stop
    all-running snapshot, which the TUI can still read during the stop
    window, would settle the transition too early and the later shutdown
    snapshot would toast.
    """
    if not health.healthy:
        return False
    if snapshot is None:
        return False
    started_at = getattr(getattr(snapshot, "host", None), "started_at", None)
    if started_at is None:
        return False
    return started_at >= transition.requested_at


__all__ = [
    "SERVICE_RESTART_POST_START_GRACE_SECONDS",
    "SERVICE_RESTART_TRANSITION_HARD_CAP_SECONDS",
    "ServiceRestartTransition",
    "restart_transition_settled",
]
