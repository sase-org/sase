"""Project active Agent Hijack ledger state onto TUI rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent import Agent


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
    requested/stopping/resolving state; these fields remain presentation-only.
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

    by_artifacts_dir: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        artifacts_dir = record.get("artifacts_dir")
        if not isinstance(artifacts_dir, str) or not artifacts_dir:
            continue
        state = record.get("state")
        if state not in {"requested", "stopping", "held", "resolving"}:
            continue
        by_artifacts_dir.setdefault(artifacts_dir, record)

    loaded_by_id: dict[str, dict[str, Any] | None] = {}
    for agent in rows:
        try:
            artifacts_dir = agent.get_artifacts_dir()
        except Exception:
            continue
        matched_record = by_artifacts_dir.get(artifacts_dir or "")
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
        if agent.status == "HIJACKED":
            agent.hijack_record = dict(matched_record)
        state = matched_record.get("state")
        if state in {"requested", "stopping"}:
            agent.hijack_overlay = "hijacking"
        elif state == "resolving":
            agent.hijack_overlay = "recovering"
        elif state == "held":
            agent.hijack_diff_summary = _diff_summary(matched_record)


__all__ = ["apply_hijack_ledger_presentation"]
