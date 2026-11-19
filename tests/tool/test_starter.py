"""ToolRun starter identity helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.tool_run import tool_run_reserve_staged_join
from sase.monitor.join import JoinRefusal, inspect_join_target, join_caller_agent
from sase.tool.starter import resolve_starter, starter_agent_name
from tests.monitor._join_helpers import reserve_detached_run
from tests.tool._detach_helpers import agent_env, clean_env


def _session_member_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    artifacts = agent_env(monkeypatch, tmp_path, name="acme")
    meta_path = artifacts / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["name"] = "acme--code"
    meta["agent_session"] = "acme"
    meta["role_suffix"] = "--code"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def test_starter_identity_agrees_for_session_members(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    _session_member_env(monkeypatch, tmp_path)
    resolved = resolve_starter()
    assert starter_agent_name() == "acme"
    assert resolved.starter is not None
    assert resolved.starter["agent"] == "acme"
    assert join_caller_agent() == "acme"


def test_session_member_join_still_refuses_foreign_and_mismatched_agents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    _session_member_env(monkeypatch, tmp_path)
    foreign_id = reserve_detached_run("--", "true", agent="other")
    refused = inspect_join_target(foreign_id, join_caller_agent() or "")
    assert isinstance(refused, JoinRefusal)
    assert refused.exit_code == 2
    assert "belongs to agent" in refused.message
    owned_id = reserve_detached_run(
        "--", "true", agent="acme", owner_id="proc-owned-join"
    )
    reserved = tool_run_reserve_staged_join(
        {
            "schema_version": 1,
            "run_id": owned_id,
            "staged_id": "staged-mismatch",
            "monitor_id": "mon-mismatch",
            "agent": "acme--code",
        }
    )
    assert reserved["outcome"] == "refused"
    assert reserved["refusal"] == "agent_mismatch"
