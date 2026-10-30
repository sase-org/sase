"""Shared gate-entry behavior for staged and immediate gate requests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.gate_turn import entry


def test_auto_gate_publishes_inline_with_frozen_policy(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    import sase.agent.staged_handoff as staged_handoff
    import sase.gate_turn as gate_turn
    import sase.gate_turn.staged_contract as staged_contract

    released: list[str] = []
    captured: dict[str, Any] = {}
    monkeypatch.setattr(staged_handoff, "staged_handoffs_enabled", lambda: True)
    monkeypatch.setattr(
        staged_handoff, "acquire_staging_reservation", lambda **_kwargs: "reservation"
    )
    monkeypatch.setattr(
        staged_contract,
        "collect_staged_gate_creator",
        lambda **_kwargs: {"project": "test"},
    )
    monkeypatch.setattr(
        staged_handoff,
        "release_staging_reservation",
        lambda reservation_id, **_kwargs: released.append(reservation_id),
    )
    monkeypatch.setattr(
        staged_handoff,
        "write_staged_handoff",
        lambda *_args, **_kwargs: pytest.fail("auto gate was staged"),
    )
    preparation = SimpleNamespace(
        auto_execute=True,
        spec=SimpleNamespace(kind="custom"),
        request_id="auto-gate",
        staged_id="auto-stage",
        workspace_mode="inherit",
        decision={"outcome": "auto", "selected_options": ["proceed"]},
        policy_block={"profile": "question_fixture"},
        record=None,
        snapshot_dir=None,
    )
    monkeypatch.setattr(entry, "_prepare_staged_gate", lambda *_a, **_k: preparation)
    monkeypatch.setattr(
        gate_turn,
        "create_gate_turn",
        lambda _request, **kwargs: (
            captured.update(kwargs)
            or SimpleNamespace(should_handoff=False, to_dict=lambda: {"kind": "custom"})
        ),
        raising=False,
    )
    monkeypatch.setattr(
        gate_turn,
        "will_handoff_gate_to_agent_runner",
        lambda: False,
        raising=False,
    )

    entry.handle_gate_entry(lambda: {"kind": "custom"}, command="sase gate create")

    out = capsys.readouterr()
    assert json.loads(out.out) == {"kind": "custom"}
    assert out.err == ""
    assert captured["frozen_auto"] == {
        "decision": preparation.decision,
        "policy_block": preparation.policy_block,
        "auto_execute": True,
    }
    assert released == ["reservation"]


def test_allow_auto_false_rejects_auto_execute_before_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    import sase.agent.staged_handoff as staged_handoff
    import sase.gate_turn.staged_contract as staged_contract
    from sase.gate_turn.models import GateTurnError

    released: list[str] = []
    monkeypatch.setattr(staged_handoff, "staged_handoffs_enabled", lambda: True)
    monkeypatch.setattr(
        staged_handoff, "acquire_staging_reservation", lambda **_kwargs: "reservation"
    )
    monkeypatch.setattr(
        staged_contract,
        "collect_staged_gate_creator",
        lambda **_kwargs: {"project": "test"},
    )
    monkeypatch.setattr(
        staged_handoff,
        "release_staging_reservation",
        lambda reservation_id, **_kwargs: released.append(reservation_id),
    )
    monkeypatch.setattr(
        staged_handoff,
        "write_staged_handoff",
        lambda *_args, **_kwargs: pytest.fail("auto launch was staged"),
    )
    preparation = SimpleNamespace(
        auto_execute=True,
        spec=SimpleNamespace(kind="launch"),
        request_id="launch-auto",
        staged_id="auto-stage",
        workspace_mode="inherit",
        decision={"outcome": "auto", "selected_options": ["approve"]},
        policy_block={"profile": "launch"},
        record=None,
        snapshot_dir=None,
    )
    monkeypatch.setattr(entry, "_prepare_staged_gate", lambda *_a, **_k: preparation)
    with pytest.raises(GateTurnError, match="cannot auto-execute"):
        entry.run_gate_entry(
            lambda: {"kind": "launch"},
            command="sase launch request",
            allow_auto=False,
        )
    assert released == ["reservation"]
