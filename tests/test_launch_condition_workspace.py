"""Condition-scoped workspace leases for typed launch admission."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_condition_workspace import (
    CONDITION_WORKSPACE_MARKER,
    ConditionWorkspaceError,
    ConditionWorkspaceUnavailable,
    acquire_condition_workspace,
    settle_condition_workspace,
)
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchConditionWire,
    LaunchPlanWire,
    LaunchUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
)
from sase.workspace_provider.lease import OperationalLeaseError
from sase.xprompt.code_value import CodeValue, make_code_value
from tests.workspace_lease_helpers import fake_operational_lease


def _code(source: str = "exit 0") -> CodeValue:
    return make_code_value(source, "bash", "bash")


def _unit(source: str = "exit 0") -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id="unit-1",
        source_order=0,
        payload=AgentUnitWire(prompt="Do work", identity="reviewer"),
        condition=LaunchConditionWire(code=_code(source)),
    )


def _plan(
    *units: LaunchUnitWire,
    selected_project: str | None = "sase",
) -> LaunchPlanWire:
    return LaunchPlanWire(
        schema_version=1,
        launch_kind="multi_prompt",
        selected_project=selected_project,
        content_digest="d" * 64,
        units=list(units or [_unit()]),
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
        marker = json.loads(
            (work_dir / CONDITION_WORKSPACE_MARKER).read_text(encoding="utf-8")
        )
        assert marker["settled"] is False
        assert context["condition_workspace_num"] == 10
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


def test_condition_lease_starts_only_after_logical_wait_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    events: list[str] = []
    response_dir = tmp_path / "bundle-waited"
    response_dir.mkdir()
    launch_plan = _plan(
        LaunchUnitWire(
            logical_id="unit-1",
            source_order=0,
            payload=AgentUnitWire(prompt="First", identity="first"),
        ),
        LaunchUnitWire(
            logical_id="unit-2",
            source_order=1,
            payload=AgentUnitWire(prompt="Later", identity="later"),
            waits=[WaitTargetWire(kind="logical", logical_id="unit-1", source="%wait")],
            condition=LaunchConditionWire(code=_code("exit 1")),
        ),
    )

    def fake_acquire(
        project: str,
        *,
        workflow: str,
        holder: str,
        **_kwargs: object,
    ) -> Any:
        _prefix, _request, logical_id, _digest = workflow.split(":", 3)
        events.append(f"lease:{logical_id}")
        return fake_operational_lease(
            checkout,
            project=project,
            workflow=f"lease({workflow})",
            holder=holder,
        )

    def fake_supervise(
        request: dict[str, Any], _work_dir: Path, _context: Any
    ) -> tuple[str, str | None]:
        events.append(f"check:{request['logical_id']}")
        return "skipped", "predicate exited 1"

    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.acquire_operational_lease",
        fake_acquire,
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.release_operational_lease",
        lambda _policy: None,
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_runtime._supervise_request",
        fake_supervise,
    )

    def dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str | None, str | None, list[Any]]:
        del fingerprint
        events.append(f"dispatch:{unit.logical_id}")
        return True, unit.logical_id, None, []

    progress = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-waited-condition",
            "typed_plan": agent_launch_wire_to_json_dict(launch_plan),
            "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
        },
        spawn_coordinator=False,
        agent_dispatcher=dispatcher,
    )

    assert progress.admission_complete
    assert events == [
        "dispatch:unit-1",
        "lease:unit-2",
        "check:unit-2",
    ]


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


def test_home_condition_uses_explicit_source_cwd_without_condition_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    source = tmp_path / "home-source"
    source.mkdir()
    observed: dict[str, Any] = {}

    def unexpected_acquire(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("unmanaged condition should not lease a workspace")

    def fake_supervise(
        request: dict[str, Any], _work_dir: Path, _context: Any
    ) -> tuple[str, str | None]:
        observed["cwd"] = request["cwd"]
        return "skipped", "predicate exited 1"

    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.acquire_operational_lease",
        unexpected_acquire,
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_runtime._supervise_request",
        fake_supervise,
    )

    response_dir = tmp_path / "bundle-home"
    response_dir.mkdir()
    progress = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-home-condition",
            "typed_plan": agent_launch_wire_to_json_dict(
                _plan(_unit("exit 1"), selected_project=None)
            ),
            "dispatch": {"cwd": str(source), "prompt": "Do work"},
        },
        spawn_coordinator=False,
        agent_dispatcher=lambda unit, fingerprint: pytest.fail(
            "skipped condition should not dispatch"
        ),
    )

    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.skipped == 1
    assert observed["cwd"] == str(source)


def test_runner_wait_stays_on_agent_after_temporary_condition_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    dispatched: list[int | None] = []

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
        lambda _policy: None,
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_runtime._supervise_request",
        lambda request, work_dir, context: ("eligible", None),
    )

    unit = LaunchUnitWire(
        logical_id="unit-1",
        source_order=0,
        payload=AgentUnitWire(
            prompt="Do work",
            identity="reviewer",
            wait_runners=2,
            wait_priority=4,
        ),
        condition=LaunchConditionWire(code=_code("exit 0")),
    )
    response_dir = tmp_path / "bundle-runner-wait"
    response_dir.mkdir()
    progress = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-runner-wait",
            "typed_plan": agent_launch_wire_to_json_dict(_plan(unit)),
            "dispatch": {"cwd": str(tmp_path), "prompt": "Do work"},
        },
        spawn_coordinator=False,
        agent_dispatcher=lambda dispatched_unit, fingerprint: (
            dispatched.append(dispatched_unit.payload.wait_runners),
            (True, dispatched_unit.logical_id, None, []),
        )[1],
    )

    assert progress.admission_complete
    assert dispatched == [2]


def test_stale_source_checkout_skips_after_prepared_lease_sees_upstream(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    writer = tmp_path / "writer"
    writer.mkdir()
    _init_git(writer)
    target = writer / "target.py"
    target.write_text("print('line 1')\nprint('line 2')\n", encoding="utf-8")
    _git(writer, "add", "target.py")
    _git(writer, "commit", "-qm", "oversized")
    _git(writer, "branch", "-M", "main")
    _git(writer, "remote", "add", "origin", str(remote))
    _git(writer, "push", "-u", "origin", "main")
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
        cwd=remote,
        check=True,
    )

    source = tmp_path / "source"
    subprocess.run(["git", "clone", "-q", str(remote), str(source)], check=True)
    target.write_text("print('line 1')\n", encoding="utf-8")
    _git(writer, "add", "target.py")
    _git(writer, "commit", "-qm", "split")
    _git(writer, "push", "origin", "main")
    assert (source / "target.py").read_text(encoding="utf-8").count("\n") == 2

    project_file = tmp_path / "demo.sase"
    project_file.write_text(
        f"WORKSPACE_DIR: {source}\nRUNNING:\n\nNAME: demo\n",
        encoding="utf-8",
    )
    dispatched: list[str] = []
    response_dir = tmp_path / "bundle-stale"
    response_dir.mkdir()

    progress = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-stale-source",
            "project_file": str(project_file),
            "typed_plan": agent_launch_wire_to_json_dict(
                _plan(_unit("test $(wc -l < target.py) -gt 1"), selected_project="demo")
            ),
            "dispatch": {"cwd": str(source), "prompt": "Do work"},
        },
        spawn_coordinator=False,
        agent_dispatcher=lambda unit, fingerprint: (
            dispatched.append(unit.logical_id),
            (True, unit.logical_id, None, []),
        )[1],
    )

    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.skipped == 1
    assert dispatched == []
    assert "RUNNING" not in project_file.read_text(encoding="utf-8")
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
    leased_target = Path(marker["checkout_dir"]) / "target.py"
    assert leased_target.read_text(encoding="utf-8").count("\n") == 1


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True)
