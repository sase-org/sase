"""Shared reclaim-test helpers.

Public helpers for the ``test_reclaim*`` modules. Names are public so the
split modules can import them; the module itself is private (``_``-prefixed)
so no ``_``-prefixed name is ever imported across modules.
"""

from __future__ import annotations

from sase.gate_turn.models import GateTurnRecord

__all__ = ["RECLAIM_PROJECT", "make_reclaim_record"]

RECLAIM_PROJECT = "proj"


def make_reclaim_record(
    *,
    gate_id: str,
    member_agent_name: str,
    gate_state: str = "pending",
) -> GateTurnRecord:
    return GateTurnRecord(
        gate_id=gate_id,
        member_agent_name=member_agent_name,
        lane="lane",
        project_name="proj",
        artifacts_dir="/tmp/artifacts",
        timestamp="20260828120000",
        kind="custom",
        gate_state=gate_state,  # type: ignore[arg-type]
        start_status="WAIT",
        stop_status="DONE",
        accent="#00D7AF",
        label="Review",
        reason="wait",
        creator_agent="lane--0",
        bundle_path="/tmp/bundle",
        notification_id="notif-1",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )
