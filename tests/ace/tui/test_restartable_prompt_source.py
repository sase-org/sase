"""Restartable prompt-source coverage for historical family members."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path

from sase.agent.artifact_files_cache import get_global_cache
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.artifact_files import get_restartable_prompt_content


def _agent(
    artifacts_dir: Path,
    *,
    suffix: str,
    cl_name: str = "feature",
    parent_timestamp: str | None = None,
    step_name: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    effort: str | None = None,
) -> Agent:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/projects/project/project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 23, 12, 0, 0),
        raw_suffix=suffix,
        artifacts_dir=str(artifacts_dir),
        parent_timestamp=parent_timestamp,
        step_name=step_name,
        model=model,
        llm_provider=provider,
        reasoning_effort=effort,
    )


def test_restartable_prompt_prefers_raw_xprompt(tmp_path: Path) -> None:
    get_global_cache().clear()
    artifacts = tmp_path / "raw"
    agent = _agent(artifacts, suffix="20260723120000")
    (artifacts / "raw_xprompt.md").write_text(
        "#gh:feature\nraw launch prompt",
        encoding="utf-8",
    )
    (artifacts / "workflow-gh-main_prompt.md").write_text(
        "historical expanded prompt",
        encoding="utf-8",
    )

    assert get_restartable_prompt_content(agent, (agent,)) == (
        "#gh:feature\nraw launch prompt"
    )


def test_restartable_prompt_uses_matching_cached_fallback_and_restores_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    get_global_cache().clear()
    parent_dir = tmp_path / "parent"
    parent = _agent(
        parent_dir,
        suffix="20260723120000",
        cl_name="feature",
    )
    (parent_dir / "raw_xprompt.md").write_text(
        "#gh:project #propose\nPlan the change",
        encoding="utf-8",
    )
    (parent_dir / "embedded_workflows.json").write_text(
        json.dumps(
            [
                {"name": "gh", "tags": ["vcs"], "args": {"ref": "project"}},
                {"name": "propose", "tags": ["rollover"], "args": {}},
            ]
        ),
        encoding="utf-8",
    )

    child_dir = tmp_path / "child"
    child = _agent(
        child_dir,
        suffix="20260723120100",
        cl_name="feature",
        parent_timestamp=parent.raw_suffix,
        step_name="gh-main",
        model="gpt-5.6-sol",
        provider="codex",
        effort="xhigh",
    )
    matching = child_dir / "workflow-gh-main_prompt.md"
    matching.write_text("Implement the historical code body.", encoding="utf-8")
    unrelated = child_dir / "unrelated_prompt.md"
    unrelated.write_text("wrong prompt", encoding="utf-8")
    finalizer = child_dir / "commit_finalizer_pass_1_prompt.md"
    finalizer.write_text("commit finalizer prompt", encoding="utf-8")
    newest = matching.stat().st_mtime_ns + 5_000_000_000
    os.utime(unrelated, ns=(newest, newest))
    os.utime(finalizer, ns=(newest + 1, newest + 1))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._fork_scope.resolve_vcs_tag",
        lambda *_args: "#gh:feature ",
    )

    prompt = get_restartable_prompt_content(child, (parent, child))

    assert prompt == (
        "%model:codex/gpt-5.6-sol@xhigh\n"
        "#gh:feature\n"
        "Implement the historical code body.\n"
        "#propose\n"
    )


def test_restartable_complete_fallback_is_not_duplicated(tmp_path: Path) -> None:
    get_global_cache().clear()
    parent_dir = tmp_path / "parent"
    parent = _agent(parent_dir, suffix="20260723120000")
    (parent_dir / "embedded_workflows.json").write_text(
        json.dumps([{"name": "propose", "tags": ["rollover"], "args": {}}]),
        encoding="utf-8",
    )

    child_dir = tmp_path / "child"
    child = _agent(
        child_dir,
        suffix="20260723120100",
        parent_timestamp=parent.raw_suffix,
        step_name="gh-main",
        model="gpt-5.6-sol",
        provider="codex",
        effort="xhigh",
    )
    complete = (
        "%model:codex/gpt-5.6-sol@xhigh\n"
        "#gh:feature\n"
        "Implement the historical code body.\n"
        "#propose\n"
    )
    (child_dir / "workflow-gh-main_prompt.md").write_text(
        complete,
        encoding="utf-8",
    )

    assert get_restartable_prompt_content(child, (parent, child)) == complete
