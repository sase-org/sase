from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.dispatch_launch_rows import (
    dispatch_operation_id,
    dispatch_provisional_agent_from_payload,
    dispatch_provisional_agent_from_preview,
    dispatch_row_reconciled,
    mark_dispatch_row_unknown,
)


@dataclass(frozen=True)
class _Preview:
    target: str
    prompt: str
    source: str
    target_installation_id: str
    target_status: str
    target_detail: str
    portable_context: dict[str, Any]
    intent: dict[str, Any]
    operation_key: dict[str, Any]
    payload_fingerprint: dict[str, Any]
    request: dict[str, Any]
    provisional_locator: dict[str, Any]


def test_dispatch_preview_row_tracks_operation_and_source_payload() -> None:
    preview = _preview()
    payload = {"project": "sase", "patch_ref": "patch-123"}

    row = dispatch_provisional_agent_from_preview(
        preview,
        prompt="%dispatch:apollo do remote work",
        payload=payload,
    )

    assert dispatch_operation_id(row) == "op-1"
    assert row.fleet_origin_alias == "apollo"
    assert row.status == "QUEUED"
    assert row.fleet_dispatch_prompt == "%dispatch:apollo do remote work"
    assert row.fleet_dispatch_payload == payload
    assert row.fleet_bounded_intent == "accepted locally; waiting for owner"


def test_dispatch_payload_row_reconciles_with_matching_fleet_row() -> None:
    preview = _preview()
    row = dispatch_provisional_agent_from_payload(
        {
            "target": "apollo",
            "target_installation_id": preview.target_installation_id,
            "operation_key": preview.operation_key,
            "source_status": "settled",
            "portable_context": preview.portable_context,
            "receipt": {
                "state": "settled",
                "logical_locator": preview.provisional_locator,
            },
        },
        prompt="%dispatch:apollo do remote work",
        payload={"project": "sase"},
    )
    assert row is not None
    real = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase",
        project_file="/fleet/sase/project.yml",
        status="RUNNING",
        start_time=None,
        raw_suffix="fleet:apollo:real",
        fleet_origin_alias="apollo",
        fleet_logical_locator=preview.provisional_locator,
    )

    assert row.status == "STARTING"
    assert dispatch_row_reconciled(row, [real]) is True


def test_dispatch_unknown_row_prompts_outcome_check() -> None:
    row = dispatch_provisional_agent_from_preview(
        _preview(),
        prompt="%dispatch:apollo do remote work",
        payload={"project": "sase"},
    )

    mark_dispatch_row_unknown(row, "remote dispatch outcome is uncertain")

    assert row.status == "WAITING"
    assert row.fleet_dispatch_status == "outcome_unknown"
    assert row.fleet_bounded_intent == "submission outcome unknown; check outcome"


def _preview() -> _Preview:
    target_installation_id = "sase_inst_v1_" + "a" * 64
    locator = {
        "schema_version": 1,
        "project": {
            "schema_version": 1,
            "origin": {
                "schema_version": 1,
                "installation_id": target_installation_id,
            },
            "project_id": "sase",
        },
        "agent_id": "op-1",
        "family_id": None,
    }
    return _Preview(
        target="apollo",
        prompt="do remote work",
        source="%dispatch:apollo",
        target_installation_id=target_installation_id,
        target_status="ok",
        target_detail="",
        portable_context={
            "schema_version": 1,
            "provider_ref": "builtin:https",
            "project_id": "sase",
            "revision": None,
            "patch_ref": "patch-123",
        },
        intent={"prompt": "do remote work", "name": "op-1"},
        operation_key={"schema_version": 1, "operation_id": "op-1"},
        payload_fingerprint={"schema_version": 1, "sha256": "a" * 64},
        request={},
        provisional_locator=locator,
    )
