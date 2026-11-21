"""Per-project cadence state for the ``artifact_link_backfill`` chop.

Persists these facts across hourly ticks in one small JSON file:

- when each project last completed a stale-terminal outbox drop, so that
  expensive check (it may build the whole agent catalog) runs at most once
  per day per project;
- a decaying estimate of each project's reconcile/repair duration, so the
  chop never starts a reconcile it cannot finish inside its budget;
- the input fingerprints each project's last complete sweep and
  reconcile/repair pass finished with, plus when each last ran in full, so
  an unchanged project skips that work until its daily full pass.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import tempfile

from sase.sdd._artifact_link_incremental import (
    FULL_PASS_INTERVAL_SECONDS,
    ArtifactLinkReconcileMemo,
)

SCHEDULE_FILENAME = "artifact_link_backfill_schedule.json"
_SCHEDULE_SCHEMA_VERSION = 1
STALE_DROP_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_RECONCILE_ESTIMATE_SECONDS = 60.0
# Weight kept from the previous estimate when a reconcile ran faster; a
# slower run replaces the estimate outright.
_RECONCILE_ESTIMATE_DECAY = 0.7


@dataclass
class BackfillSchedule:
    """Mutable per-project cadence state, keyed by project name."""

    stale_checked_at: dict[str, float] = field(default_factory=dict)
    reconcile_seconds: dict[str, float] = field(default_factory=dict)
    sweep_fingerprints: dict[str, str] = field(default_factory=dict)
    sweep_full_at: dict[str, float] = field(default_factory=dict)
    reconcile_memos: dict[str, ArtifactLinkReconcileMemo] = field(default_factory=dict)

    def stale_drop_due(self, project: str, *, now: float) -> bool:
        """Return whether *project*'s daily stale-terminal drop should run."""

        checked_at = self.stale_checked_at.get(project)
        return checked_at is None or now - checked_at >= STALE_DROP_INTERVAL_SECONDS

    def record_stale_checked(self, project: str, *, now: float) -> None:
        self.stale_checked_at[project] = float(now)

    def reconcile_estimate(self, project: str) -> float:
        return self.reconcile_seconds.get(project, DEFAULT_RECONCILE_ESTIMATE_SECONDS)

    def record_reconcile(self, project: str, observed: float) -> None:
        """Fold one complete reconcile duration into *project*'s estimate.

        The estimate rises at once on a slow run and decays slowly after a
        fast one, so one quick tick cannot talk the chop into a reconcile
        that the next slow tick would overrun.
        """

        observed = float(observed)
        previous = self.reconcile_seconds.get(project)
        if previous is None:
            self.reconcile_seconds[project] = observed
            return
        blended = (
            _RECONCILE_ESTIMATE_DECAY * previous
            + (1.0 - _RECONCILE_ESTIMATE_DECAY) * observed
        )
        self.reconcile_seconds[project] = max(observed, blended)

    def sweep_skippable(
        self, project: str, fingerprint: str | None, *, now: float
    ) -> bool:
        """Return whether *project*'s sweep may skip its document walk.

        True only while *fingerprint* matches the one a complete sweep (no
        documents left pending) recorded, and that sweep's full walk is
        younger than the daily backstop.
        """

        full_at = self.sweep_full_at.get(project)
        return (
            fingerprint is not None
            and self.sweep_fingerprints.get(project) == fingerprint
            and full_at is not None
            and now - full_at < FULL_PASS_INTERVAL_SECONDS
        )

    def record_sweep(
        self, project: str, fingerprint: str | None, *, complete: bool, now: float
    ) -> None:
        """Record one full sweep walk; only a complete one may vouch for skips."""

        self.sweep_full_at[project] = float(now)
        if complete and fingerprint is not None:
            self.sweep_fingerprints[project] = fingerprint
        else:
            self.sweep_fingerprints.pop(project, None)

    def reconcile_memo(self, project: str) -> ArtifactLinkReconcileMemo:
        """Return *project*'s mutable reconcile memo, creating an empty one."""

        return self.reconcile_memos.setdefault(project, ArtifactLinkReconcileMemo())

    def prune(self, live_projects: Iterable[str]) -> None:
        """Forget projects that are no longer enabled."""

        live = set(live_projects)
        for mapping in (
            self.stale_checked_at,
            self.reconcile_seconds,
            self.sweep_fingerprints,
            self.sweep_full_at,
            self.reconcile_memos,
        ):
            for key in set(mapping) - live:
                del mapping[key]


def read_backfill_schedule(path: Path) -> BackfillSchedule:
    """Read the schedule; a missing, unreadable, or invalid file reads empty."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return BackfillSchedule()
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _SCHEDULE_SCHEMA_VERSION
    ):
        return BackfillSchedule()
    return BackfillSchedule(
        stale_checked_at=_number_map(payload.get("stale_checked_at")),
        reconcile_seconds=_number_map(payload.get("reconcile_seconds")),
        sweep_fingerprints=_string_map(payload.get("sweep_fingerprints")),
        sweep_full_at=_number_map(payload.get("sweep_full_at")),
        reconcile_memos=_memo_map(payload.get("reconcile_memos")),
    )


def write_backfill_schedule(path: Path, schedule: BackfillSchedule) -> None:
    """Atomically replace the schedule file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _SCHEDULE_SCHEMA_VERSION,
        "stale_checked_at": dict(sorted(schedule.stale_checked_at.items())),
        "reconcile_seconds": dict(sorted(schedule.reconcile_seconds.items())),
        "sweep_fingerprints": dict(sorted(schedule.sweep_fingerprints.items())),
        "sweep_full_at": dict(sorted(schedule.sweep_full_at.items())),
        "reconcile_memos": {
            key: memo.to_json()
            for key, memo in sorted(schedule.reconcile_memos.items())
        },
    }
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def _number_map(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, item in value.items():
        if (
            isinstance(key, str)
            and isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(item)
        ):
            result[key] = float(item)
    return result


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str) and item
    }


def _memo_map(value: object) -> dict[str, ArtifactLinkReconcileMemo]:
    if not isinstance(value, dict):
        return {}
    return {
        key: ArtifactLinkReconcileMemo.from_json(item)
        for key, item in value.items()
        if isinstance(key, str)
    }


__all__ = [
    "DEFAULT_RECONCILE_ESTIMATE_SECONDS",
    "SCHEDULE_FILENAME",
    "STALE_DROP_INTERVAL_SECONDS",
    "BackfillSchedule",
    "read_backfill_schedule",
    "write_backfill_schedule",
]
