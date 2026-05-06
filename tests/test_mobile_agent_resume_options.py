"""Tests for mobile agent resume option payloads."""

from __future__ import annotations

from pathlib import Path

from sase.integrations import mobile_agents
from sase.integrations.mobile_agents import _mobile_agent_resume_options
from tests._mobile_agents_fixtures import _agent


def test_resume_options_use_native_resume_and_wait_syntax(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        mobile_agents,
        "list_all_agents",
        lambda: [_agent(tmp_path, name="alpha"), _agent(tmp_path, name="has space")],
    )

    payload = _mobile_agent_resume_options()

    assert payload["options"][0] == {
        "id": "alpha:resume",
        "agent_name": "alpha",
        "kind": "resume",
        "label": "Resume alpha",
        "prompt_text": "#resume:alpha\n",
        "direct_launch_supported": True,
    }
    assert payload["options"][1]["prompt_text"] == "%wait:alpha\n"
    assert payload["options"][2]["prompt_text"] == "#resume:`has space`\n"
    assert payload["options"][3]["prompt_text"] == "%wait:`has space`\n"
