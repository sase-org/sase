"""Submission-time provenance shared by agent launch funnels."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sase.env_contracts import SASE_LAUNCH_SUBMITTED_AT_ENV

LEGACY_NO_SUBMISSION_STAMP = "__legacy_no_submission_stamp__"


def capture_launch_submitted_at(*, now: datetime | None = None) -> str:
    """Return an RFC 3339 UTC timestamp with microsecond precision."""
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("launch submission time must be timezone-aware")
    return (
        instant.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def stamp_launch_submission(
    extra_env: dict[str, str] | None,
    segment_extra_env: Sequence[dict[str, str] | None] | None = None,
    *,
    submitted_at: str | None = None,
) -> tuple[dict[str, str], list[dict[str, str] | None], str]:
    """Carry one explicit submission stamp through every slot in a launch."""
    stamped_env = dict(extra_env or {})
    stamped_segments = [
        None if env is None else dict(env) for env in (segment_extra_env or ())
    ]
    stamp = submitted_at
    if stamp is None:
        stamp = stamped_env.get(SASE_LAUNCH_SUBMITTED_AT_ENV)
    if stamp is None:
        stamp = next(
            (
                env[SASE_LAUNCH_SUBMITTED_AT_ENV]
                for env in stamped_segments
                if env is not None and SASE_LAUNCH_SUBMITTED_AT_ENV in env
            ),
            None,
        )
    if stamp is None:
        stamp = capture_launch_submitted_at()

    stamped_env[SASE_LAUNCH_SUBMITTED_AT_ENV] = stamp
    for env in stamped_segments:
        if env is not None:
            env[SASE_LAUNCH_SUBMITTED_AT_ENV] = stamp
    return stamped_env, stamped_segments, stamp


__all__ = [
    "LEGACY_NO_SUBMISSION_STAMP",
    "capture_launch_submitted_at",
    "stamp_launch_submission",
]
