"""Launched hijack recovery transactions: continue, escalate, and instruct."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests._agent_hijack_recovery_transaction_support import Transaction, parent_done


def _ack_for(txn: Transaction, child: Path) -> dict[str, Any]:
    from sase.agent.hijack.recovery_successor import read_recovery_ack

    ack = read_recovery_ack(str(child))
    assert ack is not None
    return dict(ack)


def _assert_inherited_work(txn: Transaction, child: Path, ack: dict[str, Any]) -> None:
    """Prove the fake provider received and inherited both repository changes."""
    assert ack["workspace_num"] == 3
    assert ack["workspace_dir"] == str(txn.workspace_dir)
    assert ack["goal"] == "goal-1"
    assert ack["bead"] == "sase-1"
    assert ack["scope_verified"] is True
    assert ack["baselines_verified"] is True
    assert ack["inventory_verified"] is True
    assert ack["lineage"]["hijack_id"] == "h-123"
    assert ack["lineage"]["predecessor"] == "acme--3"
    provider = txn.provider_calls[-1]
    assert provider["workspace_num"] == 3
    assert provider["workspace_dir"] == str(txn.workspace_dir)
    assert provider["primary_work"] == (
        "# primary fixture change\n\nPredecessor primary work.\n"
    )
    assert provider["linked_work"] == (
        "# linked fixture change\n\nPredecessor linked work.\n"
    )
    for filename in (
        "commit_finalizer_baseline.json",
        "opened_linked_workspaces.json",
    ):
        assert (child / filename).read_bytes() == (txn.parent / filename).read_bytes()


def test_continue_full_transaction_launches_with_real_policy_and_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = Transaction(monkeypatch, tmp_path)
    result = txn.recover(action="continue")

    assert result.kind == "launched"
    assert result.concrete_target == "claude/opus@high"
    assert result.successor == "acme--4"
    assert result.launch_identity
    assert result.admission_request_id
    assert txn.record()["state"] == "resolved"
    # One durable request, one child, same workspace pair and exact target.
    assert len(txn.bundles()) == 1
    assert len(txn.children()) == 1
    child = txn.children()[0]
    ack = _ack_for(txn, child)
    _assert_inherited_work(txn, child, ack)
    assert ack["launch_identity"] == result.launch_identity
    assert ack["successor_name"] == "acme--4"
    assert ack["concrete_target"] == "claude/opus@high"
    assert ack["provider"] == "claude"
    assert ack["model"] == "opus"
    assert ack["effort"] == "high"
    assert ack["workspace_num"] == 3
    assert ack["workspace_dir"] == str(txn.workspace_dir)
    assert ack["goal"] == "goal-1"
    assert ack["bead"] == "sase-1"
    assert ack["goal_verified"] is True
    assert ack["bead_verified"] is True
    assert ack["scope_verified"] is True
    assert ack["baselines_verified"] is True
    assert ack["inventory_verified"] is True
    # The provider boundary observes the original inheritance, not a copy.
    assert txn.provider_calls == [
        {
            "prompt": txn.spawned_prompts[0],
            "goal": "goal-1",
            "bead": "sase-1",
            "model": "claude/opus@high",
            "workspace_num": 3,
            "workspace_dir": str(txn.workspace_dir),
            "primary_work": "# primary fixture change\n\nPredecessor primary work.\n",
            "linked_work": "# linked fixture change\n\nPredecessor linked work.\n",
        }
    ]
    assert txn.spawned_prompts[0].startswith("%model:claude/opus@high")
    # The prepared prompt stays inert: the fork example is literal text.
    assert "#fork:other-agent\n%id(other-agent)" in txn.spawned_prompts[0]
    # Predecessor outcome is preserved; only recovery fields are resolved.
    done = parent_done(txn)
    assert done["outcome"] == "hijacked"
    assert done["recovery"]["state"] == "resolved"
    assert done["recovery"]["action"] == "continue"
    assert done["recovery"]["successor"] == "acme--4"
    # The held claim moved to the successor on the same workspace pair.
    from sase.running_field import get_claimed_workspaces

    claims = get_claimed_workspaces(str(txn.project_file))
    owned = [claim for claim in claims if claim.workspace_num == 3]
    assert len(owned) == 1
    assert owned[0].pid == txn.pid


def test_escalate_full_transaction_pins_changed_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txn = Transaction(monkeypatch, tmp_path)
    result = txn.recover(action="escalate")

    assert result.kind == "launched"
    assert result.concrete_target == "claude/opus@xhigh"
    assert result.model_changed is True
    child = txn.children()[0]
    ack = _ack_for(txn, child)
    _assert_inherited_work(txn, child, ack)
    assert ack["lineage"]["to_rung"] == "claude/opus@xhigh"
    assert ack["concrete_target"] == "claude/opus@xhigh"
    assert ack["effort"] == "xhigh"
    assert txn.provider_calls[0]["model"] == "claude/opus@xhigh"
    assert txn.provider_calls[0]["goal"] == "goal-1"
    done = parent_done(txn)
    assert done["outcome"] == "hijacked"
    assert done["recovery"]["action"] == "escalate"


def test_instruct_edited_prompt_with_explicit_model_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.hijack import preview as preview_module

    txn = Transaction(monkeypatch, tmp_path)
    edited = preview_module.build_hijack_continuation_prompt(
        txn.record(), model_target="claude/opus@high"
    ).prompt
    edited += "\n\nKeep the existing changes and use the edited model.\n"

    result = txn.recover(action="continue", prompt=edited, model="sonnet@low")

    assert result.kind == "launched"
    assert result.action == "instruct"
    assert result.concrete_target == "claude/sonnet@low"
    assert result.model_changed is True
    assert txn.spawned_prompts[0].startswith("%model:claude/sonnet@low")
    child = txn.children()[0]
    ack = _ack_for(txn, child)
    _assert_inherited_work(txn, child, ack)
    assert ack["model"] == "sonnet"
    assert ack["effort"] == "low"
    assert ack["goal"] == "goal-1"
    assert result.detail["context_mode"] == "fork"
