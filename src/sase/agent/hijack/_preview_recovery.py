"""Recovery ledger lookup and read-only recovery preview assembly."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.config import (
    AgentHijackConfig,
    agent_hijack_config,
    build_alias_candidates,
)
from sase.agent.hijack.core import (
    assemble_hijack_recovery_preview,
    escalation_wire_schema_version,
    hijack_escalation_target,
    hijack_recovery_preview_wire_schema_version,
)
from sase.history.chat_fork.common import load_json_object

from sase.agent.hijack._preview_models import (
    RecoveryAction,
    RecoveryPreview,
    HijackRecoveryRefusal,
)
from sase.agent.hijack._preview_values import (
    concrete_model_target,
    diff_totals,
    duration,
    integer,
    string,
    string_list,
)


def hijack_recovery_preview(agent_or_name: object) -> RecoveryPreview:
    """Gather current read-only facts and invoke the Rust preview policy."""
    record, artifacts_dir, meta = _load_recovery_context(agent_or_name)
    state = _record_state(record)
    header = _recovery_header(record)
    model_target = concrete_model_target(record)
    rung = _lineage_to_rung(meta)
    config: AgentHijackConfig = agent_hijack_config()
    escalation = hijack_escalation_target(
        {
            "schema_version": escalation_wire_schema_version(),
            "model_facts": {
                "alias": string(record.get("model_alias")),
                "alias_trail": string_list(record.get("model_alias_trail")),
                "origin": string(record.get("model_origin")),
                "provider": string(record.get("provider")),
                "model": string(record.get("model")),
                "effort": string(record.get("effort")),
            },
            "ladder": list(config.escalation_ladder),
            "alias_candidates": build_alias_candidates(config.escalation_ladder),
            "lineage_to_rung": rung,
            "stalled_concrete": model_target,
        }
    )
    wire = assemble_hijack_recovery_preview(
        {
            "schema_version": hijack_recovery_preview_wire_schema_version(),
            "hijack_id": str(record.get("hijack_id") or ""),
            "revision": integer(record.get("revision")),
            "state": state,
            "header": header,
            "escalate": escalation,
            "continue_target": model_target,
        }
    )
    wire = _with_release_rows(wire, record, state)
    return _preview_from_wire(
        wire, record=record, artifacts_dir=artifacts_dir, state=state
    )


_RELEASE_ROW_DETAILS = (
    ("restart", "Restart", "same prompt, same name, fresh workspace"),
    ("edit", "Edit", "edit the prompt; nothing is released until submit"),
    ("dismiss", "Dismiss", "snapshot first, then workspace released"),
)


_RELEASE_FROM_STATES = frozenset({"held", "expired"})


def _with_release_rows(
    wire: Mapping[str, Any],
    record: Mapping[str, Any],
    state: str,
) -> dict[str, Any]:
    """Fill in the restart/edit/dismiss rows the core leaves unavailable.

    The Rust preview owns keep-work availability; release availability depends
    on the Python restart planner (fan-out, container, disabled provider) and
    the ledger state, so this phase patches those rows here. The same patched
    preview powers ``sase agent recover``, the TUI panel, and the release
    transaction's own availability check.
    """
    patched = dict(wire)
    raw_actions = wire.get("actions")
    actions: list[dict[str, Any]] = [
        dict(item)
        for item in (raw_actions if isinstance(raw_actions, list) else [])
        if isinstance(item, Mapping)
    ]
    by_action = {str(item.get("action") or ""): item for item in actions}
    for name, label, detail in _RELEASE_ROW_DETAILS:
        available, reason = _release_row_availability(name, record, state)
        row = by_action.get(name)
        if row is None:
            row = {"action": name}
            actions.append(row)
            by_action[name] = row
        row["available"] = available
        row["reason"] = reason
        row["label"] = label
        row["detail"] = detail if available else ""
        row.setdefault("target", None)
    patched["actions"] = actions
    return patched


def _release_row_availability(
    name: str,
    record: Mapping[str, Any],
    state: str,
) -> tuple[bool, str | None]:
    """Return ``(available, reason)`` for one release row.

    Restart availability runs the restart planner, whose refusals become the
    disabled-row reason; edit and dismiss only need a releasable state.
    """
    if state not in _RELEASE_FROM_STATES:
        if state == "resolving":
            return False, "already being resolved"
        return False, f"release recovery is not available in {state}"
    if name == "restart":
        from sase.agent.hijack.recover_release import restart_availability_reason

        reason = restart_availability_reason(record)
        if reason is not None:
            return False, reason
    return True, None


def _load_recovery_context(
    agent_or_name: object,
) -> tuple[dict[str, Any], str, Mapping[str, object]]:
    from sase.agent.names import find_named_agent

    direct_record: dict[str, Any] | None = None
    agent_name: str | None = None
    artifacts_dir: str | None = None
    if isinstance(agent_or_name, Mapping):
        candidate = dict(agent_or_name)
        if candidate.get("hijack_id"):
            direct_record = candidate
        agent_name = string(candidate.get("agent_name") or candidate.get("name"))
        artifacts_dir = string(candidate.get("artifacts_dir"))
    elif isinstance(agent_or_name, str):
        direct_record = ledger.load_record(agent_or_name)
        agent_name = agent_or_name
    else:
        agent_name = string(getattr(agent_or_name, "name", None))
        artifacts_dir = string(getattr(agent_or_name, "artifacts_dir", None))

    if artifacts_dir is None and agent_name:
        try:
            found = find_named_agent(agent_name)
        except Exception:
            found = None
        artifacts_dir = string(getattr(found, "artifacts_dir", None))
    if artifacts_dir and direct_record is None:
        direct_record = ledger.load_record_by_artifacts_dir(artifacts_dir)
    if direct_record is None and agent_name:
        direct_record = ledger.load_record_by_agent_name(agent_name)

    meta: Mapping[str, object] = {}
    if artifacts_dir:
        meta = load_json_object(Path(artifacts_dir) / "agent_meta.json")
        done = load_json_object(Path(artifacts_dir) / "done.json")
        recovery = done.get("recovery")
        hijack_id = recovery.get("hijack_id") if isinstance(recovery, Mapping) else None
        if direct_record is None and isinstance(hijack_id, str) and hijack_id:
            direct_record = ledger.load_record(hijack_id)
    if direct_record is None:
        subject = agent_name or str(agent_or_name)
        raise HijackRecoveryRefusal(
            "record_not_found", f"No hijack recovery record was found for {subject}"
        )
    record = dict(direct_record)
    artifacts_dir = string(record.get("artifacts_dir")) or artifacts_dir
    if not artifacts_dir:
        raise HijackRecoveryRefusal(
            "missing_artifacts",
            "The hijack record has no predecessor artifact directory",
        )
    if not meta:
        meta = load_json_object(Path(artifacts_dir) / "agent_meta.json")
    return record, artifacts_dir, meta


def _preview_from_wire(
    wire: Mapping[str, Any],
    *,
    record: Mapping[str, Any],
    artifacts_dir: str,
    state: str,
) -> RecoveryPreview:
    raw_actions = wire.get("actions")
    actions: list[RecoveryAction] = []
    if isinstance(raw_actions, Sequence) and not isinstance(raw_actions, (str, bytes)):
        for value in raw_actions:
            if not isinstance(value, Mapping):
                continue
            actions.append(
                RecoveryAction(
                    action=string(value.get("action")) or "",
                    available=bool(value.get("available")),
                    reason=string(value.get("reason")),
                    label=string(value.get("label")) or "",
                    detail=string(value.get("detail")) or "",
                    target=string(value.get("target")),
                )
            )
    header = wire.get("header")
    return RecoveryPreview(
        hijack_id=string(wire.get("hijack_id")) or str(record.get("hijack_id") or ""),
        revision=integer(wire.get("revision")),
        header=dict(header) if isinstance(header, Mapping) else {},
        default_action=string(wire.get("default_action")),
        actions=tuple(actions),
        state=state,
        _record=dict(record),
        _artifacts_dir=artifacts_dir,
    )


def _record_state(record: Mapping[str, Any]) -> str:
    state = string(record.get("state")) or "unknown"
    return state


def _recovery_header(record: Mapping[str, Any]) -> dict[str, Any]:
    files, insertions, deletions = diff_totals(record)
    return {
        "agent_name": string(record.get("agent_name")) or "unknown",
        "workspace_num": _integer_or_none(record.get("workspace_num")),
        "model_display": _model_display(record),
        "run_duration_display": duration(record.get("run_duration_seconds")),
        "hijacked_ago": _age_since(record.get("hijacked_at")),
        "files_changed": files,
        "insertions": insertions,
        "deletions": deletions,
        "last_tool": string(record.get("last_tool")) or "",
        "last_tool_age": duration(record.get("last_tool_age_seconds")),
    }


def _model_display(record: Mapping[str, Any]) -> str:
    from sase.history.chat_storage import format_metadata_model

    provider = string(record.get("provider"))
    model = string(record.get("model"))
    display = format_metadata_model(provider, model) or "unknown model"
    effort = string(record.get("effort"))
    if effort and not display.endswith(f"@{effort}"):
        display += f"@{effort}"
    return display


def _lineage_to_rung(meta: Mapping[str, object]) -> str | None:
    lineage = meta.get("hijack_lineage")
    if not isinstance(lineage, Mapping):
        lineage = meta.get("recovery_lineage")
    return string(lineage.get("to_rung")) if isinstance(lineage, Mapping) else None


def _age_since(value: object) -> str:
    from sase.core.time import local_now, parse_local

    raw = string(value)
    if not raw:
        return ""
    try:
        parsed = parse_local(raw)
        if parsed is None:
            return ""
        seconds = max(0.0, (local_now() - parsed).total_seconds())
    except (TypeError, ValueError):
        return ""
    return duration(seconds)


def _integer_or_none(value: object) -> int | None:
    return value if type(value) is int else None
