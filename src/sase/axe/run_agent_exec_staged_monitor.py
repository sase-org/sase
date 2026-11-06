"""Connect runner failure handling to staged-monitor resource cleanup."""

from __future__ import annotations


def cleanup_staged_monitor_handoff(artifacts_dir: str, *, held: bool) -> None:
    """Unwind an unstarted monitor, retaining held handoffs for recovery.

    Missing, malformed, or already-adopted stages are not cleanup proof.
    The monitor transaction owns reservation release and skips running members.
    """
    try:
        from sase.agent.staged_handoff import read_staged_handoff

        staged = read_staged_handoff(artifacts_dir)
    except Exception:  # noqa: BLE001 - cleanup must not mask the original failure.
        return
    if not isinstance(staged, dict) or staged.get("kind") != "monitor":
        return
    staged_id = staged.get("staged_id")
    payload = staged.get("payload")
    if not isinstance(staged_id, str) or not staged_id:
        return
    if not isinstance(payload, dict):
        return
    monitor_id = payload.get("monitor_id")
    if not isinstance(monitor_id, str) or not monitor_id:
        return
    try:
        from sase.monitor.staged_owner import staged_monitor_member_artifacts_dir

        member_dir = staged_monitor_member_artifacts_dir(monitor_id, staged_id, payload)
    except Exception:  # noqa: BLE001 - missing owner evidence means nothing to clean.
        return
    if not member_dir:
        return
    try:
        from sase.monitor.start_stage import cleanup_staged_monitor

        cleanup_staged_monitor(member_dir, held=held)
    except Exception:  # noqa: BLE001 - preserve original failure and held evidence.
        return
