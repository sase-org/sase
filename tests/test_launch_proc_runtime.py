"""Native stand-alone `%proc` dispatch and supervisor preparation."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_proc_runtime import dispatch_proc_unit
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import (
    parse_proc_duration_seconds,
    resolve_proc_execution_cwd,
    sanitized_proc_env,
    validate_proc_workspace_intent,
    validate_standalone_proc_shell_name,
    xprompt_proc_origin,
)
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchPlanWire,
    LaunchUnitWire,
    ProcUnitWire,
    WaitTargetWire,
    agent_launch_wire_to_json_dict,
)
from sase.procs import wait_for_proc
from sase.procs.runtime import proc_runtime_dir
from sase.xprompt.code_value import make_code_value


def _plan(*units: LaunchUnitWire, project: str | None = None) -> LaunchPlanWire:
    return LaunchPlanWire(
        schema_version=1,
        launch_kind="multi_prompt",
        selected_project=project,
        content_digest="d" * 64,
        units=list(units),
        approval_preview=["LaunchPlan v1"],
    )


def _run_plan(tmp_path: Path, plan: LaunchPlanWire, **kwargs: Any) -> Any:
    response_dir = tmp_path / "bundle"
    response_dir.mkdir(exist_ok=True)
    result = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "req-proc",
            "typed_plan": agent_launch_wire_to_json_dict(plan),
            "dispatch": {"cwd": str(tmp_path), "prompt": "%proc"},
        },
        spawn_coordinator=False,
        **kwargs,
    )
    return result, response_dir


def _proc_unit(
    source: str,
    *,
    language: str = "bash",
    workspace: bool = False,
    cwd: str | None = None,
    shell_name: str | None = None,
    label: str | None = None,
    timeout: str | None = None,
    logical_id: str = "unit-1",
    selected_project: str | None = None,
) -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id=logical_id,
        source_order=0,
        payload=ProcUnitWire(
            code=make_code_value(source, language, language),
            workspace=workspace,
            cwd=cwd,
            shell_name=shell_name,
            label=label,
            timeout=timeout,
            selected_project=selected_project,
        ),
    )


def test_rust_helpers_cover_workspace_cwd_and_env_contracts(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    nested = tmp_path / "src"
    nested.mkdir()
    assert resolve_proc_execution_cwd(
        True, declared_cwd="src", lease_root=str(tmp_path)
    ) == str(nested.resolve())
    with pytest.raises(ValueError, match="escapes"):
        resolve_proc_execution_cwd(True, declared_cwd="..", lease_root=str(tmp_path))
    outside = tmp_path / "outside"
    outside.mkdir()
    lease = tmp_path / "lease"
    lease.mkdir()
    os.symlink(outside, lease / "escape")
    with pytest.raises(ValueError, match="escapes"):
        resolve_proc_execution_cwd(True, declared_cwd="escape", lease_root=str(lease))
    with pytest.raises(ValueError, match="selected project"):
        validate_proc_workspace_intent(True, None, str(tmp_path))
    with pytest.raises(ValueError, match="ordinary cwd"):
        validate_proc_workspace_intent(False, "sase", None)
    validate_standalone_proc_shell_name("checks")
    with pytest.raises(ValueError, match="`--`"):
        validate_standalone_proc_shell_name("agent--checks")
    assert parse_proc_duration_seconds("20m") == 1200
    env = sanitized_proc_env(
        "proc-one",
        str(tmp_path),
        str(tmp_path),
        sys.executable,
        selected_project="sase",
        project_file="/tmp/sase.sase",
        workspace_num=12,
    )
    assert env["SASE_PROC_ID"] == "proc-one"
    assert env["SASE_PROJECT"] == "sase"
    assert "SASE_AGENT" not in env
    assert xprompt_proc_origin() == "xprompt-proc"


def test_bash_proc_runs_without_agent_artifacts(
    monkeypatch: Any, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    marker = tmp_path / "ran.txt"
    unit = _proc_unit(
        f"printf ready > {marker}\nprintf env=$SASE_AGENT.\\n",
        cwd=str(tmp_path),
        shell_name="checks",
    )
    ok, identity, message, spawned = dispatch_proc_unit(
        unit,
        "fp-bash",
        {"source_cwd": str(tmp_path), "python_executable": sys.executable},
    )
    assert ok, message
    assert spawned == []
    assert identity is not None
    finished = wait_for_proc(identity, timeout=10)
    assert finished.status == "success"
    assert finished.origin == "xprompt-proc"
    assert finished.lifecycle == "proc-shell"
    assert finished.shell_name == "checks"
    assert finished.xprompt_proc is not None
    assert finished.xprompt_proc["code_language"] == "bash"
    assert marker.read_text(encoding="utf-8") == "ready"
    assert not (proc_runtime_dir(finished.proc_id) / "script.sh").exists()
    artifacts = tmp_path / "home" / "projects"
    assert not any(artifacts.rglob("done.json")) if artifacts.exists() else True


def test_proc_metadata_preserves_label_provenance_through_prepare(
    monkeypatch: Any, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    unit = _proc_unit(
        "printf ready\n",
        cwd=str(tmp_path),
        shell_name="checks",
        label="Verify docs",
    )

    ok, identity, message, _spawned = dispatch_proc_unit(
        unit,
        "fp-label",
        {"source_cwd": str(tmp_path), "python_executable": sys.executable},
    )

    assert ok, message
    assert identity is not None
    from sase.procs.store import get_proc

    submitted = get_proc(identity)
    assert submitted is not None
    assert submitted.xprompt_proc is not None
    assert submitted.xprompt_proc["label"] == "Verify docs"
    assert submitted.xprompt_proc["shell_name"] == "checks"

    finished = wait_for_proc(identity, timeout=10)
    assert finished.status == "success"
    assert finished.xprompt_proc is not None
    assert finished.xprompt_proc["label"] == "Verify docs"
    assert finished.xprompt_proc["shell_name"] == "checks"
    assert finished.xprompt_proc["code_digest"]


def test_python_proc_uses_sase_interpreter(monkeypatch: Any, tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    marker = tmp_path / "py.txt"
    source = (
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text(sys.executable)\n"
    )
    unit = _proc_unit(source, language="python", cwd=str(tmp_path))
    ok, identity, message, _spawned = dispatch_proc_unit(
        unit,
        "fp-python",
        {"source_cwd": str(tmp_path), "python_executable": sys.executable},
    )
    assert ok, message
    assert identity is not None
    finished = wait_for_proc(identity, timeout=10)
    assert finished.status == "success"
    assert marker.read_text(encoding="utf-8") == sys.executable


def test_admission_launches_proc_and_mixed_wait_order(
    monkeypatch: Any, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    marker = tmp_path / "mixed.txt"
    agent = LaunchUnitWire(
        logical_id="unit-1",
        source_order=0,
        payload=AgentUnitWire(prompt="review"),
    )
    proc = LaunchUnitWire(
        logical_id="unit-2",
        source_order=1,
        waits=[WaitTargetWire(kind="logical", logical_id="unit-1")],
        payload=ProcUnitWire(
            code=make_code_value(f"printf mixed > {marker}", "bash", "bash"),
            workspace=False,
            cwd=str(tmp_path),
        ),
    )

    def agent_dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        del fingerprint
        return (
            True,
            "reviewer",
            None,
            [
                AgentLaunchResult(
                    pid=9,
                    workspace_num=2,
                    workspace_dir=str(tmp_path / "ws"),
                    output_path=str(tmp_path / "out.log"),
                    agent_name=unit.logical_id,
                )
            ],
        )

    progress, response_dir = _run_plan(
        tmp_path,
        _plan(agent, proc, project="sase"),
        agent_dispatcher=agent_dispatcher,
    )
    assert progress.summary is not None
    assert progress.summary.launched == 2
    outcomes = {item.logical_id: item.outcome for item in progress.unit_results}
    assert outcomes == {"unit-1": "launched", "unit-2": "launched"}
    from sase.procs.store import read_procs

    rows = [row for row in read_procs() if row.origin == "xprompt-proc"]
    assert len(rows) == 1
    finished = wait_for_proc(rows[0].proc_id, timeout=10)
    assert finished.status == "success"
    assert marker.read_text(encoding="utf-8") == "mixed"
    receipt = (response_dir / "launch_admission" / "units" / "unit-2.json").read_text(
        encoding="utf-8"
    )
    assert rows[0].proc_id in receipt


def test_duplicate_fingerprint_does_not_spawn_a_second_child(
    monkeypatch: Any, tmp_path: Path
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    unit = _proc_unit("sleep 2", cwd=str(tmp_path), shell_name="once")
    context = {"source_cwd": str(tmp_path), "python_executable": sys.executable}
    ok1, first, message1, _spawned = dispatch_proc_unit(unit, "fp-once", context)
    assert ok1, message1
    ok2, second, message2, _spawned = dispatch_proc_unit(unit, "fp-once", context)
    assert ok2, message2
    assert first == second
    assert first is not None
    wait_for_proc(first, timeout=10)


def test_timeout_settles_without_agent_slots(monkeypatch: Any, tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    unit = _proc_unit("sleep 8", cwd=str(tmp_path), timeout="1s")
    ok, identity, message, spawned = dispatch_proc_unit(
        unit,
        "fp-timeout",
        {"source_cwd": str(tmp_path), "python_executable": sys.executable},
    )
    assert ok, message
    assert spawned == []
    assert identity is not None
    finished = wait_for_proc(identity, timeout=10)
    assert finished.status == "error"
    assert finished.origin == "xprompt-proc"


def test_prepared_script_mode_is_private(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    from sase.core.agent_launch_facade import prepare_proc_script
    from sase.xprompt.code_value import make_code_value

    work = tmp_path / "work"
    work.mkdir()
    code = make_code_value("echo ready", "bash", "bash")
    prepared = prepare_proc_script(
        {
            "schema_version": 1,
            "logical_id": "unit-1",
            "fingerprint": "fp",
            "code": {
                "schema_version": 1,
                "source": code.source,
                "language": code.language,
                "digest": code.digest,
                "preview": code.preview,
            },
            "work_dir": str(work),
            "python_executable": sys.executable,
            "workspace": False,
            "declared_cwd": str(tmp_path),
            "source_cwd": str(tmp_path),
            "proc_id": "proc-mode",
        }
    )
    mode = stat.S_IMODE(Path(str(prepared["script_path"])).stat().st_mode)
    assert mode == 0o600
    assert prepared["argv"][:3] == ["/bin/bash", "--noprofile", "--norc"]
