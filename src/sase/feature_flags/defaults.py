"""Computed defaults for a newly scaffolded feature flag."""

from __future__ import annotations

from datetime import date, timedelta

from sase.bead.model import FlagRecord
from sase.feature_flags.models import FeatureFlagError


_DEFAULT_REMOVE_BY_DAYS = 90
_DEFAULT_REMOVE_BY_MINOR_BUMP = 2


def _default_remove_by_date(today: date) -> str:
    """Return the ISO date *today* plus the 90-day default window."""
    return (today + timedelta(days=_DEFAULT_REMOVE_BY_DAYS)).isoformat()


def _default_remove_by_release(version: str) -> str:
    """Return the current minor plus two, with the patch reset to zero."""
    core = version.split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except ValueError as exc:
        raise FeatureFlagError(
            f"cannot derive remove_by_release from version {version!r}"
        ) from exc
    return f"{major}.{minor + _DEFAULT_REMOVE_BY_MINOR_BUMP}.0"


def _parse_remove_by_arg(value: str, *, key: str) -> FlagRecord:
    """Parse ``YYYY-MM-DD/release`` into a :class:`FlagRecord` for *key*."""
    remove_by_date, sep, remove_by_release = value.partition("/")
    if not sep or not remove_by_date or not remove_by_release:
        raise FeatureFlagError(f"--remove-by expects <YYYY-MM-DD>/<release>: {value}")
    record = FlagRecord(
        key=key,
        remove_by_date=remove_by_date,
        remove_by_release=remove_by_release,
    )
    try:
        record.validate()
    except ValueError as exc:
        raise FeatureFlagError(str(exc)) from exc
    return record


def default_flag_record(
    key: str,
    *,
    today: date,
    version: str,
    remove_by: str | None = None,
) -> FlagRecord:
    """Return the flag bead record for *key*, honoring an optional override."""
    if remove_by is not None:
        return _parse_remove_by_arg(remove_by, key=key)
    record = FlagRecord(
        key=key,
        remove_by_date=_default_remove_by_date(today),
        remove_by_release=_default_remove_by_release(version),
    )
    record.validate()
    return record


__all__ = [
    "default_flag_record",
]
