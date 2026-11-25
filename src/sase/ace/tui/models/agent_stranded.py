"""Cached, memory-only stranded-work views for Agents-tab rows.

The stranded-work collector reads bead and artifact stores, so it only runs in
the Agents tab's deferred bead warmup worker. Renderers use the report snapshot
below and never touch disk.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
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
_CACHE_TTL_SECONDS: Final = 60.0
_FORCED_RECOMPUTE_MIN_INTERVAL_SECONDS: Final = 30.0
_CACHE_MAX_ENTRIES: Final = 64


@dataclass(frozen=True, slots=True)
class _AgentStrandedView:
    """Cached stranded state that can affect one rendered agent row."""

    verdict: StrandedWorkVerdict | None = None
    waiting_on: tuple[tuple[str, str], ...] = ()
    waiting_on_agents: tuple[tuple[str, str], ...] = ()
    clan_stranded_ids: tuple[str, ...] = ()
    clan_stranded_member_keys: tuple[str, ...] = ()
    clan_leaf_direct: bool = False
    wait_project: str | None = None
    clan_project: str | None = None

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
            self.waiting_on_agents,
            self.clan_stranded_ids,
            self.clan_stranded_member_keys,
            self.clan_leaf_direct,
        )


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
        _reset_surfaced_count_memo()

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
        _reset_surfaced_count_memo()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._count_project_keys = None
            self._count_reports = ()
            self._count_value = 0
        _reset_surfaced_count_memo()


def _reset_surfaced_count_memo() -> None:
    """Drop the memoized surfaced count after any report mutation."""
    global _surfaced_count_key, _surfaced_count_value
    # Defined after this class; resolved at call time.
    with _SURFACED_COUNT_LOCK:
        _surfaced_count_key = None
        _surfaced_count_value = 0


_STRANDED_REPORT_CACHE = _StrandedReportCache(max_entries=_CACHE_MAX_ENTRIES)


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


def _verdict_index(project_key: str | None) -> dict[str, StrandedWorkVerdict]:
    if project_key is None:
        return {}
    return _STRANDED_REPORT_CACHE.verdict_index(project_key) or {}


def _stranded_verdict_for_agent(agent: Agent) -> StrandedWorkVerdict | None:
    """Return the cached verdict for the bead attached to *agent*, if any."""
    bead_id = _agent_bead_id_for_stranded(agent)
    if bead_id is None:
        return None
    return _verdict_index(stranded_project_key_for_agent(agent)).get(bead_id)


def stranded_leaf_verdict(agent: Agent) -> StrandedWorkVerdict | None:
    """Return the cached stranded verdict for a real agent row."""
    verdict = _stranded_verdict_for_agent(agent)
    return verdict if verdict is not None and verdict.state == "stranded" else None


def _clan_wave_member_key(agent: Agent) -> str:
    return (
        f"{agent.agent_type.value}:{agent.cl_name}:"
        f"{agent.raw_suffix or ''}:{agent.agent_name or ''}"
    )


def _clan_epic_id(agent: Agent) -> str | None:
    """Return the epic bead ID a clan container is named after."""
    clan = getattr(agent, "agent_clan", None)
    if isinstance(clan, str) and clan.strip():
        return clan.strip()
    name = getattr(agent, "presented_agent_name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _flagged_wait_target(
    bead_id: str | None, verdicts: dict[str, StrandedWorkVerdict]
) -> tuple[str, str] | None:
    if not bead_id:
        return None
    target = verdicts.get(bead_id)
    if target is None or target.state not in {"stranded", "blocked"}:
        return None
    return (target.bead_id, target.state)


def agent_stranded_view(agent: Agent) -> _AgentStrandedView:
    """Build row overlays from warm reports without filesystem access."""
    from .agent_time import wait_display_agent

    verdict = _stranded_verdict_for_agent(agent)
    wait_agent = wait_display_agent(agent)
    waiting_on: list[tuple[str, str]] = []
    waiting_on_agents: list[tuple[str, str]] = []
    wait_project = stranded_project_key_for_agent(
        wait_agent
    ) or stranded_project_key_for_agent(agent)
    wait_verdicts = _verdict_index(wait_project)
    for bead_id in getattr(wait_agent, "waiting_for_beads", ()):
        flagged = _flagged_wait_target(bead_id, wait_verdicts)
        if flagged is not None:
            waiting_on.append(flagged)
    for name in getattr(wait_agent, "waiting_for", ()):
        flagged = _flagged_wait_target(
            derive_agent_bead_id_from_name(name), wait_verdicts
        )
        if flagged is not None:
            waiting_on_agents.append(flagged)

    clan_stranded: set[str] = set()
    clan_member_keys: set[str] = set()
    clan_leaf_direct = False
    clan_project: str | None = None
    if getattr(agent, "is_clan_container", False):
        from ._agent_clan import clan_members

        members = clan_members(agent)
        project_key = stranded_project_key_for_agent(agent)
        if project_key is None:
            for member in members:
                project_key = stranded_project_key_for_agent(member)
                if project_key is not None:
                    break
        clan_project = project_key
        verdicts = _verdict_index(project_key)
        epic_id = _clan_epic_id(agent)
        epic_verdict = verdicts.get(epic_id) if epic_id else None
        if epic_verdict is not None:
            if epic_verdict.state == "stranded":
                clan_stranded.add(epic_verdict.bead_id)
            clan_stranded.update(epic_verdict.blocked_by)
        for member in members:
            member_bead_id = _agent_bead_id_for_stranded(member)
            member_verdict = _verdict_index(stranded_project_key_for_agent(member)).get(
                member_bead_id or ""
            )
            if member_verdict is None:
                continue
            if member_verdict.state == "stranded":
                clan_stranded.add(member_verdict.bead_id)
            if member_verdict.state in {"stranded", "blocked"}:
                clan_member_keys.add(_clan_wave_member_key(member))
        if epic_verdict is not None and epic_verdict.state == "stranded":
            clan_leaf_direct = True
        elif epic_id:
            clan_leaf_direct = any(
                (leaf := verdicts.get(leaf_id)) is not None
                and leaf.parent_id == epic_id
                for leaf_id in clan_stranded
            )

    return _AgentStrandedView(
        verdict=verdict,
        waiting_on=tuple(sorted(waiting_on)),
        waiting_on_agents=tuple(sorted(waiting_on_agents)),
        clan_stranded_ids=tuple(sorted(clan_stranded)),
        clan_stranded_member_keys=tuple(sorted(clan_member_keys)),
        clan_leaf_direct=clan_leaf_direct,
        wait_project=wait_project,
        clan_project=clan_project,
    )


def stranded_count_for_agents(agents: Iterable[Agent]) -> int:
    """Count unique stranded beads in reports for the represented projects."""
    project_keys = tuple(sorted(set(stranded_project_keys(agents))))
    return _STRANDED_REPORT_CACHE.stranded_count(project_keys)


def cached_stranded_verdict_state(project: str, bead_id: str) -> str | None:
    """Return the cached verdict state for one bead without filesystem access.

    This is the O(1) verdict-index lookup shared by Beads filtering. It never
    scans every verdict the way a linear search would.
    """
    index = _STRANDED_REPORT_CACHE.verdict_index(project)
    if not index:
        return None
    verdict = index.get(bead_id)
    return None if verdict is None else verdict.state


def stranded_verdict_for_bead(project: str, bead_id: str) -> StrandedWorkVerdict | None:
    """Return the cached verdict for one bead without filesystem access."""
    index = _STRANDED_REPORT_CACHE.verdict_index(project)
    if not index:
        return None
    return index.get(bead_id)


def stranded_snapshot_token(project_keys: Iterable[str]) -> tuple[object, ...]:
    """Return an identity token for the cached reports of *project_keys*.

    The token changes whenever any represented report snapshot is replaced,
    so filter indexes can rebuild without scanning verdicts on the key path.
    """
    token: list[object] = []
    for key in sorted(set(project_keys)):
        entry = _STRANDED_REPORT_CACHE.entry(key)
        token.append((key, None if entry is None else id(entry.snapshot)))
    return tuple(token)


_SURFACED_COUNT_LOCK = RLock()
_surfaced_count_key: tuple[object, ...] | None = None
_surfaced_count_value = 0


def _surfaced_reports_token() -> tuple[object, ...]:
    """Return an identity token over every cached stranded report."""
    with _STRANDED_REPORT_CACHE._lock:
        return tuple(
            sorted(
                (key, id(entry.snapshot))
                for key, entry in _STRANDED_REPORT_CACHE._entries.items()
            )
        )


def surfaced_stranded_leaves(agent: Agent) -> tuple[tuple[str, str], ...]:
    """Return the ``(project_key, bead_id)`` stranded leaves one row flags.

    Only stranded leaves count: the row's own stranded verdict, stranded
    ``waiting_on`` / ``waiting_on_agents`` targets, and stranded ids in a
    clan container's subtree. Blocked (breadcrumb) states never count.
    """
    view = agent_stranded_view(agent)
    leaves: set[tuple[str, str]] = set()
    verdict = view.verdict
    if verdict is not None and verdict.state == "stranded":
        project = stranded_project_key_for_agent(agent)
        if project is not None:
            leaves.add((project, verdict.bead_id))
    wait_project = view.wait_project or stranded_project_key_for_agent(agent)
    if wait_project is not None:
        for bead_id, state in (*view.waiting_on, *view.waiting_on_agents):
            if state == "stranded":
                leaves.add((wait_project, bead_id))
    clan_project = view.clan_project or stranded_project_key_for_agent(agent)
    if clan_project is not None and view.clan_stranded_ids:
        index = _verdict_index(clan_project)
        for bead_id in view.clan_stranded_ids:
            leaf = index.get(bead_id)
            if leaf is not None and leaf.state == "stranded":
                leaves.add((clan_project, bead_id))
            elif leaf is None:
                # The clan view only collects ids from cached verdicts, so a
                # missing index entry means the report turned over mid-read.
                # Keep the flagged id so a racing refresh cannot hide a leaf.
                leaves.add((clan_project, bead_id))
    return tuple(sorted(leaves))


def surfaced_stranded_count(
    agents: Iterable[Agent],
    app: object | None = None,
) -> int:
    """Count distinct stranded leaves flagged on loaded rows.

    The union is over :func:`surfaced_stranded_leaves`, so every counted leaf
    has a reachable Agents-tab row. The result is memoized keyed by roster
    generation, roster identity/length, and cached report identities, staying
    O(1) on a cache hit because the info strip refreshes often.
    """
    roster = tuple(agents)
    generation: object = None
    tribe_generation: object = None
    if app is not None:
        try:
            from sase.ace.tui.actions.agents._roster_generation import (
                get_roster_generation,
                get_tribe_assignment_generation,
            )

            generation = get_roster_generation(app)
            tribe_generation = get_tribe_assignment_generation(app)
        except Exception:  # noqa: BLE001 - memo key stays fail-open.
            generation = None
            tribe_generation = None
    key = (
        generation,
        tribe_generation,
        id(agents),
        len(roster),
        _surfaced_reports_token(),
    )
    global _surfaced_count_key, _surfaced_count_value
    with _SURFACED_COUNT_LOCK:
        if _surfaced_count_key is not None and _surfaced_count_key == key:
            return _surfaced_count_value
    seen: set[tuple[str, str]] = set()
    for agent in roster:
        seen.update(surfaced_stranded_leaves(agent))
    value = len(seen)
    with _SURFACED_COUNT_LOCK:
        _surfaced_count_key = key
        _surfaced_count_value = value
    return value


__all__ = [
    "agent_stranded_view",
    "cached_stranded_report",
    "cached_stranded_report_for_agent",
    "cached_stranded_verdict_state",
    "force_stranded_refresh",
    "should_resolve_stranded_report",
    "stranded_count_for_agents",
    "stranded_leaf_verdict",
    "stranded_project_key_for_agent",
    "stranded_project_keys",
    "stranded_snapshot_token",
    "stranded_verdict_for_bead",
    "surfaced_stranded_count",
    "surfaced_stranded_leaves",
    "warm_stranded_work_reports",
]
