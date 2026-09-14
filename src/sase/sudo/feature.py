"""Feature-flag guard for the sudo request workflow."""

from __future__ import annotations

from sase.feature_flags import FeatureFlag, current_flags
from sase.notification_gates.models import GateError

SUDO_FEATURE_HINT = (
    "Enable it with `sase flag enable agent_sudo_requests` after reviewing "
    "the sudo request workflow."
)


def _sudo_requests_enabled() -> bool:
    """Return whether the beta sudo request workflow is enabled."""
    return current_flags().enabled(FeatureFlag.agent_sudo_requests)


def require_sudo_requests_enabled(target: str = "sudo") -> None:
    """Fail closed while the sudo workflow is beta-gated."""
    if _sudo_requests_enabled():
        return
    raise GateError(
        "feature_disabled",
        target,
        f"sudo requests are behind the agent_sudo_requests beta flag. {SUDO_FEATURE_HINT}",
    )


__all__ = [
    "SUDO_FEATURE_HINT",
    "require_sudo_requests_enabled",
]
