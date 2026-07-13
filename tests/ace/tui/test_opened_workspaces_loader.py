"""Tests for the per-agent opened-workspaces loader."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui import opened_workspaces as opened_workspaces_module
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.opened_workspaces import (
    _load_opened_workspaces_for_agent,
    load_opened_workspaces_for_agent_context,
)
from sase.linked_repos import (
    OPENED_LINKED_FILENAME,
    record_opened_external_repo,
    record_opened_linked_repo,
)
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
)


def _make_agent(
    *,
    artifacts_dir: Path | None,
    agent_name: str | None = None,
    workspace_dir: Path | None = None,
    raw_suffix: str = "20260620-140000",
    role_suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="opened-workspaces-test",
        project_file="/tmp/opened-workspaces-test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 20, 14, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        workspace_dir=str(workspace_dir) if workspace_dir else None,
        artifacts_dir=str(artifacts_dir) if artifacts_dir else None,
        role_suffix=role_suffix,
    )


def _record(
    monkeypatch: pytest.MonkeyPatch,
    artifacts_dir: Path,
    *,
    name: str,
    workspace_dir: Path,
    reason: str,
    opened_at: str,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    record_opened_linked_repo(
        name,
        str(workspace_dir),
        reason=reason,
        opened_at=opened_at,
    )


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    opened_workspaces_module._opened_workspaces_cache.clear()
    opened_workspaces_module._opened_workspaces_context_cache.clear()


def test_single_agent_reads_own_artifacts_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    other_dir = tmp_path / "artifacts" / "agent_b"
    workspace_dir = tmp_path / "workspace"
    for directory in (artifacts_dir, other_dir, workspace_dir):
        directory.mkdir(parents=True)

    _record(
        monkeypatch,
        artifacts_dir,
        name="sase-core",
        workspace_dir=tmp_path / "sase-core_13",
        reason="inspect core boundary",
        opened_at="2026-06-20T14:00:00+00:00",
    )
    _record(
        monkeypatch,
        other_dir,
        name="sase-nvim",
        workspace_dir=tmp_path / "sase-nvim_13",
        reason="unrelated agent",
        opened_at="2026-06-20T14:01:00+00:00",
    )

    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=workspace_dir,
    )
    result = _load_opened_workspaces_for_agent(agent)

    assert [(event.name, event.reason, event.agent_label) for event in result] == [
        ("sase-core", "inspect core boundary", None)
    ]


def test_results_are_newest_first_and_limit_caps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    workspace_dir = tmp_path / "workspace"
    artifacts_dir.mkdir(parents=True)
    workspace_dir.mkdir()
    for index in range(7):
        _record(
            monkeypatch,
            artifacts_dir,
            name=f"repo-{index}",
            workspace_dir=tmp_path / f"repo-{index}_13",
            reason=f"reason {index}",
            opened_at=f"2026-06-20T14:0{index}:00+00:00",
        )

    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=workspace_dir,
    )
    result = _load_opened_workspaces_for_agent(agent, limit=3)

    assert [event.name for event in result] == ["repo-6", "repo-5", "repo-4"]


def test_context_aggregates_family_with_role_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    plan_dir = tmp_path / "artifacts" / "plan"
    coder_dir = tmp_path / "artifacts" / "coder"
    q_dir = tmp_path / "artifacts" / "q"
    for directory in (plan_dir, coder_dir, q_dir):
        directory.mkdir(parents=True)

    _record(
        monkeypatch,
        plan_dir,
        name="sase-core",
        workspace_dir=tmp_path / "sase-core_13",
        reason="planner inspected core",
        opened_at="2026-06-20T14:00:00+00:00",
    )
    _record(
        monkeypatch,
        coder_dir,
        name="sase-github",
        workspace_dir=tmp_path / "sase-github_13",
        reason="coder checked github plugin",
        opened_at="2026-06-20T14:05:00+00:00",
    )
    _record(
        monkeypatch,
        q_dir,
        name="sase-nvim",
        workspace_dir=tmp_path / "sase-nvim_13",
        reason="questions checked editor plugin",
        opened_at="2026-06-20T14:02:00+00:00",
    )

    root = _make_agent(
        artifacts_dir=plan_dir,
        agent_name="alpha--plan",
        workspace_dir=workspace_dir,
        raw_suffix="20260620-140000-plan",
        role_suffix=PLAN_CHAIN_PLAN_SUFFIX,
    )
    coder = _make_agent(
        artifacts_dir=coder_dir,
        agent_name="alpha--code",
        workspace_dir=workspace_dir,
        raw_suffix="20260620-140000-code",
        role_suffix=PLAN_CHAIN_CODER_SUFFIX,
    )
    question = _make_agent(
        artifacts_dir=q_dir,
        agent_name="alpha--q",
        workspace_dir=workspace_dir,
        raw_suffix="20260620-140000-q",
        role_suffix=PLAN_CHAIN_QUESTION_SUFFIX,
    )
    root.followup_agents = [coder, question]

    result = load_opened_workspaces_for_agent_context(root)

    assert [(event.name, event.agent_label) for event in result] == [
        ("sase-github", "coder"),
        ("sase-nvim", "q"),
        ("sase-core", "plan"),
    ]


def test_cache_invalidates_on_marker_mtime_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    workspace_dir = tmp_path / "workspace"
    artifacts_dir.mkdir(parents=True)
    workspace_dir.mkdir()
    _record(
        monkeypatch,
        artifacts_dir,
        name="sase-core",
        workspace_dir=tmp_path / "sase-core_13",
        reason="initial",
        opened_at="2026-06-20T14:00:00+00:00",
    )

    agent = _make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=workspace_dir,
    )
    first = _load_opened_workspaces_for_agent(agent)
    assert [event.name for event in first] == ["sase-core"]

    _record(
        monkeypatch,
        artifacts_dir,
        name="sase-nvim",
        workspace_dir=tmp_path / "sase-nvim_13",
        reason="new marker record",
        opened_at="2026-06-20T14:05:00+00:00",
    )
    marker = artifacts_dir / OPENED_LINKED_FILENAME
    future_mtime_ns = marker.stat().st_mtime_ns + 10_000_000_000
    os.utime(marker, ns=(future_mtime_ns, future_mtime_ns))
    for entry in opened_workspaces_module._opened_workspaces_cache.values():
        entry.last_read_monotonic = 0.0

    second = _load_opened_workspaces_for_agent(agent)
    assert [event.name for event in second] == ["sase-nvim", "sase-core"]


def test_missing_artifacts_dir_returns_empty_tuple() -> None:
    agent = _make_agent(artifacts_dir=None, agent_name="alpha")

    assert _load_opened_workspaces_for_agent(agent) == ()
    assert load_opened_workspaces_for_agent_context(agent) == ()


def test_external_workspace_records_preserve_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir = tmp_path / "workspace"
    artifacts_dir.mkdir()
    workspace_dir.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    record_opened_external_repo(
        "gh:pallets/click",
        str(workspace_dir / "sase" / "repos" / "external" / "gh" / "pallets" / "click"),
        reason="inspect upstream parsing",
        opened_at="2026-07-13T18:00:00+00:00",
    )

    events = _load_opened_workspaces_for_agent(
        _make_agent(artifacts_dir=artifacts_dir, workspace_dir=workspace_dir)
    )

    assert [(event.name, event.kind) for event in events] == [
        ("gh:pallets/click", "external")
    ]
