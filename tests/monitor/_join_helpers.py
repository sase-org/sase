"""Shared helpers for monitor join tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_claim
from sase.tool.argv import resolve_run_argv
from sase.tool.executor_recording import finish_tool_run
from sase.tool.handoff import reserve_handoff_run

__all__ = [
    "join_env",
    "reserve_detached_run",
    "settle_detached_run",
]


@pytest.fixture(autouse=True)
def join_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
    ):
        monkeypatch.delenv(key, raising=False)
    clear_config_cache()


def _starter(agent: str = "agent-1") -> dict[str, object]:
    return {
        "agent": agent,
        "pid": os.getpid(),
        "boot_id": "boot-1",
        "process_start_identity": "boot-1:1",
    }


def reserve_detached_run(
    *words: str, agent: str = "agent-1", owner_id: str = "proc-join-engine"
) -> str:
    resolved = resolve_run_argv(list(words))
    reservation = reserve_handoff_run(
        resolved,
        owner_kind="proc",
        owner_id=owner_id,
        agent=agent,
        starter=_starter(agent),
    )
    assert reservation.reserved, reservation.error
    return reservation.run_id


def settle_detached_run(
    run_id: str,
    *,
    state: str,
    exit_code: int | None,
    terminal_cause: str,
    owner_id: str = "proc-join-engine",
) -> None:
    claimed = tool_run_claim(
        {
            "schema_version": 1,
            "run_id": run_id,
            "owner_kind": "proc",
            "owner_id": owner_id,
            "wrapper_pid": os.getpid(),
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        }
    )
    assert claimed.get("outcome") == "claimed", claimed
    assert finish_tool_run(
        run_id,
        state=state,
        exit_code=exit_code,
        duration_ms=9,
        terminal_cause=terminal_cause,
    )
