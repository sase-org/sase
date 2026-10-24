"""Cached, memory-only stranded-work views for Agents-tab rows.

The stranded-work collector reads bead and artifact stores, so it only runs in
the Agents tab's deferred bead warmup worker. Renderers use the report snapshot
below and never touch disk.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import TYPE_CHECKING, Final

from sase.agent.bead_display import derive_agent_bead_id_from_name

if TYPE_CHECKING:
    from sase.bead.stranded import StrandedReport
    from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict

    from .agent import Agent

STRANDED_REPORT_CACHE_MISS: Final = object()
_CACHE_TTL_SECONDS: Final = 15.0
_CACHE_MAX_ENTRIES: Final = 64


@dataclass(frozen=True, slots=True)
class _AgentStrandedView:
    """Cached stranded state that can affect one rendered agent row."""

    verdict: StrandedWorkVerdict | None = None
    waiting_on: tuple[tuple[str, str], ...] = ()
    clan_stranded_ids: tuple[str, ...] = ()
    clan_stranded_member_keys: tuple[str, ...] = ()

    @property
    def signature(self) -> tuple[object, ...]:
        """Return the immutable presentation inputs for row-render caching."""
        verdict = self.verdict
        return (
            None
            if verdict is None
            else (
                verdict.bead_id,
                verdict.state,
                verdict.reason,
                verdict.blocked_by,
            ),
            self.waiting_on,
            self.clan_stranded_ids,
            self.clan_stranded_member_keys,
        )


@dataclass(frozen=True, slots=True)
class _CachedProjectReport:
    expires_at: float
    fingerprint: str | None
    snapshot: StrandedReport


class _StrandedReportCache:
    """Small TTL- and bead-store-fingerprint-bounded report cache."""

    def __init__(self, *, max_entries: int) -> None:
        self._entries: OrderedDict[str, _CachedProjectReport] = OrderedDict()
        self._max_entries = max_entries
        self._lock = RLock()

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

    def set(
        self,
        project_key: str,
        snapshot: StrandedReport,
        fingerprint: str | None,
    ) -> None:
        with self._lock:
            self._entries[project_key] = _CachedProjectReport(
                expires_at=monotonic() + _CACHE_TTL_SECONDS,
                fingerprint=fingerprint,
                snapshot=snapshot,
            )
            self._entries.move_to_end(project_key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_STRANDED_REPORT_CACHE = _StrandedReportCache(max_entries=_CACHE_MAX_ENTRIES)


def stranded_project_key_for_agent(agent: Agent) -> str | None:
    """Return the bead-store project key already attached to an agent row."""
    project_file = getattr(agent, "project_file", None)
    if not project_file:
        return None
    project_key = Path(str(project_file)).parent.name
    return project_key or None


def _agent_bead_id_for_stranded(agent: Agent) -> str | None:
    """Return the bead candidate attached to a real Agents-tab agent node."""
    from .agent_nodes import is_agents_tab_agent_node

    if not is_agents_tab_agent_node(agent):
        return None
    phase_bead_id = getattr(agent, "phase_bead_id", None)
    if isinstance(phase_bead_id, str) and phase_bead_id.strip():
        return phase_bead_id.strip()
    return derive_agent_bead_id_from_name(
        getattr(agent, "presented_agent_name", None)
        or getattr(agent, "agent_name", None)
    )


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
        )
        for verdict in report.verdicts
    )


def warm_stranded_work_reports(
    project_keys: Iterable[str],
    *,
    force: bool = False,
) -> dict[str, frozenset[str]]:
    """Refresh stale reports off the event loop and return changed bead IDs.

    A changed store fingerprint invalidates its cached report immediately,
    while the TTL revalidates the collector's process/artifact-liveness facts.
    Store and collector failures remain quiet because the shared loader returns
    an empty report on failure.
    """
    changed: dict[str, frozenset[str]] = {}
    from sase.bead.stranded import load_stranded_report

    for project_key in dict.fromkeys(project_keys):
        previous = _STRANDED_REPORT_CACHE.entry(project_key)
        fingerprint = _project_fingerprint(project_key)
        if (
            not force
            and previous is not None
            and previous.fingerprint == fingerprint
            and previous.expires_at > monotonic()
        ):
            continue
        snapshot = load_stranded_report(project_key)
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
    return changed


def _verdict_index(project_key: str | None) -> dict[str, StrandedWorkVerdict]:
    if project_key is None:
        return {}
    snapshot = _cached_stranded_report(project_key)
    if snapshot is None:
        return {}
    return {verdict.bead_id: verdict for verdict in snapshot.report.verdicts}


def _stranded_verdict_for_agent(agent: Agent) -> StrandedWorkVerdict | None:
    """Return the cached verdict for the bead attached to *agent*, if any."""
    bead_id = _agent_bead_id_for_stranded(agent)
    if bead_id is None:
        return None
    return _verdict_index(stranded_project_key_for_agent(agent)).get(bead_id)


def _clan_wave_member_key(agent: Agent) -> str:
    return (
        f"{agent.agent_type.value}:{agent.cl_name}:"
        f"{agent.raw_suffix or ''}:{agent.agent_name or ''}"
    )


def agent_stranded_view(agent: Agent) -> _AgentStrandedView:
    """Build row overlays from warm reports without filesystem access."""
    from .agent_time import wait_display_agent

    verdict = _stranded_verdict_for_agent(agent)
    wait_agent = wait_display_agent(agent)
    waiting_on: list[tuple[str, str]] = []
    wait_project = stranded_project_key_for_agent(
        wait_agent
    ) or stranded_project_key_for_agent(agent)
    wait_verdicts = _verdict_index(wait_project)
    for bead_id in getattr(wait_agent, "waiting_for_beads", ()):
        target = wait_verdicts.get(bead_id)
        if target is not None and target.state in {"stranded", "blocked"}:
            waiting_on.append((bead_id, target.state))

    clan_stranded: set[str] = set()
    clan_member_keys: set[str] = set()
    if getattr(agent, "is_clan_container", False):
        from ._agent_clan import clan_members

        for member in clan_members(agent):
            member_bead_id = _agent_bead_id_for_stranded(member)
            member_verdict = _verdict_index(stranded_project_key_for_agent(member)).get(
                member_bead_id or ""
            )
            if member_verdict is None or member_verdict.state != "stranded":
                continue
            clan_stranded.add(member_verdict.bead_id)
            clan_member_keys.add(_clan_wave_member_key(member))

    return _AgentStrandedView(
        verdict=verdict,
        waiting_on=tuple(sorted(waiting_on)),
        clan_stranded_ids=tuple(sorted(clan_stranded)),
        clan_stranded_member_keys=tuple(sorted(clan_member_keys)),
    )


def stranded_count_for_agents(agents: Iterable[Agent]) -> int:
    """Count unique stranded beads in reports for the represented projects."""
    return sum(
        len(snapshot.report.stranded_ids)
        for project_key in stranded_project_keys(agents)
        if (snapshot := _cached_stranded_report(project_key)) is not None
    )


__all__ = [
    "agent_stranded_view",
    "cached_stranded_report",
    "cached_stranded_report_for_agent",
    "should_resolve_stranded_report",
    "stranded_count_for_agents",
    "stranded_project_key_for_agent",
    "stranded_project_keys",
    "warm_stranded_work_reports",
]
