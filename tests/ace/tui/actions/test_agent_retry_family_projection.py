"""Regression coverage for live plan-family retry projection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models.agent import Agent
from sase.agent.status_buckets import agent_status_bucket
from tests.ace.tui._retry_family_loader_fixture import (
    ROOT_TIMESTAMP,
    RUNNER_PID,
    build_retrying_plan_family,
)


def _load_family(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    runner_live: bool,
    include_retry_state: bool,
) -> tuple[Agent, list[Agent]]:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    build_retrying_plan_family(
        sase_home,
        next_retry_at_epoch=1_800_000_000.0,
        include_retry_state=include_retry_state,
    )

    def is_live(pid: int | None) -> bool:
        return runner_live and pid == RUNNER_PID

    with (
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            side_effect=is_live,
        ),
        patch(
            "sase.ace.tui.models._loaders._workflow_loaders.is_process_running",
            side_effect=is_live,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            side_effect=is_live,
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        result = load_agents_from_disk_with_state(
            set(),
            patch_snapshot=[],
            full_history=True,
        )

    roots = [
        agent
        for agent in result.all_agents
        if agent.raw_suffix == ROOT_TIMESTAMP and not agent.is_child_row
    ]
    assert len(roots) == 1
    return roots[0], result.all_agents


def test_live_failed_plan_family_projects_retry_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, agents = _load_family(
        tmp_path,
        monkeypatch,
        runner_live=True,
        include_retry_state=True,
    )

    assert root.status == "RETRYING"
    assert root.runner_is_live is True
    assert root.retry_status == "retrying"
    assert (root.retry_count, root.max_retries) == (2, 3)
    assert root.retry_next_at_epoch == 1_800_000_000.0
    assert root.retry_wait_seconds == 300
    assert agent_status_bucket(root) == "Running"

    planner = next(agent for agent in agents if agent.agent_family_role == "plan")
    coder = next(agent for agent in agents if agent.agent_family_role == "code")
    assert planner.status == "TALE APPROVED"
    assert coder.status == "FAILED"


@pytest.mark.parametrize(
    ("runner_live", "include_retry_state"),
    [(False, True), (True, False)],
)
def test_failed_plan_family_without_live_retry_remains_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_live: bool,
    include_retry_state: bool,
) -> None:
    root, _ = _load_family(
        tmp_path,
        monkeypatch,
        runner_live=runner_live,
        include_retry_state=include_retry_state,
    )

    assert root.status == "FAILED"
    assert root.retry_status is None
    assert (root.retry_count, root.max_retries) == (0, 0)
    assert agent_status_bucket(root) == "Failed"
