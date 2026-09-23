"""Regression: proc holds are released before the terminal row is published."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_hold_facade import (
    arm_agent_hold,
    list_agent_holds_without_liveness,
)
from sase.procs.models import ProcReserve
from sase.procs.store import reserve_proc


def test_settlement_releases_proc_hold_before_publishing_terminal_row(
    monkeypatch: Any, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    proc_id = "proc-hold-ordering"
    outcome = reserve_proc(
        ProcReserve(
            proc_id=proc_id,
            label=proc_id,
            argv=["true"],
            cwd=str(tmp_path),
            created_at="2026-09-23T00:00:00Z",
            log_path=str(tmp_path / f"{proc_id}.log"),
            request_fingerprint="test-fingerprint",
            reserved_by="test",
            project="sase",
        )
    )
    proc = outcome.proc
    assert proc.lifecycle == "proc-shell"
    arm_agent_hold(
        armer={
            "kind": "proc",
            "key": f"proc:{proc_id}",
            "display": proc_id,
            "project": "sase",
            "proc_id": proc_id,
        },
        future=True,
        scope="project",
        ttl_seconds=60.0,
    )
    assert [hold["armer"]["key"] for hold in list_agent_holds_without_liveness()] == [
        f"proc:{proc_id}"
    ]

    import sase.procs.settlement as settlement

    real_finish_proc = settlement.finish_proc
    seen: list[list[dict[str, Any]]] = []

    def _spy_finish(finish: Any) -> Any:
        seen.append(list_agent_holds_without_liveness())
        return real_finish_proc(finish)

    monkeypatch.setattr(settlement, "finish_proc", _spy_finish)

    finished = settlement.settle_proc_shell(
        proc_id,
        supervisor_id="test-supervisor",
        status="success",
        message="done",
        termination_reason="success",
        exit_code=0,
    )

    assert finished.status == "success"
    assert len(seen) == 1
    assert [
        hold for hold in seen[0] if hold["armer"].get("key") == f"proc:{proc_id}"
    ] == []
    assert list_agent_holds_without_liveness() == []
