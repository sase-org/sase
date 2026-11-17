"""CLI ingress tests for Agent Hijack stop (``sase agent hijack``)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack.stop import HijackStopResult
from tests._agent_hijack_stop_support import AGENT


def test_cli_json_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from sase.agents.cli_hijack import handle_agents_hijack

    expected = HijackStopResult(
        status="held",
        message="hijacked",
        exit_code=0,
        hijack_id="h-1",
        record={"workspace_num": 4},
    )
    monkeypatch.setattr(
        "sase.agents.cli_hijack.stop_agent_for_hijack", lambda *a, **k: expected
    )
    args = argparse.Namespace(name=AGENT, reason=None, json=True)
    assert handle_agents_hijack(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["hijack_id"] == "h-1"
    assert payload["workspace_num"] == 4


def test_cli_explain_json_is_additive_and_does_not_stop(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    from sase.agents.cli_hijack import handle_agents_hijack

    subject = SimpleNamespace(
        occupant_name="sase-7f.2",
        occupant_reason="sase-7f.2 holds the workspace claim",
        target=SimpleNamespace(workspace_num=4),
    )
    decision = {
        "mode": "immediate",
        "eligible": True,
        "code": None,
        "message": None,
        "next_action": None,
        "redirect_op": None,
        "adapter": "llm",
    }
    monkeypatch.setattr(
        "sase.agents.cli_hijack.resolve_and_decide",
        lambda name: (subject, decision),
    )
    monkeypatch.setattr(
        "sase.agents.cli_hijack.stop_agent_for_hijack",
        lambda *args, **kwargs: pytest.fail("--explain must not stop a turn"),
    )

    args = argparse.Namespace(name=AGENT, reason=None, json=True, explain=True)
    assert handle_agents_hijack(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "explained"
    assert payload["occupant_name"] == "sase-7f.2"
    assert payload["mode"] == "immediate"
    assert payload["adapter"] == "llm"
    assert payload["workspace_num"] == 4

    args.json = False
    assert handle_agents_hijack(args) == 0
    assert (
        "Selected because: sase-7f.2 holds the workspace claim"
        in capsys.readouterr().out
    )
