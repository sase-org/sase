"""Combined approval-to-launch lifecycle regression for sase-s2.2.

This test stitches plan approval into the swap-safe epic launcher
(sase-s2.2) journey and reproduces the historical fail-fast failure that fix
replaced. The host-owned plan archive (sase-s2.1) journeys live in
test_plan_approval_launch_reliability_integration.py.
"""

from __future__ import annotations

import json
import subprocess
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.axe.agent_meta import write_agent_meta_atomic
from sase.bead.epic_launch import build_epic_launch_argv, start_epic_launch_monitor
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BeadProject
from sase.dev_update.code_swap_lock import (
    code_swap_writer_lock,
    guarded_exec_argv,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.plan_gate import create_plan_approval_gate
from tests._plan_gate_fixtures import (  # noqa: F401
    plan_gate_home,
    write_plan,
)
from tests.plan_approval_launch_reliability_test_helpers import (
    WAITING_NEEDLE,
    create_one_epic_dag,
    install_fake_sase,
    readline_until,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution
from tests.workspace_lease_helpers import fake_operational_lease


@pytest.mark.parametrize("start_order", ["writer_first", "launch_first"])
def test_epic_approval_during_code_swap_creates_one_dag(
    tmp_path: Path,
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    start_order: str,
) -> None:
    checkout = tmp_path / "bead-project"
    with BeadProject.init(checkout):
        pass
    isolate_bead_store_resolution(monkeypatch, checkout)
    plan = checkout / "incoming" / "rollout.md"
    plan.parent.mkdir()
    plan.write_text(EPIC_PLAN, encoding="utf-8")
    gate_plan = write_plan(gate_home, "rollout.md", VALID_EPIC_PLAN)
    gate = create_plan_approval_gate(gate_plan, f"epic-{start_order}")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    write_agent_meta_atomic(
        artifacts,
        {"name": "planner", "agent_family": "planner", "status": "running"},
        index_updater=lambda _path: None,
    )
    marker = install_fake_sase(tmp_path, monkeypatch)
    captured: dict[str, Any] = {}
    lease = fake_operational_lease(
        tmp_path / "leased",
        primary_checkout=checkout,
    )

    def fake_start_monitor(request: object) -> object:
        captured["request"] = request
        proc = subprocess.Popen(
            list(request.execution_argv),  # type: ignore[attr-defined]
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        captured["proc"] = proc
        return SimpleNamespace(
            monitor_id="m7k2xyz",
            monitor_state="running",
            command=request.command,  # type: ignore[attr-defined]
        )

    def prepare_launch(*_args: object, **_kwargs: object) -> object:
        return start_epic_launch_monitor(
            plan,
            project="sase",
            host_action_data={"agent_name": "planner"},
            artifacts_dir=artifacts,
        )

    patches = ExitStack()
    patches.enter_context(
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks")
    )
    patches.enter_context(patch("sase.procs.read_procs", return_value=[]))
    patches.enter_context(
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            return_value=lease,
        )
    )
    patches.enter_context(
        patch("sase.workspace_provider.lease.release_operational_lease")
    )
    patches.enter_context(
        patch("sase.monitor.start.start_monitor", side_effect=fake_start_monitor)
    )
    patches.enter_context(
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            side_effect=prepare_launch,
        )
    )

    def approve() -> object:
        return execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            {"epic_launch_mode": "launch"},
        )

    with patches:
        if start_order == "writer_first":
            with code_swap_writer_lock() as writer:
                assert writer.acquired is True
                execution = approve()
                proc = captured["proc"]
                assert isinstance(proc, subprocess.Popen)
                try:
                    line = readline_until(proc, WAITING_NEEDLE, timeout=5.0)
                    assert line is not None
                    assert proc.poll() is None
                    assert not marker.exists()
                    assert gate.response_path.exists()
                    with BeadProject(checkout) as project:
                        assert project.list_issues() == []
                except BaseException:
                    proc.kill()
                    proc.wait(timeout=5)
                    raise
            assert proc.wait(timeout=10) == 0
        else:
            execution = approve()
            proc = captured["proc"]
            assert isinstance(proc, subprocess.Popen)
            assert proc.wait(timeout=10) == 0
            assert gate.response_path.exists()

    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload[1:4] == ["bead", "work", str(plan)]
    request = captured["request"]
    logical = build_epic_launch_argv(plan, artifacts_dir=artifacts)
    assert list(request.execution_argv) == guarded_exec_argv(  # type: ignore[attr-defined]
        logical
    )
    assert execution.response["kind"] == "epic_plan"
    epic_id = create_one_epic_dag(plan, monkeypatch)
    with BeadProject(checkout) as project:
        epic = project.show(epic_id)
        children = project.get_epic_children(epic.id)
        assert epic.tier is BeadTier.EPIC
        assert len(children) == 3
        assert all(issue.issue_type is IssueType.PHASE for issue in children)
        assert len(project.list_issues()) == 4
