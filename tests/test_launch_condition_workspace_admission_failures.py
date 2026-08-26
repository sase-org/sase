"""Condition workspace failure handling during launch admission."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_condition_workspace import (
    CONDITION_WORKSPACE_MARKER,
    acquire_condition_workspace,
)
from sase.core.agent_launch_wire import agent_launch_wire_to_json_dict
from sase.workspace_provider.lease import OperationalLeaseError
from tests._launch_condition_workspace_helpers import _plan, _run_plan, _unit
from tests.workspace_lease_helpers import fake_operational_lease


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


def test_marker_write_failure_fails_closed_without_evaluating_condition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    released: list[dict[str, Any]] = []
    evaluated = False

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

    def fake_supervise(*_args: object, **_kwargs: object) -> tuple[str, str | None]:
        nonlocal evaluated
        evaluated = True
        return "eligible", None

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
    monkeypatch.setattr(
        "sase.agent.launch_condition_runtime._supervise_request",
        fake_supervise,
    )

    progress, response_dir = _run_plan(tmp_path)

    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.condition_errors == 1
    assert evaluated is False
    assert len(released) == 1
    work_dir = response_dir / "launch_admission" / "units" / "unit-1"
    assert not (work_dir / CONDITION_WORKSPACE_MARKER).exists()
    journal = (response_dir / "launch_admission" / "journal.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"phase": "checking"' not in journal
    assert '"phase": "condition_error"' in journal
    receipt = json.loads(
        (response_dir / "launch_admission" / "receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["units"][0]["outcome"] == "condition_error"
    assert "marker persistence failed" in receipt["units"][0]["message"]


def test_evaluator_exception_releases_condition_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
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

    def broken_supervise(*_args: object, **_kwargs: object) -> tuple[str, str | None]:
        raise RuntimeError("boom")

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
        broken_supervise,
    )

    progress, response_dir = _run_plan(tmp_path)

    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.condition_errors == 1
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


def test_cancelled_condition_releases_condition_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    released: list[dict[str, Any]] = []
    lease_acquired = False

    def fake_acquire(
        project: str,
        *,
        workflow: str,
        holder: str,
        **_kwargs: object,
    ) -> Any:
        nonlocal lease_acquired
        lease_acquired = True
        return fake_operational_lease(
            checkout,
            project=project,
            workflow=f"lease({workflow})",
            holder=holder,
        )

    def cancelled() -> bool:
        return lease_acquired

    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.acquire_operational_lease",
        fake_acquire,
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.release_operational_lease",
        lambda policy: released.append(dict(policy)),
    )

    response_dir = tmp_path / "bundle-cancel"
    response_dir.mkdir()
    progress = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-cancel-condition",
            "typed_plan": agent_launch_wire_to_json_dict(_plan(_unit("sleep 30"))),
            "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
        },
        spawn_coordinator=False,
        cancelled=cancelled,
        agent_dispatcher=lambda unit, fingerprint: pytest.fail(
            "cancelled condition should not dispatch"
        ),
    )

    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.condition_errors + progress.summary.launch_errors == 1
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


def test_replayed_condition_result_releases_unsettled_condition_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
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

    launch_plan = _plan()
    response_dir = tmp_path / "bundle-replay"
    work_dir = response_dir / "launch_admission" / "units" / "unit-1"
    work_dir.mkdir(parents=True)
    acquire_condition_workspace(
        project="sase",
        request_id="req-replay-condition",
        plan_digest=launch_plan.content_digest,
        logical_id="unit-1",
        work_dir=work_dir,
    )
    (response_dir / "launch_admission" / "journal.jsonl").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "seq": 1,
                "logical_id": "unit-1",
                "phase": "checking",
                "recorded_at_unix": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (work_dir / "result.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "verdict": "eligible",
                "timed_out": False,
                "truncated": False,
                "cancelled": False,
                "code_digest": launch_plan.units[0].condition.code.digest,
                "context_digest": "b" * 64,
                "message": None,
            }
        ),
        encoding="utf-8",
    )

    progress = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-replay-condition",
            "typed_plan": agent_launch_wire_to_json_dict(launch_plan),
            "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
        },
        spawn_coordinator=False,
        agent_dispatcher=lambda unit, fingerprint: (
            True,
            unit.logical_id,
            None,
            [],
        ),
    )

    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert len(released) == 1
    marker = json.loads((work_dir / CONDITION_WORKSPACE_MARKER).read_text("utf-8"))
    assert marker["settled"] is True
