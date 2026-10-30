"""Staged gate publication uses persisted creator context and request-id replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.gate_turn import transaction as transaction_module
from sase.gate_turn.publisher import publish_staged_gate
from sase.gate_turn.staged_contract import prepare_staged_gate
from sase.gate_turn.transaction import (
    _spec_from_request,
    creator_context_from_persisted,
    publish_gate_turn,
)
from tests.gate_turn.test_staged_contract import _creator, _request, _write_sources
from tests.gate_turn.test_transaction_gate_intent import (
    _install_transaction_fakes,
    _record,
    _shell_gate_spec,
)


def test_creator_context_from_persisted_ignores_adopter_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "20261029120000"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "original-agent",
                "pid": 4242,
                "workspace_num": 7,
                "cl_name": "orig-cl",
                "agent_session": "original-agent",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "re-adopter")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "adopter"))
    monkeypatch.delenv("SASE_AGENT", raising=False)

    creator = creator_context_from_persisted(
        {
            "project": "proj",
            "project_file": str(tmp_path / "proj.sase"),
            "artifacts_dir": str(artifacts),
            "timestamp": "20261029120000",
            "agent": "original-agent",
            "meta": {},
        }
    )

    assert creator.target_name == "original-agent"
    assert creator.runner_pid == 4242
    assert creator.workspace_num == 7
    assert creator.cl_name == "orig-cl"
    assert creator.artifacts_dir == str(artifacts)


def test_publish_gate_turn_replay_does_not_move_claim_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _install_transaction_fakes(tmp_path, monkeypatch)
    moves: list[str] = []
    members: list[str] = []

    def counting_member(*_args: object, **_kwargs: object) -> str:
        members.append("created")
        return record.artifacts_dir

    def counting_move(*_args: object, **_kwargs: object) -> object:
        from sase.gate_turn.start_claim import GateClaimMove
        from sase.running_field import ClaimResult

        moves.append("moved")
        return GateClaimMove(ClaimResult(True), None, None, "inherit")

    monkeypatch.setattr(transaction_module, "create_gate_turn_member", counting_member)
    monkeypatch.setattr(transaction_module, "move_gate_turn_claim", counting_move)

    spec = _spec_from_request(_shell_gate_spec())
    creator = transaction_module._CreatorContext(
        project_name="proj",
        project_file=str(tmp_path / "proj.sase"),
        artifacts_dir=str(tmp_path / "creator"),
        timestamp="20260916115959",
        target_name="agent",
        durable_lane="agent",
        meta={"name": "agent"},
        workspace_num=None,
        runner_pid=None,
        cl_name=None,
    )

    first = publish_gate_turn(spec, creator=creator)
    monkeypatch.setattr(
        transaction_module, "find_gate_turn_by_gate_id", lambda *_: record
    )
    second = publish_gate_turn(spec, creator=creator)

    assert first.claim_move is not None
    assert second.claim_move is None
    assert members == ["created"]
    assert moves == ["moved"]
    assert first.record.gate_id == second.record.gate_id == "intent-one"


def test_publish_staged_gate_passes_frozen_auto_and_skips_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sources(tmp_path, monkeypatch)
    artifacts = tmp_path / "20261029120000"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "original-agent",
                "pid": 9,
                "workspace_num": 1,
                "agent_session": "original-agent",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setenv("SASE_AGENT_NAME", "re-adopter")
    monkeypatch.delenv("SASE_AGENT", raising=False)
    preparation = prepare_staged_gate(
        _request(),
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )
    assert preparation.payload is not None
    captured: dict[str, Any] = {}

    def fake_publish(spec, *, creator, frozen_auto=None, resource_bytes=None, **_k):
        captured["creator"] = creator
        captured["frozen_auto"] = frozen_auto
        captured["resource_bytes"] = resource_bytes
        captured["spec_source"] = [
            resource.source for resource in spec.resources if resource.source
        ]
        from tests.gate_turn.test_transaction_gate_intent import _creation_result

        record = _record(tmp_path)
        return transaction_module.GateTurnCreation(
            gate=_creation_result(tmp_path),
            record=record,
            project_file=creator.project_file,
            claim_move=None,
            cl_name=creator.cl_name,
        )

    monkeypatch.setattr("sase.gate_turn.publisher.publish_gate_turn", fake_publish)

    publish_staged_gate(
        preparation.payload,
        staged_id=preparation.staged_id,
        artifacts_dir=str(artifacts),
    )

    assert captured["creator"].target_name == "original-agent"
    assert captured["frozen_auto"]["auto_execute"] is False
    assert "notes.md" in captured["resource_bytes"]
    assert captured["resource_bytes"]["notes.md"] == b"editable notes\n"
    assert [str(source) for source in captured["spec_source"]] == ["notes.md"]
