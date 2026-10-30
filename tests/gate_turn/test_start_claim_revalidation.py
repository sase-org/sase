"""Claim moves revalidate ownership instead of trusting a recorded PID."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.gate_turn.start_claim import move_gate_turn_claim
from sase.running_field import WorkspaceClaim


def _claim(
    *,
    pid: int,
    artifacts_timestamp: str = "20261029120000",
    cl_name: str | None = "cl-1",
) -> WorkspaceClaim:
    return WorkspaceClaim(
        workspace_num=3,
        workflow="ace-run",
        cl_name=cl_name,
        pid=pid,
        artifacts_timestamp=artifacts_timestamp,
    )


def test_live_pid_with_matching_identity_transfers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim = _claim(pid=111)
    monkeypatch.setattr(
        "sase.gate_turn.start_claim.get_claimed_workspaces", lambda _path: [claim]
    )
    monkeypatch.setattr(
        "sase.gate_turn.start_claim._creator_pid_is_live", lambda _pid: True
    )
    transferred: list[tuple[int, int]] = []

    def fake_transfer(_project, _ws, *, from_pid, to_pid, **_kwargs):
        transferred.append((from_pid, to_pid))
        from sase.running_field import ClaimResult

        return ClaimResult(True)

    monkeypatch.setattr(
        "sase.gate_turn.start_claim.transfer_workspace_claim", fake_transfer
    )

    move = move_gate_turn_claim(
        str(tmp_path / "proj.sase"),
        3,
        creator_pid=111,
        artifacts_timestamp="20261029120100",
        cl_name="cl-1",
        workspace_policy="inherit",
        creator_artifacts_timestamp="20261029120000",
    )

    assert move.result.success
    assert transferred == [(111, 111)]


def test_reused_live_pid_with_foreign_identity_refuses_to_steal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    foreign = _claim(pid=111, artifacts_timestamp="someone-else", cl_name="other")
    monkeypatch.setattr(
        "sase.gate_turn.start_claim.get_claimed_workspaces", lambda _path: [foreign]
    )
    monkeypatch.setattr(
        "sase.gate_turn.start_claim._creator_pid_is_live", lambda _pid: True
    )

    def fail_transfer(*_args, **_kwargs):
        raise AssertionError("must not transfer a reused PID")

    monkeypatch.setattr(
        "sase.gate_turn.start_claim.transfer_workspace_claim", fail_transfer
    )

    move = move_gate_turn_claim(
        str(tmp_path / "proj.sase"),
        3,
        creator_pid=111,
        artifacts_timestamp="20261029120100",
        cl_name="cl-1",
        workspace_policy="inherit",
        creator_artifacts_timestamp="20261029120000",
    )

    assert not move.result.success
    assert "no longer owned" in (move.result.error or "")


def test_dead_pid_still_listed_may_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim = _claim(pid=111)
    monkeypatch.setattr(
        "sase.gate_turn.start_claim.get_claimed_workspaces", lambda _path: [claim]
    )
    monkeypatch.setattr(
        "sase.gate_turn.start_claim._creator_pid_is_live", lambda _pid: False
    )
    transferred: list[int] = []

    def fake_transfer(_project, _ws, *, from_pid, to_pid, **_kwargs):
        del to_pid
        transferred.append(from_pid)
        from sase.running_field import ClaimResult

        return ClaimResult(True)

    monkeypatch.setattr(
        "sase.gate_turn.start_claim.transfer_workspace_claim", fake_transfer
    )

    move = move_gate_turn_claim(
        str(tmp_path / "proj.sase"),
        3,
        creator_pid=111,
        artifacts_timestamp="20261029120100",
        cl_name="cl-1",
        workspace_policy="inherit",
        creator_artifacts_timestamp="20261029120000",
    )

    assert move.result.success
    assert transferred == [111]
