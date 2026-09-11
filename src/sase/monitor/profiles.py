"""Named monitor profiles for common long-running command workflows."""

from __future__ import annotations

from dataclasses import dataclass

from .followup_prompt import DEFAULT_NEXT_OUTPUT

VERIFY_MONITOR_PROFILE_NAME = "verify"
MONITOR_PROFILE_CHOICES = (VERIFY_MONITOR_PROFILE_NAME,)


@dataclass(frozen=True)
class MonitorProfile:
    """Resolved defaults supplied by one named monitor profile."""

    name: str
    start_status: str
    stop_status: str
    next_output: str


VERIFY_MONITOR_PROFILE = MonitorProfile(
    name=VERIFY_MONITOR_PROFILE_NAME,
    start_status="TESTING",
    stop_status="TESTED",
    next_output=DEFAULT_NEXT_OUTPUT,
)


def resolve_monitor_profile(name: str | None) -> MonitorProfile | None:
    """Return the named monitor profile, or ``None`` when omitted/unknown."""
    if not name:
        return None
    if name.strip() == VERIFY_MONITOR_PROFILE_NAME:
        return VERIFY_MONITOR_PROFILE
    return None


__all__ = [
    "MONITOR_PROFILE_CHOICES",
    "MonitorProfile",
    "VERIFY_MONITOR_PROFILE",
    "VERIFY_MONITOR_PROFILE_NAME",
    "resolve_monitor_profile",
]
