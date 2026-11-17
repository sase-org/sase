"""Gate-handoff continuation replay regression.

A gated starter that published its ``agent_delta`` node must replay as a
versioned block even when its chat transcript nests every earlier fork.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.history.chat_fork.continuation._render import prepare_legacy_payload
from sase.history.chat_fork.continuation._util import MAX_PROTECTED_LEGACY_BYTES
from sase.history.chat_fork.continuation.replay import (
    replay_versioned_continuation_history,
)
from tests.history.test_continuation_replay import (
    _agent_member,
    _write_agent_node,
    _write_json,
)


def _write_chat(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_gated_starter_renders_as_agent_delta_not_legacy_boundary(
    tmp_path: Path,
) -> None:
    starter = tmp_path / "artifacts" / "20260911010101"
    gate_member_dir = tmp_path / "artifacts" / "20260911010102"
    followup = tmp_path / "artifacts" / "20260911010103"
    starter_node_id = "agent-delta-gated-starter"
    followup_node_id = "agent-delta-followup"
    _write_agent_node(
        starter,
        name="chain--0",
        node_id=starter_node_id,
        prompt="Do the gated work.",
        response="STARTER_REPLY",
    )
    # The starter transcript nests the previous fork and carries a large body.
    # Replay must ignore it because the starter has a recoverable node.
    nested = (
        "# Previous Continuation\n\nnested fork history\n\n"
        + "LARGE_BODY_SENTINEL_"
        + ("x" * 20_000)
    )
    chat_path = tmp_path / "20260911010101.md"
    _write_chat(chat_path, nested)
    starter_member = {
        "kind": "agent",
        "name": "chain--0",
        "path": str(chat_path),
        "artifact_dir": str(starter),
        "outcome": "completed",
    }
    gate_member_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        gate_member_dir / "agent_meta.json",
        {
            "name": "chain--gate",
            "gate_id": "gate-1",
            "continuation_parent_node_ids": [starter_node_id],
            "continuation_parent_node_id": starter_node_id,
        },
    )
    gate_chat = tmp_path / "20260911010102.md"
    _write_chat(gate_chat, "small gate transcript\n")
    gate_member = {
        "kind": "agent",
        "name": "chain--gate",
        "path": str(gate_chat),
        "artifact_dir": str(gate_member_dir),
        "outcome": "completed",
    }
    _write_agent_node(
        followup,
        name="chain--1",
        node_id=followup_node_id,
        parents=[starter_node_id],
        prompt="Continue after the gate.",
        response="FOLLOWUP_REPLY",
    )
    followup_member = _agent_member(tmp_path, "20260911010103", "chain--1")
    source = {
        "kind": "session",
        "name": "chain",
        "members": [starter_member, gate_member, followup_member],
        "excluded": [],
    }
    result = replay_versioned_continuation_history([source])
    assert result is not None
    assert result.refusals == ()
    kinds = {
        str(block.get("node_id")): str(block.get("kind"))
        for block in result.manifest.get("stable_blocks", [])
        if isinstance(block, dict)
    }
    assert kinds.get(starter_node_id) == "agent_delta"
    assert kinds.get(followup_node_id) == "agent_delta"
    assert "LARGE_BODY_SENTINEL_" not in result.rendered
    assert "STARTER_REPLY" in result.rendered
    assert "FOLLOWUP_REPLY" in result.rendered


def test_over_budget_refusal_names_member_and_size(tmp_path: Path) -> None:
    label = "agent session `tailnet-x.13` member `tailnet-x.13--5`"
    protected = "P" * (MAX_PROTECTED_LEGACY_BYTES + 10)
    payload = {"label": label, "protected_text": protected}
    prepared, omission = prepare_legacy_payload(payload, evidence_policy=None)
    assert prepared.get("protected_content_omitted") is True
    assert omission is not None
    assert omission["kind"] == "protected_content_over_budget"
    reason = str(omission["reason"])
    assert label in reason
    assert str(len(protected.encode("utf-8"))) in reason
    assert str(MAX_PROTECTED_LEGACY_BYTES) in reason
