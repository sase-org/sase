"""Persist-cleanup executes monitor stops before other side effects."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from sase.core.agent_cleanup_wire import (
    AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
    AgentCleanupIdentityWire,
    AgentCleanupKillItemWire,
    AgentCleanupMonitorStopIntentWire,
    AgentCleanupPlanWire,
    AgentCleanupSideEffectsWire,
)
from sase.monitor.cleanup import execute_monitor_stop_intents
from sase.ops.commands.agent import _apply_cleanup_payload_for_result


def _plan(*, monitor_state: str = "running") -> AgentCleanupPlanWire:
    identity = AgentCleanupIdentityWire("run", "owner--mon", "mon-ts")
    return AgentCleanupPlanWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        kill_items=(
            AgentCleanupKillItemWire(
                identity=identity,
                kind="monitor",
                monitor_id="monid123456",
            ),
        ),
        side_effects=AgentCleanupSideEffectsWire(
            monitor_stop_requests=(
                AgentCleanupMonitorStopIntentWire(
                    identity=identity,
                    monitor_id="monid123456",
                ),
            ),
            dismissed_index_additions=(identity,),
        ),
    )


def test_execute_monitor_stop_intents_is_idempotent_for_terminal_monitors() -> None:
    identity = AgentCleanupIdentityWire("run", "owner--mon", "mon-ts")
    plan = AgentCleanupPlanWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        side_effects=AgentCleanupSideEffectsWire(
            monitor_stop_requests=(
                AgentCleanupMonitorStopIntentWire(
                    identity=identity,
                    monitor_id="already-stopped",
                ),
            ),
        ),
    )
    terminal = type(
        "Record",
        (),
        {
            "monitor_id": "already-stopped",
            "monitor_state": "stopped",
            "project_name": "proj",
            "artifacts_dir": "/tmp/mon",
        },
    )()

    with (
        patch("sase.monitor.store.list_monitors", return_value=[terminal]),
        patch("sase.monitor.store.stop_monitor") as stop,
    ):
        execute_monitor_stop_intents(plan)

    stop.assert_not_called()


def test_execute_monitor_stop_intents_fails_closed_when_monitor_stays_running() -> None:
    running = type(
        "Record",
        (),
        {
            "monitor_id": "monid123456",
            "monitor_state": "running",
            "project_name": "proj",
            "artifacts_dir": "/tmp/mon",
        },
    )()

    with (
        patch("sase.monitor.store.list_monitors", return_value=[running]),
        patch("sase.monitor.store.stop_monitor", return_value=running),
        patch("sase.monitor.store.read_monitor_marker", return_value=running),
        patch(
            "sase.ace.tui.actions.agents._kill_transactions.persist_bulk_kill_transaction"
        ) as persist,
    ):
        success, message, payload = _apply_cleanup_payload_for_result(
            {
                "action": "kill",
                "transaction": "bulk_kill",
                "cleanup_plan": {
                    "schema_version": AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
                    "kill_items": [
                        {
                            "identity": {
                                "agent_type": "run",
                                "cl_name": "owner--mon",
                                "raw_suffix": "mon-ts",
                            },
                            "kind": "monitor",
                            "monitor_id": "monid123456",
                        }
                    ],
                    "side_effects": {
                        "monitor_stop_requests": [
                            {
                                "identity": {
                                    "agent_type": "run",
                                    "cl_name": "owner--mon",
                                    "raw_suffix": "mon-ts",
                                },
                                "monitor_id": "monid123456",
                            }
                        ],
                        "dismissed_index_additions": [],
                    },
                },
                "kill_items": [],
                "dismissable": [],
                "dismissed_identities": [],
            }
        )

    persist.assert_not_called()
    assert success is False
    assert "remained running" in message
    assert payload["severity"] == "error"


def test_persist_cleanup_stops_monitors_before_dismissal() -> None:
    order: list[str] = []
    running = type(
        "Record",
        (),
        {
            "monitor_id": "monid123456",
            "monitor_state": "running",
            "project_name": "proj",
            "artifacts_dir": "/tmp/mon",
        },
    )()
    stopped = type(
        "Record",
        (),
        {
            "monitor_id": "monid123456",
            "monitor_state": "stopped",
            "project_name": "proj",
            "artifacts_dir": "/tmp/mon",
        },
    )()

    def _stop(record: Any) -> Any:
        order.append("stop")
        assert record.monitor_id == "monid123456"
        return stopped

    def _persist(*_args: object, **_kwargs: object) -> None:
        order.append("persist")

    with (
        patch("sase.monitor.store.list_monitors", return_value=[running]),
        patch("sase.monitor.store.stop_monitor", side_effect=_stop),
        patch("sase.monitor.store.read_monitor_marker", return_value=stopped),
        patch(
            "sase.ace.tui.actions.agents._kill_transactions.persist_bulk_kill_transaction",
            side_effect=_persist,
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_agents", return_value=False),
    ):
        success, _message, _payload = _apply_cleanup_payload_for_result(
            {
                "action": "kill",
                "transaction": "bulk_kill",
                "cleanup_plan": {
                    "schema_version": AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
                    "kill_items": [
                        {
                            "identity": {
                                "agent_type": "run",
                                "cl_name": "owner--mon",
                                "raw_suffix": "mon-ts",
                            },
                            "kind": "monitor",
                            "monitor_id": "monid123456",
                        }
                    ],
                    "side_effects": {
                        "monitor_stop_requests": [
                            {
                                "identity": {
                                    "agent_type": "run",
                                    "cl_name": "owner--mon",
                                    "raw_suffix": "mon-ts",
                                },
                                "monitor_id": "monid123456",
                            }
                        ]
                    },
                },
                "kill_items": [],
                "dismissable": [],
                "dismissed_identities": [],
            }
        )

    assert success is True
    assert order == ["stop", "persist"]


def test_missing_monitor_stop_intent_is_success() -> None:
    from sase.monitor.models import MonitorRefError

    plan = _plan()
    with (
        patch("sase.monitor.store.list_monitors", return_value=[]),
        patch(
            "sase.monitor.store.resolve_monitor_ref",
            side_effect=MonitorRefError("gone"),
        ),
        patch("sase.monitor.store.stop_monitor") as stop,
    ):
        execute_monitor_stop_intents(plan)
    stop.assert_not_called()
