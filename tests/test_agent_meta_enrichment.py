"""Tests for enrich_agent_from_meta reading agent_meta.json."""

import json
from datetime import datetime
from pathlib import Path

from sase.ace.tui.models._loaders._artifact_loaders import enrich_agent_from_meta
from sase.ace.tui.models.agent import Agent, AgentType


def _make_agent() -> Agent:
    """Create a minimal Agent for testing."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test_cl",
        project_file="/fake/path.gp",
        status="RUNNING",
        start_time=datetime(2026, 1, 1, 12, 0, 0),
    )


def testenrich_agent_from_meta_valid(tmp_path: Path) -> None:
    """Verify model and vcs_provider are populated from agent_meta.json."""
    meta_data = {"model": "sonnet", "vcs_provider": "GitHub"}
    with open(tmp_path / "agent_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta_data, f)

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.model == "sonnet"
    assert agent.vcs_provider == "GitHub"


def testenrich_agent_from_meta_missing_file(tmp_path: Path) -> None:
    """Verify no error when agent_meta.json is missing."""
    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.model is None
    assert agent.vcs_provider is None


def testenrich_agent_from_meta_malformed_json(tmp_path: Path) -> None:
    """Verify no error when agent_meta.json contains invalid JSON."""
    with open(tmp_path / "agent_meta.json", "w", encoding="utf-8") as f:
        f.write("{bad json")

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.model is None
    assert agent.vcs_provider is None


def testenrich_agent_from_meta_none_artifacts_dir() -> None:
    """Verify no error when artifacts_dir is None."""
    agent = _make_agent()
    enrich_agent_from_meta(agent, None)

    assert agent.model is None
    assert agent.vcs_provider is None


def testenrich_agent_from_meta_partial_fields(tmp_path: Path) -> None:
    """Verify only present fields are set."""
    meta_data = {"model": "opus"}
    with open(tmp_path / "agent_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta_data, f)

    agent = _make_agent()
    enrich_agent_from_meta(agent, str(tmp_path))

    assert agent.model == "opus"
    assert agent.vcs_provider is None
