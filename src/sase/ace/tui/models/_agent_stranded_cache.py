"""Cached stranded-work reports for Agents-tab rows."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from sase.bead.stranded import StrandedReport
    from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict

    from .agent import Agent

STRANDED_REPORT_CACHE_MISS: Final = object()
_CACHE_TTL_SECONDS: Final = 60.0
_FORCED_RECOMPUTE_MIN_INTERVAL_SECONDS: Final = 30.0
_CACHE_MAX_ENTRIES: Final = 64


@dataclass(frozen=True, slots=True)
class _CachedProjectReport:
    expires_at: float
    computed_at: float
    fingerprint: str | None
    snapshot: StrandedReport
    verdict_index: dict[str, StrandedWorkVerdict]


class _StrandedReportCache:
    """Small TTL- and bead-store-fingerprint-bounded report cache."""

    def __init__(self, *, max_entries: int) -> None:
        self._entries: OrderedDict[str, _CachedProjectReport] = OrderedDict()
        self._max_entries = max_entries
        self._lock = RLock()
        self._count_project_keys: tuple[str, ...] | None = None
        self._count_reports: tuple[StrandedReport | None, ...] = ()
        self._count_value = 0
        self._generation = 0

    def get(self, project_key: str) -> StrandedReport | object:
        with self._lock:
            entry = self._entries.get(project_key)
            if entry is None:
                return STRANDED_REPORT_CACHE_MISS
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

    def verdict_index(self, project_key: str) -> dict[str, StrandedWorkVerdict] | None:
        """Return the index built when the project's report was stored."""
        with self._lock:
            entry = self._entries.get(project_key)
            if entry is not None:
                self._entries.move_to_end(project_key)
                return entry.verdict_index
            return None

    def report_token(self) -> tuple[object, ...]:
        """Return identities for all cached reports without exposing cache state."""
        with self._lock:
            snapshots = tuple(
                sorted(
                    (key, id(entry.snapshot)) for key, entry in self._entries.items()
                )
            )
            return (self._generation, snapshots)

    def stranded_count(self, project_keys: tuple[str, ...]) -> int:
        """Memoize the count until a represented report or project set changes."""
        with self._lock:
            reports = tuple(
                entry.snapshot
                if (entry := self._entries.get(key)) is not None
                else None
                for key in project_keys
            )
            if (
                project_keys == self._count_project_keys
                and len(reports) == len(self._count_reports)
                and all(
                    current is cached
                    for current, cached in zip(
                        reports, self._count_reports, strict=True
                    )
                )
            ):
                for key in project_keys:
                    if key in self._entries:
                        self._entries.move_to_end(key)
                return self._count_value

            self._count_project_keys = project_keys
            self._count_reports = reports
            self._count_value = sum(
                len(snapshot.report.stranded_ids)
                for snapshot in reports
                if snapshot is not None
            )
            for key in project_keys:
                if key in self._entries:
                    self._entries.move_to_end(key)
            return self._count_value

    def set(
        self,
        project_key: str,
        snapshot: StrandedReport,
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
                verdict_index={
                    verdict.bead_id: verdict for verdict in snapshot.report.verdicts
                },
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
            self._count_project_keys = None
            self._count_reports = ()
            self._count_value = 0
            self._generation += 1


_STRANDED_REPORT_CACHE = _StrandedReportCache(max_entries=_CACHE_MAX_ENTRIES)


def stranded_report_cache() -> _StrandedReportCache:
    """Return the shared report cache for the private stranded-work modules."""
    return _STRANDED_REPORT_CACHE


def stranded_project_key_for_agent(agent: Agent) -> str | None:
    """Return the bead-store project key already attached to an agent row."""
    project_file = getattr(agent, "project_file", None)
    if not project_file:
        return None
    return _stranded_project_key_for_project_file(str(project_file))


@lru_cache(maxsize=1024)
def _stranded_project_key_for_project_file(project_file: str) -> str | None:
    """Boundedly memoize project-key derivation shared by rendered rows."""
    project_key = Path(project_file).parent.name
    return project_key or None


def _cached_stranded_report(project_key: str) -> StrandedReport | None:
    """Return the latest in-memory report for *project_key*, even if expired."""
    snapshot = _STRANDED_REPORT_CACHE.get(project_key)
    return None if snapshot is STRANDED_REPORT_CACHE_MISS else snapshot  # type: ignore[return-value]


def cached_stranded_report_for_agent(agent: Agent) -> StrandedReport | None:
    """Return the warm project report for *agent*, without resolving or I/O."""
    project_key = stranded_project_key_for_agent(agent)
    return _cached_stranded_report(project_key) if project_key is not None else None


def cached_stranded_report(project_key: str) -> StrandedReport | None:
    """Return the warm report for a project, without filesystem access."""
    return _cached_stranded_report(project_key)


def should_resolve_stranded_report(project_key: str) -> bool:
    """Return whether a project's report is cold or past its TTL."""
    return _STRANDED_REPORT_CACHE.should_resolve(project_key)


def stranded_report_resolution_reason(project_key: str) -> str | None:
    """Return ``cold`` or ``ttl`` when a project report needs refreshing."""
    entry = _STRANDED_REPORT_CACHE.entry(project_key)
    if entry is None:
        return "cold"
    return "ttl" if entry.expires_at <= monotonic() else None


def force_stranded_refresh(project_key: str) -> None:
    """Expire the cached report so the next warmup reloads it immediately."""
    _STRANDED_REPORT_CACHE.expire(project_key)


def stranded_project_keys(agents: Iterable[Agent]) -> tuple[str, ...]:
    """Return unique project keys represented by the supplied agent rows."""
    return tuple(
        dict.fromkeys(
            project_key
            for agent in agents
            if (project_key := stranded_project_key_for_agent(agent)) is not None
        )
    )


def _project_fingerprint(project_key: str) -> str | None:
    """Read the bead-store fingerprint; called only by the warmup worker."""
    from sase.bead.store_locator import canonical_beads_dir_for_project

    beads_dir = canonical_beads_dir_for_project(project_key)
    if beads_dir is None:
        return None
    try:
        from sase.core.bead_read_facade import store_fingerprint

        fingerprint = store_fingerprint(beads_dir)
    except Exception:  # noqa: BLE001 - fingerprint fallback stays fail-open.
        fingerprint = None
    if fingerprint is not None:
        return fingerprint.token
    try:
        stat = (beads_dir / "issues.jsonl").stat()
    except OSError:
        return None
    return f"mtime:{stat.st_mtime_ns}:{stat.st_size}"


def _report_projection(report: StrandedWorkReport) -> tuple[tuple[object, ...], ...]:
    """Keep report comparisons limited to values that affect this surface."""
    return tuple(
        (
            verdict.bead_id,
            verdict.kind,
            verdict.state,
            verdict.reason,
            verdict.blocked_by,
            verdict.parent_id,
        )
        for verdict in report.verdicts
    )


def warm_stranded_work_reports(
    project_keys: Iterable[str],
    *,
    force: bool = False,
    force_immediate: bool = False,
    telemetry: dict[str, int] | None = None,
) -> dict[str, frozenset[str]]:
    """Refresh stale reports off the event loop and return changed bead IDs.

    A changed store fingerprint invalidates its cached report immediately,
    while the TTL revalidates the collector's process/artifact-liveness facts.
    Collector failures stay quiet and do not replace a previous generation
    with the empty fallback report. Lock-contended partial reports, like
    collector failures, never replace a complete generation.
    """
    changed: dict[str, frozenset[str]] = {}
    from sase.bead.stranded import load_stranded_report

    project_list = tuple(dict.fromkeys(project_keys))
    if telemetry is not None:
        telemetry["stranded_candidates_examined"] = telemetry.get(
            "stranded_candidates_examined", 0
        ) + len(project_list)
    for project_key in project_list:
        previous = _STRANDED_REPORT_CACHE.entry(project_key)
        if telemetry is not None:
            telemetry["stranded_fingerprint_probes"] = (
                telemetry.get("stranded_fingerprint_probes", 0) + 1
            )
        fingerprint = _project_fingerprint(project_key)
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
        snapshot = load_stranded_report(project_key)
        if snapshot.collection_failed:
            continue
        if (
            snapshot.degraded
            and previous is not None
            and not previous.snapshot.degraded
        ):
            if telemetry is not None:
                telemetry["stranded_degraded_skips"] = (
                    telemetry.get("stranded_degraded_skips", 0) + 1
                )
            continue
        if telemetry is not None:
            if snapshot.stable_rebuild:
                telemetry["stranded_heavy_resolutions"] = (
                    telemetry.get("stranded_heavy_resolutions", 0) + 1
                )
            else:
                telemetry["stranded_liveness_checks"] = (
                    telemetry.get("stranded_liveness_checks", 0) + 1
                )
        old_projection = (
            _report_projection(previous.snapshot.report) if previous is not None else ()
        )
        new_projection = _report_projection(snapshot.report)
        if old_projection != new_projection:
            old_by_id = {
                verdict.bead_id: verdict
                for verdict in (
                    previous.snapshot.report.verdicts if previous is not None else ()
                )
            }
            new_by_id = {
                verdict.bead_id: verdict for verdict in snapshot.report.verdicts
            }
            changed_ids = frozenset(
                bead_id
                for bead_id in old_by_id.keys() | new_by_id.keys()
                if old_by_id.get(bead_id) != new_by_id.get(bead_id)
            )
            changed[project_key] = changed_ids
        _STRANDED_REPORT_CACHE.set(project_key, snapshot, fingerprint)
    if telemetry is not None:
        telemetry["stranded_changed_outcomes"] = telemetry.get(
            "stranded_changed_outcomes", 0
        ) + len(changed)
        telemetry["stranded_unchanged_outcomes"] = telemetry.get(
            "stranded_unchanged_outcomes", 0
        ) + max(0, len(project_list) - len(changed))
    return changed
