"""Condition-scoped workspace leases for typed launch admission."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_condition_workspace import (
    CONDITION_WORKSPACE_MARKER,
    ConditionWorkspaceUnavailable,
    acquire_condition_workspace,
    settle_condition_workspace,
)
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchConditionWire,
    LaunchPlanWire,
    LaunchUnitWire,
    agent_launch_wire_to_json_dict,
)
from sase.workspace_provider.lease import OperationalLeaseError
from sase.xprompt.code_value import CodeValue
from tests.workspace_lease_helpers import fake_operational_lease


def _code(source: str = "exit 0") -> CodeValue:
    return CodeValue(
        source=source,
        language="bash",
        info_string=None,
        digest="c" * 64,
        preview=source,
    )


def _unit() -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id="unit-1",
        source_order=0,
        payload=AgentUnitWire(prompt="Do work", identity="reviewer"),
        condition=LaunchConditionWire(code=_code()),
    )


def _plan() -> LaunchPlanWire:
    return LaunchPlanWire(
        schema_version=1,
        launch_kind="multi_prompt",
        selected_project="sase",
        content_digest="d" * 64,
        units=[_unit()],
        approval_preview=["LaunchPlan v1"],
    )


def _run_plan(tmp_path: Path) -> Any:
    response_dir = tmp_path / "bundle"
    response_dir.mkdir(exist_ok=True)
    stale = tmp_path / "stale"
    stale.mkdir(exist_ok=True)
    result = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-cond-ws",
            "typed_plan": agent_launch_wire_to_json_dict(_plan()),
            "dispatch": {"cwd": str(stale), "prompt": "Do work"},
        },
        spawn_coordinator=False,
        agent_dispatcher=lambda unit, fingerprint: pytest.fail(
            "skipped condition should not dispatch"
        ),
    )
    return result, response_dir


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


def test_project_condition_runs_in_leased_checkout_and_releases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    stale = tmp_path / "stale"
    stale.mkdir()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    observed: dict[str, Any] = {}
    released: list[dict[str, Any]] = []

    def fake_acquire(
        project: str,
        *,
        workflow: str,
        holder: str,
        **_kwargs: object,
    ) -> Any:
        observed["workflow"] = workflow
        return fake_operational_lease(
            checkout,
            project=project,
            workflow=f"lease({workflow})",
            holder=holder,
        )

    def fake_supervise(
        request: dict[str, Any], work_dir: Path, context: Any
    ) -> tuple[str, str | None]:
        del work_dir, context
        observed["cwd"] = request["cwd"]
        return "skipped", "predicate exited 1"

    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.acquire_operational_lease",
        fake_acquire,
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.release_operational_lease",
        lambda policy: released.append(dict(policy)),
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_runtime._supervise_request",
        fake_supervise,
    )

    progress, response_dir = _run_plan(tmp_path)

    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.skipped == 1
    assert observed["cwd"] == str(checkout)
    assert observed["workflow"].startswith("launch-if:req-cond-ws:unit-1:")
    assert len(released) == 1
    marker = json.loads(
        (
            response_dir
            / "launch_admission"
            / "units"
            / "unit-1"
            / CONDITION_WORKSPACE_MARKER
        ).read_text(encoding="utf-8")
    )
    assert marker["settled"] is True


def test_workspace_contention_leaves_admission_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")

    def fake_acquire(*_args: object, **_kwargs: object) -> Any:
        raise OperationalLeaseError("allocation", "all workspaces are claimed")

    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.acquire_operational_lease",
        fake_acquire,
    )

    progress, response_dir = _run_plan(tmp_path)

    assert not progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.skipped == 0
    journal = (response_dir / "launch_admission" / "journal.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"phase": "checking"' not in journal
    assert '"phase": "condition_error"' not in journal


def test_workspace_preparation_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    evaluated = False

    def fake_acquire(*_args: object, **_kwargs: object) -> Any:
        raise OperationalLeaseError("preparation", "git fetch failed")

    def fake_supervise(*_args: object, **_kwargs: object) -> tuple[str, str | None]:
        nonlocal evaluated
        evaluated = True
        return "eligible", None

    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.acquire_operational_lease",
        fake_acquire,
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_runtime._supervise_request",
        fake_supervise,
    )

    progress, response_dir = _run_plan(tmp_path)

    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.condition_errors == 1
    assert evaluated is False
    receipt = json.loads(
        (response_dir / "launch_admission" / "receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["units"][0]["outcome"] == "condition_error"
    assert "preparation" in receipt["units"][0]["message"]
