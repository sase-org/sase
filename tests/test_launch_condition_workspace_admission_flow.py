"""Condition workspace behavior during successful launch admission paths."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_condition_workspace import CONDITION_WORKSPACE_MARKER
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchConditionWire,
    LaunchUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
)
from tests._launch_condition_workspace_helpers import (
    _code,
    _git,
    _init_git,
    _plan,
    _run_plan,
    _unit,
)
from tests.workspace_lease_helpers import fake_operational_lease


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
