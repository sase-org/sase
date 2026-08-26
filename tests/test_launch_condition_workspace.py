"""Condition-scoped workspace leases for typed launch admission."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.launch_condition_workspace import (
    CONDITION_WORKSPACE_MARKER,
    ConditionWorkspaceError,
    ConditionWorkspaceUnavailable,
    acquire_condition_workspace,
    settle_condition_workspace,
)
from sase.workspace_provider.lease import OperationalLeaseError
from tests.workspace_lease_helpers import fake_operational_lease


def test_condition_workspace_marker_releases_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    released: list[dict[str, Any]] = []

    def fake_acquire(
        project: str,
        *,
        workflow: str,
        holder: str,
        **_kwargs: object,
    ) -> Any:
        return fake_operational_lease(
            checkout,
            project=project,
            workflow=f"lease({workflow})",
            holder=holder,
        )

    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.acquire_operational_lease",
        fake_acquire,
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.release_operational_lease",
        lambda policy: released.append(dict(policy)),
    )

    work_dir = tmp_path / "work"
    lease = acquire_condition_workspace(
        project="sase",
        request_id="req",
        plan_digest="d" * 64,
        logical_id="unit-1",
        work_dir=work_dir,
    )

    assert lease.checkout_dir == checkout
    marker_path = work_dir / CONDITION_WORKSPACE_MARKER
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["settled"] is False

    settle_condition_workspace(work_dir)
    settle_condition_workspace(work_dir)

    assert len(released) == 1
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["settled"] is True
    assert marker["lease"]["workflow"].startswith("lease(launch-if:")


def test_condition_workspace_contention_is_retryable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_acquire(*_args: object, **_kwargs: object) -> Any:
        raise OperationalLeaseError("allocation", "all workspaces are claimed")

    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.acquire_operational_lease",
        fake_acquire,
    )

    with pytest.raises(ConditionWorkspaceUnavailable):
        acquire_condition_workspace(
            project="sase",
            request_id="req",
            plan_digest="d" * 64,
            logical_id="unit-1",
            work_dir=tmp_path / "work",
        )


def test_condition_workspace_marker_write_failure_releases_acquired_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    released: list[dict[str, Any]] = []

    def fake_acquire(
        project: str,
        *,
        workflow: str,
        holder: str,
        **_kwargs: object,
    ) -> Any:
        return fake_operational_lease(
            checkout,
            project=project,
            workflow=f"lease({workflow})",
            holder=holder,
        )

    def fail_marker_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("marker fsync failed")

    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.acquire_operational_lease",
        fake_acquire,
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.release_operational_lease",
        lambda policy: released.append(dict(policy)),
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.write_json_marker_atomic",
        fail_marker_write,
    )

    work_dir = tmp_path / "work"
    with pytest.raises(ConditionWorkspaceError) as excinfo:
        acquire_condition_workspace(
            project="sase",
            request_id="req",
            plan_digest="d" * 64,
            logical_id="unit-1",
            work_dir=work_dir,
        )

    assert isinstance(excinfo.value.__cause__, OSError)
    assert "marker persistence failed" in str(excinfo.value)
    assert len(released) == 1
    assert released[0]["workflow"].startswith("lease(launch-if:")
    assert not (work_dir / CONDITION_WORKSPACE_MARKER).exists()
