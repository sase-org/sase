"""Agent cleanup persistence operation helpers."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from sase.ops.cli import load_request
from sase.ops.names import AGENT_CLEANUP


# The dead in-process kill/dismiss/save workers each hard-coded their own
# ``schedule_agents_refresh_source`` on failure so the optimistic UI update
# got a corrective reload -- and, for single-agent dismiss only, an extra
# off-thread notification-count refresh. The durable path applies the same
# payload out of process, so this table is what lets a persistence failure
# still trigger the same recovery effects instead of leaving stale
# optimistic state on screen. Keyed by ``transaction`` (not ``action``)
# because single-dismiss and bulk-dismiss shared an action but disagreed
# about the notification refresh.
_CLEANUP_ERROR_RECOVERY: Mapping[str, tuple[str, bool]] = {
    "single_kill": ("kill_error_recovery", False),
    "bulk_kill": ("kill_error_recovery", False),
    "single_dismiss": ("dismiss_error_recovery", True),
    "bulk_dismiss": ("dismiss_error_recovery", False),
    "save": ("mark_error_recovery", False),
}


def apply_cleanup_payload_for_result(
    payload: Mapping[str, Any],
) -> tuple[bool, str, Mapping[str, Any]]:
    """Apply one cleanup payload and report the durable-proc result shape.

    Shared by ``sase agent persist-cleanup`` and the in-process test harnesses
    so both exercise the exact same persistence call and failure-recovery
    surface, rather than tests re-deriving it against a code path production
    does not run.
    """
    action = str(payload.get("action") or "cleanup")
    transaction = str(payload.get("transaction") or action)
    try:
        _apply_cleanup_payload(payload)
    except Exception as exc:
        refresh_source, refresh_notifications = _CLEANUP_ERROR_RECOVERY.get(
            transaction, (f"{action}_error_recovery", False)
        )
        return (
            False,
            f"{action.capitalize()} cleanup failed: {exc}",
            {
                "action": action,
                "notify": True,
                "refresh_notifications": refresh_notifications,
                "schedule_agents_refresh_source": refresh_source,
                "severity": "error",
            },
        )
    return (
        True,
        str(payload.get("message") or f"Persisted {action}"),
        {
            "action": action,
            "notify": bool(payload.get("notify", False)),
            "refresh_notifications": bool(payload.get("refresh_notifications", False)),
            "schedule_agents_refresh_source": payload.get(
                "schedule_agents_refresh_source"
            ),
            "severity": payload.get("severity"),
        },
    )


def run_persist_cleanup(
    args: argparse.Namespace,
) -> tuple[bool, str, Mapping[str, Any]]:
    request = load_request(AGENT_CLEANUP, args, required=True)
    return apply_cleanup_payload_for_result(dict(request.payload))


def _apply_cleanup_payload(payload: Mapping[str, Any]) -> None:
    from sase.ace.tui.actions.cleanup_payload import (
        agent_from_json,
        agents_from_json,
        identities_from_json,
    )

    transaction = str(payload.get("transaction") or "")
    dismissed_snapshot = identities_from_json(payload.get("dismissed_identities"))
    added = identities_from_json(payload.get("added_identities"))
    agents_with_children = agents_from_json(payload.get("agents_with_children"))
    cleanup_plan = _cleanup_plan_from_payload(payload.get("cleanup_plan"))
    if cleanup_plan is not None:
        from sase.monitor.cleanup import execute_monitor_stop_intents

        execute_monitor_stop_intents(cleanup_plan)
    recent_group = _recent_group_from_payload(payload.get("recent_group"))
    if transaction == "single_kill":
        from sase.ace.tui.actions.agents._kill_transactions import (
            persist_single_kill_transaction,
        )

        agent_payload = payload.get("agent")
        if isinstance(agent_payload, dict):
            persist_single_kill_transaction(
                agent_from_json(agent_payload),
                str(payload.get("kind") or "running"),  # type: ignore[arg-type]
                agents_with_children,
                dismissed_snapshot,
                cleanup_plan,
                agents_from_json(payload.get("related_agents")),
            )
        return
    if transaction == "bulk_kill":
        from sase.ace.tui.actions.agents._kill_persistence import BulkKillItem
        from sase.ace.tui.actions.agents._kill_transactions import (
            persist_bulk_kill_transaction,
        )

        kill_items = []
        for item in payload.get("kill_items") or []:
            if not isinstance(item, dict) or not isinstance(item.get("agent"), dict):
                continue
            kill_items.append(
                BulkKillItem(
                    agent=agent_from_json(item["agent"]),
                    kind=str(item.get("kind") or "running"),  # type: ignore[arg-type]
                    identities=identities_from_json(item.get("identities")),
                )
            )
        persist_bulk_kill_transaction(
            kill_items,
            agents_from_json(payload.get("dismissable")),
            dismissed_snapshot,
            agents_with_children,
            cleanup_plan,
            recent_group,
        )
        return
    if transaction == "single_dismiss":
        from sase.ace.tui.actions.agents._dismissing import (
            persist_single_dismiss_transaction,
        )

        agent_payload = payload.get("agent")
        if isinstance(agent_payload, dict):
            persist_single_dismiss_transaction(
                agent_from_json(agent_payload),
                dismissed_snapshot,
                agents_with_children,
                cleanup_plan,
                added,
                recent_group,
            )
        return
    if transaction == "bulk_dismiss":
        from sase.ace.tui.actions.agents._dismissing import (
            persist_bulk_dismiss_transaction,
        )

        persist_bulk_dismiss_transaction(
            agents_from_json(payload.get("agents")),
            dismissed_snapshot,
            agents_with_children,
            cleanup_plan,
            added,
            recent_group,
        )
        return
    if transaction == "save":
        from sase.ace.tui.actions.agents._marking import (
            persist_marked_agent_group_save,
        )

        group = _recent_group_from_payload(payload.get("group"))
        if group is not None:
            persist_marked_agent_group_save(
                agents_from_json(payload.get("agents")),
                dismissed_snapshot,
                added,
                group,
                payload.get("group_name")
                if isinstance(payload.get("group_name"), str)
                else None,
            )
        return
    if dismissed_snapshot:
        from sase.ace.dismissed_agents import save_dismissed_agents
        from sase.core.agent_artifact_index_lifecycle import (
            sync_dismissed_agent_artifact_index,
        )

        if save_dismissed_agents(dismissed_snapshot):
            sync_dismissed_agent_artifact_index(dismissed_snapshot)
    if cleanup_plan is not None:
        from sase.ace.tui.actions.agents._dismiss_persistence import (
            persist_cleanup_side_effect_intents,
        )

        persist_cleanup_side_effect_intents(cleanup_plan, agents_with_children)


def _cleanup_plan_from_payload(raw: object) -> Any:
    if not isinstance(raw, dict):
        return None
    from sase.core.agent_cleanup_wire import cleanup_plan_from_dict

    return cleanup_plan_from_dict(raw)


def _recent_group_from_payload(raw: object) -> Any:
    if not isinstance(raw, dict):
        return None
    from sase.core.agent_group_archive_wire import saved_agent_group_from_dict

    return saved_agent_group_from_dict(raw)


__all__ = ["apply_cleanup_payload_for_result", "run_persist_cleanup"]
