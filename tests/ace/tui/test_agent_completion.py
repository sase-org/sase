"""Tests for shared visible-agent completion candidates."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.agent_completion import (
    build_agent_completion_candidates,
    filter_agent_completion_candidates,
)
from sase.ace.tui.models.agent import Agent, AgentType


def _agent(tmp_path: Path, **overrides: Any) -> Agent:
    raw_prompt = overrides.pop("raw_prompt", None)
    artifacts_dir = overrides.pop("artifacts_dir", None)
    if raw_prompt is not None:
        artifact_root = tmp_path / str(overrides.get("raw_suffix", "agent"))
        artifact_root.mkdir()
        (artifact_root / "raw_xprompt.md").write_text(raw_prompt, encoding="utf-8")
        artifacts_dir = str(artifact_root)

    defaults: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "sase",
        "project_file": "/tmp/projects/sase/sase.sase",
        "status": "RUNNING",
        "start_time": datetime(2026, 6, 24, 12, 0, 0),
        "raw_suffix": "260624_120000",
        "agent_name": "coder",
        "artifacts_dir": artifacts_dir,
    }
    defaults.update(overrides)
    return Agent(**defaults)


def test_build_agent_completion_candidates_enriches_visible_named_agents(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "sase.xprompt.extract_vcs_workflow_tag",
        lambda prompt: "#gh:sase " if prompt.startswith("#gh:sase ") else None,
    )
    monkeypatch.setattr(
        "sase.xprompt.strip_vcs_workflow_tag",
        lambda prompt: prompt.removeprefix("#gh:sase "),
    )
    monkeypatch.setattr(
        "sase.xprompt.extract_project_from_vcs_tag",
        lambda tag: "sase" if tag.strip() == "#gh:sase" else None,
    )
    monkeypatch.setattr(
        "sase.workspace_provider.get_display_name",
        lambda workflow_type: "GitHub" if workflow_type == "gh" else None,
    )

    family = _agent(
        tmp_path,
        agent_name="completion.plan",
        agent_family="completion",
        agent_family_role="root",
        plan_chain_root=True,
        model="gpt-5",
        llm_provider="codex",
        reasoning_effort="high",
        tag="review",
        raw_prompt="%wait(old, time=5m) #gh:sase Redesign wait completion\nwith rows",
    )
    duplicate = _agent(tmp_path, agent_name="completion", raw_suffix="260624_120001")
    unnamed = _agent(tmp_path, agent_name=None, raw_suffix="260624_120002")
    other = _agent(tmp_path, agent_name="verifier", raw_suffix="260624_120003")

    candidates = build_agent_completion_candidates(
        [family, duplicate, unnamed, other],
        exclude_identity=other.identity,
    )

    assert [candidate.name for candidate in candidates] == ["completion"]
    candidate = candidates[0]
    assert candidate.label == "completion.plan"
    assert candidate.model == "codex / gpt-5@high"
    assert candidate.tag == "#review"
    assert candidate.prompt_snippet == "Redesign wait completion with rows"
    assert candidate.vcs_workflow is not None
    assert candidate.vcs_workflow.display == "#gh:sase"
    assert candidate.vcs_workflow.workflow_type == "gh"
    assert candidate.vcs_workflow.project == "sase"
    assert candidate.vcs_workflow.provider_display == "GitHub"


def test_filter_agent_completion_candidates_uses_name_prefix(tmp_path: Path) -> None:
    candidates = build_agent_completion_candidates(
        [
            _agent(tmp_path, agent_name="planner", raw_suffix="260624_120010"),
            _agent(tmp_path, agent_name="coder", raw_suffix="260624_120011"),
        ]
    )

    assert [
        candidate.name
        for candidate in filter_agent_completion_candidates(candidates, "co")
    ] == ["coder"]
