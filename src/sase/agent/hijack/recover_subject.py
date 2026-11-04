"""Recovery subject loading: record plus host-side facts for the CAS."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.recover_common import (
    RecoverySubject,
    RecoveryTarget,
    clean_string,
    predecessor_concrete_target,
)
from sase.agent.hijack.recovery_successor import RecoveryLineage


def load_recovery_subject(agent_or_name: object) -> RecoverySubject | None:
    """Load the hijack record plus the host-side facts the CAS needs.

    Accepts a hijack id, an agent name, an artifacts directory holder, or a
    record mapping. Returns ``None`` when no record exists.
    """
    record = _load_record(agent_or_name)
    if record is None:
        return None
    predecessor_meta = _load_predecessor_meta(record)
    project_name = _subject_project_name(agent_or_name, record, predecessor_meta)
    done_outcome, done_recovery = read_predecessor_done_marker(record)
    return RecoverySubject(
        record=record,
        project_name=project_name,
        predecessor_meta=predecessor_meta,
        done_outcome=done_outcome,
        done_recovery=done_recovery,
    )


def _load_record(agent_or_name: object) -> dict[str, Any] | None:
    if isinstance(agent_or_name, Mapping):
        candidate = dict(agent_or_name)
        if clean_string(candidate.get("hijack_id")):
            return candidate
        name = clean_string(candidate.get("agent_name") or candidate.get("name"))
        artifacts = clean_string(candidate.get("artifacts_dir"))
        if artifacts:
            found = ledger.load_record_by_artifacts_dir(artifacts)
            if found is not None:
                return dict(found)
        if name:
            return _load_record(name)
        return None
    if isinstance(agent_or_name, str):
        text = agent_or_name.strip()
        if not text:
            return None
        found = ledger.load_record(text)
        if found is not None:
            return dict(found)
        by_name = ledger.load_record_by_agent_name(text)
        if by_name is not None:
            return dict(by_name)
        try:
            from sase.agent.names import find_named_agent
        except Exception:
            return None
        try:
            named = find_named_agent(text)
        except Exception:
            named = None
        artifacts_dir = clean_string(getattr(named, "artifacts_dir", None))
        if artifacts_dir:
            by_dir = ledger.load_record_by_artifacts_dir(artifacts_dir)
            if by_dir is not None:
                return dict(by_dir)
        return None
    artifacts_dir = clean_string(getattr(agent_or_name, "artifacts_dir", None))
    if artifacts_dir:
        found = ledger.load_record_by_artifacts_dir(artifacts_dir)
        if found is not None:
            return dict(found)
    name = clean_string(getattr(agent_or_name, "name", None))
    if name:
        return _load_record(name)
    return None


def _load_predecessor_meta(record: Mapping[str, Any]) -> dict[str, Any]:
    from sase.history.chat_fork.common import load_json_object

    artifacts_dir = clean_string(record.get("artifacts_dir"))
    if not artifacts_dir:
        return {}
    meta = load_json_object(Path(artifacts_dir) / "agent_meta.json")
    return dict(meta) if isinstance(meta, Mapping) else {}


def _subject_project_name(
    agent_or_name: object,
    record: Mapping[str, Any],
    predecessor_meta: Mapping[str, Any],
) -> str | None:
    _ = predecessor_meta
    try:
        from sase.agent.names import find_named_agent
        from sase.agent.running import named_agent_project_fields
    except Exception:
        return None
    name = clean_string(record.get("agent_name"))
    candidates: list[object] = [agent_or_name]
    if name:
        candidates.append(name)
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        try:
            found = find_named_agent(candidate.strip())
        except Exception:
            continue
        if found is None:
            continue
        try:
            _, project_name, _, _, _ = named_agent_project_fields(found)
        except Exception:
            continue
        if isinstance(project_name, str) and project_name.strip():
            return project_name.strip()
    return None


def read_predecessor_done_marker(
    record: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    from sase.history.chat_fork.common import load_json_object

    artifacts_dir = clean_string(record.get("artifacts_dir"))
    if not artifacts_dir:
        return None, None
    payload = load_json_object(Path(artifacts_dir) / "done.json")
    if not isinstance(payload, Mapping):
        return None, None
    outcome = payload.get("outcome")
    recovery = payload.get("recovery")
    return (
        outcome if isinstance(outcome, str) else None,
        dict(recovery) if isinstance(recovery, Mapping) else None,
    )


def session_base_for(
    record: Mapping[str, Any],
    predecessor_meta: Mapping[str, Any],
) -> str | None:
    """Return the agent-session parent the reserved successor attaches to.

    The record's session wins when present; otherwise the predecessor's
    ``agent_session`` metadata; otherwise the agent name minus its trailing
    ``--member`` suffix. ``None`` when nothing resolves.
    """
    session = clean_string(record.get("session"))
    if session:
        return session
    try:
        from sase.plan_chain import agent_session_value
    except Exception:
        agent_session_value = None  # type: ignore[assignment]
    if agent_session_value is not None:
        try:
            meta_session = agent_session_value(predecessor_meta)
        except Exception:
            meta_session = None
        if isinstance(meta_session, str) and meta_session.strip():
            return meta_session.strip()
    name = clean_string(record.get("agent_name"))
    if name and "--" in name:
        base = name.rsplit("--", 1)[0].strip()
        if base:
            return base
    return None


def lineage_for(
    *,
    hijack_id: str,
    record: Mapping[str, Any],
    target: RecoveryTarget,
) -> RecoveryLineage:
    """Build the recovery lineage transported in the successor meta.

    Rungs are concrete model labels (stalled → effective), so a chained
    recovery always names the exact models involved. The escalation policy
    ignores non-ladder labels when walking rungs, falling back to alias
    evidence, so concrete labels never misroute a later Escalate.
    """
    stalled = predecessor_concrete_target(record) or ""
    predecessor = clean_string(record.get("agent_name")) or "unknown"
    return RecoveryLineage(
        hijack_id=hijack_id,
        from_rung=stalled.strip() or "unknown",
        to_rung=target.concrete_target,
        predecessor=predecessor,
    )
