"""Project active Agent Hijack ledger state onto TUI rows."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .agent_status import HIJACKED_GLYPH

if TYPE_CHECKING:
    from .agent import Agent

_LoadRecord = Callable[[str], Mapping[str, Any] | None]

_ACTIVE_PRESENTATION_STATES = frozenset(
    {"requested", "latched", "stopping", "held", "resolving"}
)
_MOOT_NOTICE = "finished before the hijack; nothing was held"
_DEFAULT_PENDING_BOUNDARY = "handoff"


@dataclass
class _HijackPendingTracker:
    """Track pending latch IDs across background loader refreshes.

    Observation runs in the artifact-loader worker. Drain the one-shot
    moot notices on the UI thread after the loaded roster is applied.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    pending_ids: set[str] = field(default_factory=set)
    notified_moot_ids: set[str] = field(default_factory=set)
    _notices: list[str] = field(default_factory=list)

    def observe_active_records(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        load_record: _LoadRecord | None = None,
    ) -> None:
        """Update pending IDs and queue one-shot notices for newly moot latches."""
        current: set[str] = set()
        for record in records:
            if not isinstance(record, Mapping):
                continue
            if record.get("state") != "latched":
                continue
            hijack_id = record.get("hijack_id")
            if isinstance(hijack_id, str) and hijack_id:
                current.add(hijack_id)
        with self._lock:
            disappeared = self.pending_ids - current
            already_notified = set(self.notified_moot_ids)
            self.pending_ids = current
        candidates = disappeared - already_notified
        if not candidates:
            return
        if load_record is None:
            from sase.agent.hijack.ledger import load_record as ledger_load

            loader: _LoadRecord = ledger_load
        else:
            loader = load_record
        newly_moot: list[str] = []
        for hijack_id in candidates:
            try:
                settled = loader(hijack_id)
            except Exception:
                continue
            if (
                isinstance(settled, Mapping)
                and settled.get("state") == "finished_first"
            ):
                newly_moot.append(hijack_id)
        if not newly_moot:
            return
        with self._lock:
            for hijack_id in newly_moot:
                if hijack_id in self.notified_moot_ids:
                    continue
                self.notified_moot_ids.add(hijack_id)
                self._notices.append(_MOOT_NOTICE)

    def drain_moot_notices(self) -> tuple[str, ...]:
        """Return and clear one-shot moot notices gathered by the loader."""
        with self._lock:
            notices = tuple(self._notices)
            self._notices.clear()
            return notices

    def reset(self) -> None:
        """Clear pending observation. Tests use this between cases."""
        with self._lock:
            self.pending_ids.clear()
            self.notified_moot_ids.clear()
            self._notices.clear()


HIJACK_PENDING_TRACKER = _HijackPendingTracker()


def pending_hijack_boundary(record: Mapping[str, Any] | None) -> str:
    """Return the durable boundary label for a pending latch overlay."""
    if not isinstance(record, Mapping):
        return _DEFAULT_PENDING_BOUNDARY
    for key in ("boundary", "boundary_hint"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("_", " ")
    return _DEFAULT_PENDING_BOUNDARY


def pending_hijack_status_text(record: Mapping[str, Any] | None = None) -> str:
    """Return the row status text for a still-pending latch."""
    return f"{HIJACKED_GLYPH} HIJACK PENDING · after {pending_hijack_boundary(record)}"


def drain_hijack_moot_notices() -> tuple[str, ...]:
    """Return one-shot moot notices collected by the background loader."""
    return HIJACK_PENDING_TRACKER.drain_moot_notices()


def _diff_summary(record: Mapping[str, Any]) -> str | None:
    """Format the bounded repository diff counts captured at hijack time."""
    diffs = record.get("repo_diffs")
    if not isinstance(diffs, list):
        return None
    files = insertions = deletions = 0
    for diff in diffs:
        if not isinstance(diff, Mapping):
            continue
        try:
            files += int(diff.get("files_changed") or 0)
            insertions += int(diff.get("insertions") or 0)
            deletions += int(diff.get("deletions") or 0)
        except (TypeError, ValueError):
            continue
    if files <= 0:
        return None
    return f"{files} files +{insertions} −{deletions}"


def apply_hijack_ledger_presentation(agents: Iterable[Agent]) -> None:
    """Apply overlays and held-workspace summaries from one active-ledger read.

    Call from the artifact-loader worker. The ledger is the durable source for
    requested/latched/stopping/resolving state; these fields remain
    presentation-only. Pending status comes from the durable record, not from
    process liveness.
    """
    rows = list(agents)
    for agent in rows:
        agent.hijack_overlay = None
        agent.hijack_diff_summary = None
        agent.hijack_record = None

    try:
        from sase.agent.hijack.ledger import list_active_records

        records = list_active_records()
    except Exception:
        # A stale or unreadable presentation hint cannot block the agent list.
        records = []

    HIJACK_PENDING_TRACKER.observe_active_records(records)

    by_artifacts_dir: dict[str, Mapping[str, Any]] = {}
    by_agent_name: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        state = record.get("state")
        if state not in _ACTIVE_PRESENTATION_STATES:
            continue
        artifacts_dir = record.get("artifacts_dir")
        if isinstance(artifacts_dir, str) and artifacts_dir:
            by_artifacts_dir.setdefault(artifacts_dir, record)
        agent_name = record.get("agent_name")
        if isinstance(agent_name, str) and agent_name:
            by_agent_name.setdefault(agent_name, record)

    loaded_by_id: dict[str, dict[str, Any] | None] = {}
    for agent in rows:
        try:
            artifacts_dir = agent.get_artifacts_dir()
        except Exception:
            artifacts_dir = None
        matched_record = None
        if isinstance(artifacts_dir, str) and artifacts_dir:
            matched_record = by_artifacts_dir.get(artifacts_dir)
        if matched_record is None:
            name = getattr(agent, "agent_name", None)
            if isinstance(name, str) and name:
                matched_record = by_agent_name.get(name)
        if matched_record is None and agent.status == "HIJACKED":
            hijack_id = agent.hijack_id
            if isinstance(hijack_id, str) and hijack_id:
                if hijack_id not in loaded_by_id:
                    try:
                        from sase.agent.hijack.ledger import load_record

                        loaded_by_id[hijack_id] = load_record(hijack_id)
                    except Exception:
                        loaded_by_id[hijack_id] = None
                matched_record = loaded_by_id[hijack_id]
        if matched_record is None:
            continue
        _apply_matched_record(agent, matched_record)

    from ._agent_status_apply import mirror_hijack_overlays_to_containers

    mirror_hijack_overlays_to_containers(rows)

    try:
        from sase.agent.hijack.referral import apply_remote_hijack_referrals

        apply_remote_hijack_referrals(rows)
    except Exception:
        pass


def _apply_matched_record(agent: Agent, matched_record: Mapping[str, Any]) -> None:
    """Project one durable record onto a member or container row."""
    agent.hijack_record = dict(matched_record)
    hijack_id = matched_record.get("hijack_id")
    if isinstance(hijack_id, str) and hijack_id:
        agent.hijack_id = hijack_id
    state = matched_record.get("state")
    if state == "latched":
        agent.hijack_overlay = "pending"
    elif state in {"requested", "stopping"}:
        agent.hijack_overlay = "hijacking"
    elif state == "resolving":
        agent.hijack_overlay = "recovering"
    elif state == "held":
        agent.hijack_diff_summary = _diff_summary(matched_record)


__all__ = [
    "HIJACK_PENDING_TRACKER",
    "apply_hijack_ledger_presentation",
    "drain_hijack_moot_notices",
    "pending_hijack_boundary",
    "pending_hijack_status_text",
]
