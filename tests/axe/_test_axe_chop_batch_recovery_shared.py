"""Shared helpers for chop batch recovery tests.

Split from ``tests.axe.test_axe_chop_batch_recovery``.
Helpers use public names so focused test modules can import them without
touching a ``_``-prefixed symbol across files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.axe_chop_facade import CHOP_BATCH_SCHEMA_VERSION


def manifest(batch_id: str = "run-1", clan: str | None = "clan-a") -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    for index in range(3):
        member: dict[str, Any] = {
            "source_index": index,
            "proposal_id": f"proposal-{index}",
            "agent_name": f"job-{index}",
            "prompt": f"%id:job-{index}\nDo {index}.",
            "workspace": "git:sase",
        }
        if clan is not None:
            member["clan"] = clan
        members.append(member)
    return {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "run": {"routine": "docs", "job": "refresh", "run_id": batch_id},
        "members": members,
    }


def record_spawn(
    *,
    routine: str = "docs",
    job: str = "refresh",
    run_id: str,
    index: int | None,
    proposal_id: str | None = None,
    cl_name: str = "sase",
    pid: int = 4242,
) -> None:
    """Write one production-shaped chop-agent record for a member spawn."""
    from sase.axe.chop_agents import (
        build_chop_launch_env,
        record_chop_agent_launch_from_env,
    )

    env = build_chop_launch_env(
        lumberjack_name=routine,
        chop_name=job,
        prompt="%id:job-0\nDo 0.",
        run_id=run_id,
        proposal_index=index,
        proposal_id=proposal_id,
    )
    record = record_chop_agent_launch_from_env(
        pid=pid,
        project_file="/tmp/projects/sase/sase.sase",
        project_name="sase",
        workspace_num=1,
        workflow_name="fake-chop-batch-recovery",
        cl_name=cl_name,
        timestamp="20261118_120000",
        prompt="%id:job-0\nDo 0.",
        env=env,
    )
    assert record is not None


def replay_manifest() -> dict[str, Any]:
    members: list[dict[str, Any]] = [
        {
            "source_index": 0,
            "proposal_id": "proposal-0",
            "agent_name": "job-0",
            "prompt": "#git:sase\n%id:job-0\nDo 0.",
            "workspace": "git:sase",
        },
        {
            "source_index": 1,
            "proposal_id": "proposal-1",
            "agent_name": "job-1",
            "prompt": "#git:sase\n%id:job-1\nDo 1.",
            "workspace": "git:sase",
            "status": "skipped",
            "status_reason": "explicit agent name collision",
        },
        {
            "source_index": 2,
            "proposal_id": "proposal-2",
            "agent_name": "job-2",
            "prompt": "#git:sase\n%id:job-2\n%wait:job-1\nDo 2.",
            "workspace": "git:sase",
            "wait_on": 1,
        },
        {
            "source_index": 3,
            "proposal_id": "proposal-3",
            "agent_name": "clan-a.worker",
            "prompt": "#git:sase\n%id(worker, clan=clan-a)\nDo 3.",
            "workspace": "git:sase",
            "launch_role": "join",
            "clan": "clan-a",
            "clan_generation": "gen-9",
        },
        {
            "source_index": 4,
            "proposal_id": "proposal-4",
            "agent_name": "clan-a.boss",
            "prompt": "#git:sase\n%id:clan-a.boss\n%clan(clan-a, tribe=eng)\nDo 4.",
            "workspace": "git:sase",
            "launch_role": "declare",
            "clan": "clan-a",
            "clan_generation": "gen-9",
        },
    ]
    return {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": "run-9",
        "run": {"routine": "docs", "job": "refresh", "run_id": "run-9"},
        "clan": "clan-a",
        "clan_generation": "gen-9",
        "members": members,
    }


@pytest.fixture(name="isolated_home")
def recovery_isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect SASE home to a temporary directory.

    Importing this fixture's name into a test module is enough for pytest to
    pick it up, since fixture discovery scans the module's own namespace.
    """

    home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home
