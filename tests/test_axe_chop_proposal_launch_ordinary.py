"""Ordinary chop proposal-launch coverage.

Split from ``tests.test_axe_chop_proposal_launch``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.axe import chop_batch_store
from sase.axe.chop_proposal_launch import launch_chop_proposals
from sase.axe.chop_proposal_planning import plan_chop_proposals
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.chop_runner_script_result_launch import (
    launch_accepted_script_chop_proposals,
)
from sase.axe.config import ChopConfig
from sase.axe.state import ChopRunEntry, read_chop_run, start_chop_run

pytest_plugins = ["tests.axe_chop_runner_fixtures"]

__all__ = [
    "test_ordinary_clan_kill_settles_crossing_launch_without_failing_run",
    "test_ordinary_first_run_owns_batch_through_launch",
]


def test_ordinary_first_run_owns_batch_through_launch(
    temp_state_dir: Path,
) -> None:
    prepared = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "id": "refresh",
                    "prompt": "Review the docs.",
                    "workspace": "git:sase",
                    "agent_name": "refresh",
                }
            ]
        },
    )
    run_id = "run-owned-first-dispatch"
    ownership_seen: list[bool] = []

    def _launch(
        _prompt: str, *, extra_env: dict[str, str], **_kwargs: object
    ) -> SimpleNamespace:
        owner = chop_batch_store.read_chop_batch_owner("docs", "docs", run_id)
        ownership_seen.append(owner is not None)
        assert (
            chop_batch_store.acquire_chop_batch_ownership("docs", "docs", run_id)
            is False
        )
        return SimpleNamespace(pid=701, agent_name="refresh", timestamp="")

    launches = launch_chop_proposals(
        lumberjack_name="docs",
        chop_name="docs",
        run_id=run_id,
        proposals=prepared,
        launch_agent_from_cwd_fn=_launch,
        run_started_at=datetime.now(UTC),
        preflight=SimpleNamespace(decision={}),
    )

    assert len(launches) == 1
    assert ownership_seen == [True]
    assert chop_batch_store.read_chop_batch_owner("docs", "docs", run_id) is None


def test_ordinary_clan_kill_settles_crossing_launch_without_failing_run(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    prepared = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "id": "first",
                    "prompt": "Review the first file.",
                    "workspace": "git:sase",
                    "agent_name": "first",
                    "dedupe_key": "docs:first",
                },
                {
                    "id": "second",
                    "prompt": "Review the second file.",
                    "workspace": "git:sase",
                    "agent_name": "second",
                    "dedupe_key": "docs:second",
                },
            ]
        },
    )
    run_id = "run-crossing-clan-kill"
    started_at = datetime.now(UTC)
    start_chop_run(
        ChopRunEntry(
            run_id=run_id,
            lumberjack_name="docs",
            chop_name="docs",
            started_at=started_at.isoformat(),
            finished_at=None,
            duration_ms=0,
            status="running",
        )
    )
    launch_calls: list[str] = []

    def _launch(
        _prompt: str,
        *,
        extra_env: dict[str, str],
        before_agent_spawn: Any,
        on_agent_launch_recorded: Any,
        **_kwargs: object,
    ) -> SimpleNamespace:
        planned_name = str(extra_env.get("SASE_AGENT_PLANNED_NAME") or "first")
        request = SimpleNamespace(
            extra_env=extra_env,
            name_reservation=SimpleNamespace(agent_name=planned_name),
        )
        before_agent_spawn(0, 0, request, None)
        chop_batch_store.apply_chop_batch_event(
            "docs",
            "docs",
            run_id,
            "cancel_clan_generation",
            reason="test clan kill during launch",
        )
        result = SimpleNamespace(
            pid=702,
            agent_name=planned_name,
            timestamp="",
            workspace_num=1,
            workspace_dir="/workspace/1",
            project_name="sase",
            workflow_name="test",
        )
        on_agent_launch_recorded(
            0,
            0,
            SimpleNamespace(result=result, request=request),
            None,
        )
        launch_calls.append(planned_name)
        return result

    outcome = launch_accepted_script_chop_proposals(
        lumberjack_name="docs",
        chop=ChopConfig(name="docs", description=""),
        run_id=run_id,
        started_at=started_at,
        result_path=tmp_path / "result.json",
        chop_verbose=False,
        preflight=SimpleNamespace(decision={}),
        structured_result={"status": "ok"},
        prepared_proposals=prepared,
        accepted_proposals=prepared,
        proposals=[],
        once_per_decisions={},
        once_per_effective_waits={
            proposal.index: proposal.wait_on for proposal in prepared
        },
        launch_plans=plan_chop_proposals(prepared),
        launch_agent_from_cwd_fn=_launch,
        launch_agents_from_cwd_fn=None,
    )

    manifest = chop_batch_store.load_chop_batch("docs", "docs", run_id)
    entry = read_chop_run("docs", "docs", run_id)
    assert outcome.status == "launched"
    assert outcome.error is None
    assert entry is not None
    assert entry.status == "launched"
    assert len(entry.launches) == 1
    assert launch_calls == ["first"]
    assert manifest["status"] == "cancelled"
    assert [member["status"] for member in manifest["members"]] == [
        "launched",
        "cancelled",
    ]
