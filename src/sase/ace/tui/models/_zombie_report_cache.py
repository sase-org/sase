"""Cached zombie-plan reports for the Beads pane."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import TYPE_CHECKING, Final

from sase.ace.tui.models._agent_stranded_cache import project_store_fingerprint

if TYPE_CHECKING:
    from sase.bead.zombie import ZombieReport
    from sase.core.zombie_facade import ZombieVerdict

_CACHE_TTL_SECONDS: Final = 60.0
_FORCED_RECOMPUTE_MIN_INTERVAL_SECONDS: Final = 30.0
_CACHE_MAX_ENTRIES: Final = 64


@dataclass(frozen=True, slots=True)
class _CachedProjectReport:
    expires_at: float
    computed_at: float
    fingerprint: str | None
    snapshot: ZombieReport
    verdict_index: dict[str, ZombieVerdict]


class _ZombieReportCache:
    """Small TTL- and bead-store-fingerprint-bounded zombie report cache."""

    def __init__(self, *, max_entries: int) -> None:
        self._entries: OrderedDict[str, _CachedProjectReport] = OrderedDict()
        self._max_entries = max_entries
        self._lock = RLock()
        self._generation = 0

    def get(self, project_key: str) -> ZombieReport | None:
        with self._lock:
            entry = self._entries.get(project_key)
            if entry is None:
                return None
            self._entries.move_to_end(project_key)
            return entry.snapshot

    def should_resolve(self, project_key: str) -> bool:
        with self._lock:
            entry = self._entries.get(project_key)
            return entry is None or entry.expires_at <= monotonic()

    def entry(self, project_key: str) -> _CachedProjectReport | None:
        with self._lock:
            entry = self._entries.get(project_key)
            if entry is not None:
                self._entries.move_to_end(project_key)
            return entry

    def verdict_index(self, project_key: str) -> dict[str, ZombieVerdict] | None:
        """Return the index built when the project's report was stored."""
        with self._lock:
            entry = self._entries.get(project_key)
            if entry is not None:
                self._entries.move_to_end(project_key)
                return entry.verdict_index
            return None

    def report_token(self) -> tuple[object, ...]:
        """Return identities for all cached reports without exposing state."""
        with self._lock:
            snapshots = tuple(
                sorted(
                    (key, id(entry.snapshot)) for key, entry in self._entries.items()
                )
            )
            return (self._generation, snapshots)

    def set(
        self,
        project_key: str,
        snapshot: ZombieReport,
        fingerprint: str | None,
        *,
        computed_at: float | None = None,
    ) -> None:
        computed_at = monotonic() if computed_at is None else computed_at
        with self._lock:
            self._entries[project_key] = _CachedProjectReport(
                expires_at=computed_at + _CACHE_TTL_SECONDS,
                computed_at=computed_at,
                fingerprint=fingerprint,
                snapshot=snapshot,
                verdict_index={row.plan_id: row for row in snapshot.report.rows},
            )
            self._entries.move_to_end(project_key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            self._generation += 1

    def expire(self, project_key: str) -> None:
        with self._lock:
            entry = self._entries.get(project_key)
            if entry is None:
                return
            self._entries[project_key] = _CachedProjectReport(
                expires_at=0.0,
                computed_at=entry.computed_at,
                fingerprint=entry.fingerprint,
                snapshot=entry.snapshot,
                verdict_index=entry.verdict_index,
            )
            self._entries.move_to_end(project_key)
            self._generation += 1

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._generation += 1


_ZOMBIE_REPORT_CACHE = _ZombieReportCache(max_entries=_CACHE_MAX_ENTRIES)


def zombie_report_cache() -> _ZombieReportCache:
    """Return the shared report cache for the private zombie-work modules."""
    return _ZOMBIE_REPORT_CACHE


def cached_zombie_report(project_key: str) -> ZombieReport | None:
    """Return the warm zombie report for a project, without filesystem access."""
    return _ZOMBIE_REPORT_CACHE.get(project_key)


def cached_zombie_verdict(project_key: str, bead_id: str) -> ZombieVerdict | None:
    """Return the warm zombie verdict for one plan bead, if any."""
    verdicts = _ZOMBIE_REPORT_CACHE.verdict_index(project_key)
    if not verdicts:
        return None
    return verdicts.get(bead_id)


def should_resolve_zombie_report(project_key: str) -> bool:
    """Return whether a project's zombie report is cold or past its TTL."""
    return _ZOMBIE_REPORT_CACHE.should_resolve(project_key)


def force_zombie_refresh(project_key: str) -> None:
    """Expire the cached zombie report so the next warmup reloads it."""
    _ZOMBIE_REPORT_CACHE.expire(project_key)


def _report_projection(report: ZombieReport) -> tuple[tuple[object, ...], ...]:
    """Keep report comparisons limited to values that affect this surface."""
    return tuple(
        (
            row.plan_id,
            row.state,
            row.reason,
            row.unknown_reason,
            row.recovery_eligible,
            row.latest_descendant_closed_at,
        )
        for row in report.report.rows
    )


def warm_zombie_reports(
    project_keys: Iterable[str],
    *,
    force: bool = False,
    force_immediate: bool = False,
    telemetry: dict[str, int] | None = None,
) -> dict[str, frozenset[str]]:
    """Refresh stale zombie reports off the event loop.

    A changed store fingerprint invalidates its cached report immediately,
    while the TTL revalidates the collector's session-liveness facts.
    Collector failures stay quiet and do not replace a previous generation
    with the failed fallback report.
    """
    changed: dict[str, frozenset[str]] = {}
    from sase.bead.zombie import load_zombie_report

    project_list = tuple(dict.fromkeys(project_keys))
    if telemetry is not None:
        telemetry["zombie_candidates_examined"] = telemetry.get(
            "zombie_candidates_examined", 0
        ) + len(project_list)
    for project_key in project_list:
        previous = _ZOMBIE_REPORT_CACHE.entry(project_key)
        if telemetry is not None:
            telemetry["zombie_fingerprint_probes"] = (
                telemetry.get("zombie_fingerprint_probes", 0) + 1
            )
        fingerprint = project_store_fingerprint(project_key)
        now = monotonic()
        fingerprint_changed = (
            previous is not None and previous.fingerprint != fingerprint
        )
        if (
            force
            and not force_immediate
            and previous is not None
            and not fingerprint_changed
            and now - previous.computed_at < _FORCED_RECOMPUTE_MIN_INTERVAL_SECONDS
        ):
            continue
        if (
            not force
            and previous is not None
            and previous.fingerprint == fingerprint
            and previous.expires_at > monotonic()
        ):
            continue
        snapshot = load_zombie_report(project_key)
        if snapshot.collection_failed:
            continue
        old_projection = (
            _report_projection(previous.snapshot) if previous is not None else ()
        )
        new_projection = _report_projection(snapshot)
        if old_projection != new_projection:
            old_by_id = (
                {row.plan_id: row for row in previous.snapshot.report.rows}
                if previous is not None
                else {}
            )
            new_by_id = {row.plan_id: row for row in snapshot.report.rows}
            changed[project_key] = frozenset(
                plan_id
                for plan_id in old_by_id.keys() | new_by_id.keys()
                if old_by_id.get(plan_id) != new_by_id.get(plan_id)
            )
        _ZOMBIE_REPORT_CACHE.set(project_key, snapshot, fingerprint)
    if telemetry is not None:
        telemetry["zombie_changed_outcomes"] = telemetry.get(
            "zombie_changed_outcomes", 0
        ) + len(changed)
        telemetry["zombie_unchanged_outcomes"] = telemetry.get(
            "zombie_unchanged_outcomes", 0
        ) + max(0, len(project_list) - len(changed))
    return changed
