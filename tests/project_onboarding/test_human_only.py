"""Tests for onboarding actor detection."""

from __future__ import annotations

from io import StringIO

import pytest

from sase.agent.identity import AgentIdentity
from sase.project_onboarding.human_only import detect_actor
import sase.project_onboarding.human_only as human_only


def _reset_bypass() -> None:
    human_only._emitted_bypass_reasons.clear()


class TestDetectActor:
    def test_empty_environment_is_human(self) -> None:
        assert detect_actor({}) == "human"

    def test_sase_agent_is_agent(self) -> None:
        assert detect_actor({"SASE_AGENT": "1"}) == "agent"

    def test_sase_agent_name_is_agent(self) -> None:
        assert detect_actor({"SASE_AGENT_NAME": "sase-1jx.7.1.1"}) == "agent"

    def test_monitor_id_is_agent(self) -> None:
        assert detect_actor({"SASE_MONITOR_ID": "mon-1"}) == "agent"

    def test_discovered_identity_is_agent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "sase.agent.identity.discover_agent_identity",
            lambda env: AgentIdentity(name="coder", source="agent_meta"),
        )
        assert detect_actor({}) == "agent"

    def test_gate_command_permits_human(self) -> None:
        assert detect_actor({"SASE_AGENT": "1", "SASE_GATE_COMMAND": "1"}) == "human"

    def test_other_gate_values_stay_agent(self) -> None:
        assert detect_actor({"SASE_AGENT": "1", "SASE_GATE_COMMAND": "0"}) == "agent"

    def test_bypass_permits_human_and_prints_once(self) -> None:
        _reset_bypass()
        stderr = StringIO()
        env = {"SASE_AGENT": "1", "SASE_PROJECT_CREATE_BYPASS": "repair-setup"}
        assert detect_actor(env, stderr=stderr) == "human"
        assert detect_actor(env, stderr=stderr) == "human"
        assert stderr.getvalue().count("repair-setup") == 1

    def test_blank_agent_markers_are_human(self) -> None:
        assert (
            detect_actor(
                {
                    "SASE_AGENT": "  ",
                    "SASE_AGENT_NAME": "",
                    "SASE_MONITOR_ID": "",
                }
            )
            == "human"
        )
