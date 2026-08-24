"""Select the agents a hard-disabled provider stranded.

Selection takes one :func:`~sase.agent.running_listing.list_all_agents`
snapshot and narrows it to the rows a provider drain can act on: live rows
still burning quota, plus recently-failed rows that hit that provider's own
usage limit. Monitor members, rows holding a pending question, and the
calling agent match the provider but are dropped and reported as skips
instead of candidates. Everything else in the snapshot (a different
provider, a long-finished row) is silently irrelevant to this drain.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sase.agent._drain_types import ProviderDrainSkip
from sase.agent._restart_reads import optional_str, read_json_dict
from sase.agent.running_listing import RunningAgentInfo
from sase.llm_provider.provider_disable import TemporaryProviderDisable

_FAILED_GRACE_SECONDS = 300

_LIVE_STATUSES = frozenset({"STARTING", "RUNNING", "WAITING"})
_PENDING_QUESTION_STATUSES = frozenset({"QUESTION", "ANSWERED"})

# WAITING first, RUNNING last: the least-progress move is the cheapest one
# to lose to a --limit truncation.
_ORDER_PRIORITY = {"WAITING": 0, "STARTING": 1, "FAILED": 2, "RUNNING": 3}

_DROP_DETAIL = {
    "monitor": "monitor rows supervise a shell command, not provider quota",
    "pending_question": "holding a pending question; a restart would destroy it",
    "caller": "this is the agent running the drain",
}


def select_drain_candidates(
    snapshot: Sequence[RunningAgentInfo],
    provider: str,
    disable: TemporaryProviderDisable,
) -> tuple[list[RunningAgentInfo], list[ProviderDrainSkip]]:
    """Return ordered drain candidates for *provider*, plus initial skips.

    Candidates are ordered least-progress-first (``WAITING``, ``STARTING``,
    ``FAILED``, ``RUNNING``), ties broken on *snapshot*'s existing
    most-recent-first order.
    """
    caller_name = _caller_agent_name()
    candidates: list[RunningAgentInfo] = []
    skips: list[ProviderDrainSkip] = []
    for row in snapshot:
        if row.name is None or not row.artifacts_dir:
            continue
        if (
            row.status not in _LIVE_STATUSES
            and row.status != "FAILED"
            and row.status not in _PENDING_QUESTION_STATUSES
        ):
            continue
        artifacts_dir = Path(row.artifacts_dir)
        if not _matches_provider(row, artifacts_dir, provider):
            continue
        if row.status == "FAILED" and not _recently_failed_on_provider(
            artifacts_dir, provider, disable
        ):
            continue
        reason = _drop_reason(row, caller_name)
        if reason is not None:
            skips.append(_skip_for(row, reason))
            continue
        candidates.append(row)
    candidates.sort(
        key=lambda row: _ORDER_PRIORITY.get(row.status, len(_ORDER_PRIORITY))
    )
    return candidates, skips


def _matches_provider(
    row: RunningAgentInfo, artifacts_dir: Path, provider: str
) -> bool:
    meta = read_json_dict(artifacts_dir / "agent_meta.json")
    effective_provider = optional_str(meta.get("exec_llm_provider")) or row.provider
    return effective_provider == provider


def _recently_failed_on_provider(
    artifacts_dir: Path, provider: str, disable: TemporaryProviderDisable
) -> bool:
    from sase.llm_provider.usage_limit_config import detect_usage_limit

    done = read_json_dict(artifacts_dir / "done.json")
    finished_at = done.get("finished_at")
    if not isinstance(finished_at, int | float):
        return False
    if float(finished_at) < disable.created_at - _FAILED_GRACE_SECONDS:
        return False
    error = optional_str(done.get("error"))
    if error is None:
        return False
    return detect_usage_limit(provider, error) is not None


def _drop_reason(row: RunningAgentInfo, caller_name: str | None) -> str | None:
    if row.is_monitor:
        return "monitor"
    if row.status in _PENDING_QUESTION_STATUSES:
        return "pending_question"
    if caller_name is not None and row.name == caller_name:
        return "caller"
    return None


def _skip_for(row: RunningAgentInfo, reason: str) -> ProviderDrainSkip:
    from sase.core.agent_identity_facade import present_agent_name

    name = row.name or ""
    return ProviderDrainSkip(
        name=name,
        presented_name=present_agent_name(name) if name else name,
        status=row.status,
        reason=reason,
        detail=_DROP_DETAIL[reason],
    )


def _caller_agent_name() -> str | None:
    from sase.agent.identity import discover_agent_identity

    identity = discover_agent_identity()
    return identity.name if identity is not None else None
