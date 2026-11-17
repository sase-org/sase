"""Repair monitor hijack settlement after a partial terminal checkpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.agent.hijack._stop_orchestrator_common import EXIT_FAILED, HijackStopResult
from sase.agent.hijack._stop_orchestrator_targets import coalesced_result


def repair_monitor_settlement(
    name: str,
    active: dict[str, Any],
    *,
    subject: Any,
    target: Any,
    decision: dict[str, Any],
) -> HijackStopResult | None:
    """Replay a terminal monitor checkpoint after a prior partial settle."""
    from sase.agent.hijack._stop_models import read_json_dict
    from sase.monitor.hijack_settlement import settle_monitor_hijack
    from sase.monitor.store import read_monitor_marker

    current = read_monitor_marker(target.project_name, target.artifacts_dir)
    if current is None or current.monitor_state == "running":
        return None
    meta = read_json_dict(Path(target.artifacts_dir) / "agent_meta.json") or {}
    disposition = settle_monitor_hijack(
        target.artifacts_dir,
        meta,
        monitor_state=current.monitor_state,
        project_name=target.project_name,
    )
    record = None
    try:
        from sase.agent.hijack import ledger

        record = ledger.load_record(str(active.get("hijack_id") or ""))
    except Exception:
        pass
    if (
        disposition.settled
        and isinstance(record, dict)
        and record.get("state") == "held"
    ):
        return coalesced_result(name, record, subject=subject, decision=decision)
    if disposition.handled:
        return HijackStopResult(
            status="settlement_pending",
            message=(
                f"Monitor {target.name} is terminal, but hijack settlement remains "
                f"repairable: {disposition.error or 'pending'}"
            ),
            exit_code=EXIT_FAILED,
            hijack_id=str(active.get("hijack_id") or "") or None,
            record=record or active,
            reason="settlement_pending",
            decision=decision,
            occupant_name=getattr(subject, "occupant_name", None),
            occupant_reason=getattr(subject, "occupant_reason", None),
            workspace_num=getattr(target, "workspace_num", None),
        )
    return None
