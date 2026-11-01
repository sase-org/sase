"""Tests for explicit staged-handoff recovery selection and output."""

from __future__ import annotations

import json
from types import SimpleNamespace

from sase.axe._run_agent_exec_staged_recovery_shared import StagedRecoveryResult
from sase.agent.staged_handoff import STAGED_HANDOFF_FILENAME
from sase.agents.cli_readopt import handle_agent_readopt
from sase.main.parser import create_parser
from tests.main.parser_help_helpers import parser_for


def test_readopt_parser_and_help() -> None:
    parser = create_parser(only="agent")
    args = parser.parse_args(["agent", "readopt", "origin", "-j"])
    assert args.agent_subcommand == "readopt"
    assert args.agent == "origin"
    assert args.json is True

    help_text = parser_for(("sase", "agent", "readopt")).format_help()
    assert "Retry recovery" in help_text
    assert "-j, --json" in help_text


def test_readopt_session_requires_one_staged_turn(
    tmp_path, monkeypatch, capsys
) -> None:
    from sase.agent.names import AgentSession, AgentSessionMember

    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    (one / STAGED_HANDOFF_FILENAME).write_text("{}", encoding="utf-8")
    (two / STAGED_HANDOFF_FILENAME).write_text("{}", encoding="utf-8")
    session = AgentSession(
        base_name="review",
        root=None,
        members=(
            AgentSessionMember("review--0", one, "1", None, None),
            AgentSessionMember("review--1", two, "2", None, None),
        ),
    )
    monkeypatch.setattr(
        "sase.agents.cli_readopt.find_agent_session", lambda _name: session
    )
    called = False

    def unexpected_recovery(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("ambiguous selectors must not invoke recovery")

    monkeypatch.setattr(
        "sase.agents.cli_readopt.recover_staged_handoff", unexpected_recovery
    )
    code = handle_agent_readopt(SimpleNamespace(agent="review", json=True))
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert called is False
    assert "review--0" in payload["reason"]
    assert "review--1" in payload["reason"]
    assert "exact originating agent name" in payload["reason"]


def test_readopt_reports_result_and_destination_refs(
    tmp_path, monkeypatch, capsys
) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / STAGED_HANDOFF_FILENAME).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sase.agents.cli_readopt.find_agent_session", lambda _name: None
    )
    monkeypatch.setattr(
        "sase.agents.cli_readopt.find_named_agent",
        lambda _name: SimpleNamespace(artifacts_dir=str(origin)),
    )
    result = StagedRecoveryResult(
        adopted=True,
        already_adopted=False,
        action="adopt",
        reason="recovered",
        kind="gate",
        origin_agent="review--plan",
        destination={"gate_request_id": "req-1"},
    )
    monkeypatch.setattr(
        "sase.agents.cli_readopt.recover_staged_handoff",
        lambda _path, mode: result if mode == "explicit" else None,
    )
    code = handle_agent_readopt(SimpleNamespace(agent="review--plan", json=True))
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["adopted"] is True
    assert payload["origin_agent"] == "review--plan"
    assert payload["destination"] == {"gate_request_id": "req-1"}
