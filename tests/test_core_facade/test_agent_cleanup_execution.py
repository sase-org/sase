"""Tests for Rust-backed agent cleanup execution helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.changespec import (
    CommentEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
)
from sase.ace.comments.operations import mark_comment_agents_as_killed
from sase.ace.dismissed_agents import save_dismissed_agents, save_dismissed_bundle
from sase.ace.hooks.processes import (
    mark_hook_agents_as_killed,
    mark_mentor_agents_as_killed,
)
from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_cleanup_execution import (
    mark_comment_agents_as_killed_rust,
    mark_hook_agents_as_killed_rust,
    mark_mentor_agents_as_killed_rust,
    try_release_workspace_from_content,
)


pytest.importorskip("sase_core_rs")


def _agent(**kwargs: Any) -> Agent:
    defaults: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "demo",
        "project_file": "/tmp/project.gp",
        "status": "DONE",
        "start_time": datetime(2026, 4, 30, 1, 2, 3),
        "stop_time": datetime(2026, 4, 30, 1, 3, 3),
        "pid": None,
        "raw_suffix": "20260430010203",
        "agent_name": "demo",
    }
    defaults.update(kwargs)
    return Agent(**defaults)


def test_dismissed_index_and_bundle_layout_use_rust_helpers(
    tmp_path: Path,
) -> None:
    dismissed_file = tmp_path / "dismissed_agents.json"
    bundles_dir = tmp_path / "dismissed_bundles"

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", dismissed_file),
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
    ):
        assert save_dismissed_agents(
            {
                (AgentType.RUNNING, "demo", "20260430010203"),
                (AgentType.WORKFLOW, "flow", None),
            }
        )
        parent = _agent()
        child = _agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="child",
            raw_suffix="20260430010203",
            parent_workflow="build",
            parent_timestamp="20260430010203",
            step_type="agent",
            step_index=2,
        )
        assert save_dismissed_bundle(parent)
        assert save_dismissed_bundle(child)

    assert json.loads(dismissed_file.read_text()) == [
        ["run", "demo", "20260430010203"],
        ["workflow", "flow", None],
    ]
    assert (bundles_dir / "202604" / "20260430010203.json").is_file()
    assert (bundles_dir / "202604" / "20260430010203__c2.json").is_file()


def test_release_workspace_content_helper_matches_running_field_semantics() -> None:
    content = (
        "RUNNING:\n"
        "  #1 | 111 | wf | demo\n"
        "  #2 | 222 | other | demo\n"
        "\n\n"
        "NAME: demo\n"
        "STATUS: WIP\n"
    )

    result = try_release_workspace_from_content(content, 1, "wf", "demo")

    assert result is not None
    assert result["removed"] is True
    assert result["has_remaining_claims"] is True
    assert "#1 | 111" not in result["content"]
    assert "RUNNING:\n  #2 | 222 | other | demo\n\n\nNAME: demo" in result["content"]


def test_artifact_marker_deletion_uses_rust_helper(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    for filename in ("workflow_state.json", "done.json", "prompt_step_0.json"):
        (artifacts / filename).write_text("{}")
    keep = artifacts / "response.md"
    keep.write_text("keep")

    delete_agent_artifacts(str(artifacts))

    assert not (artifacts / "workflow_state.json").exists()
    assert not (artifacts / "done.json").exists()
    assert not (artifacts / "prompt_step_0.json").exists()
    assert keep.read_text() == "keep"


def test_rust_kill_marking_matches_python_helpers() -> None:
    suffix = "agent-123-20260430010203"
    hooks = [
        HookEntry(
            command="pytest",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="20260430010203",
                    status="RUNNING",
                    suffix=suffix,
                    suffix_type="running_agent",
                )
            ],
        )
    ]
    mentors = [
        MentorEntry(
            entry_id="1",
            profiles=["feature"],
            status_lines=[
                MentorStatusLine(
                    profile_name="feature",
                    mentor_name="complete",
                    status="RUNNING",
                    timestamp="20260430010203",
                    suffix=suffix,
                    suffix_type="running_agent",
                )
            ],
        )
    ]
    comments = [
        CommentEntry(
            reviewer="crs",
            file_path="/tmp/comments.json",
            suffix=suffix,
            suffix_type="running_agent",
        )
    ]

    assert mark_hook_agents_as_killed_rust(
        hooks, [suffix]
    ) == mark_hook_agents_as_killed(
        hooks,
        [(hooks[0], hooks[0].status_lines[0], 123)],
    )
    assert mark_mentor_agents_as_killed_rust(
        mentors, [suffix]
    ) == mark_mentor_agents_as_killed(
        mentors,
        [(mentors[0], mentors[0].status_lines[0], 123)],
    )
    assert mark_comment_agents_as_killed_rust(
        comments, [suffix]
    ) == mark_comment_agents_as_killed(
        comments,
        [(comments[0], 123)],
    )
