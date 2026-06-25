"""Regression tests for the wait_checks chop script."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_wait_checks as wait_checks_module
from sase.axe.chop_script_context import ChopScriptContext, write_chop_context
from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependencies_resolved,
)
from sase.scripts.sase_chop_wait_checks import main as wait_checks_main

from tests._agent_names_fixtures import make_agent


def _write_context(tmp_path: Path) -> Path:
    path = tmp_path / "context.json"
    write_chop_context(
        ChopScriptContext(
            max_hook_runners=3,
            max_agent_runners=3,
            zombie_timeout_seconds=600,
            query="status:Ready",
            lumberjack_name="wait_checks",
            state_dir=str(tmp_path / "state"),
            all_changespecs_file=str(tmp_path / "all.json"),
            filtered_changespecs_file=str(tmp_path / "filtered.json"),
        ),
        str(path),
    )
    return path


def _make_waiting_agent(base: Path, *waiting_for: str, suffix: str = "waiter") -> Path:
    artifact_dir = base / ".sase/projects/proj/artifacts/ace-run" / suffix
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": list(waiting_for),
                "cl_name": "waiter-cl",
                "timestamp": "waiter",
            }
        ),
        encoding="utf-8",
    )
    return artifact_dir


def _make_submitted_planner(
    base: Path,
    timestamp: str,
    name: str,
    *,
    plan_path: str | None = "sdd/tales/202606/example.md",
    role_suffix: str = "--plan",
    write_plan_path_json: bool = True,
    promoted: bool = True,
) -> Path:
    """Create a submitted-and-waiting planner artifact (no done.json)."""
    artifact_dir = make_agent(
        base,
        "proj",
        timestamp,
        name,
        workflow_name=name if promoted else None,
        agent_family=name if promoted else None,
        role_suffix=role_suffix,
    )
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["plan"] = True
    meta["plan_submitted_at"] = ["2026-06-25T18:47:16+00:00"]
    if plan_path is not None:
        meta["plan_path"] = plan_path
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    if write_plan_path_json and plan_path is not None:
        (artifact_dir / "plan_path.json").write_text(
            json.dumps({"plan_path": plan_path}), encoding="utf-8"
        )
    return artifact_dir


def _write_workflow_state(
    artifact_dir: Path,
    *,
    status: str = "completed",
    step_status: str = "completed",
    marker_status: str = "completed",
) -> None:
    (artifact_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "status": status,
                "current_step_index": 0,
                "steps": [
                    {
                        "name": "main",
                        "status": step_status,
                        "error": None,
                        "traceback": None,
                    }
                ],
                "appears_as_agent": True,
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "prompt_step_main.json").write_text(
        json.dumps(
            {
                "step_name": "main",
                "status": marker_status,
                "error": None,
                "traceback": None,
            }
        ),
        encoding="utf-8",
    )


def _run_wait_checks(tmp_path: Path, monkeypatch) -> None:
    context_path = _write_context(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["sase_chop_wait_checks", "--context", str(context_path)],
    )
    wait_checks_main()


def test_named_agent_killed_newest_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "foo")
    make_agent(tmp_path, "proj", "20260506010101", "foo", done=True)
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "foo",
        done=True,
        outcome="killed",
    )

    _run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_later_same_name_completed_agent_resolves_after_killed(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="killed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "foo",
        done=True,
        outcome="completed",
    )

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}


def test_repeat_stopped_completed_marker_resolves_downstream_wait(
    tmp_path: Path, monkeypatch
) -> None:
    """A repeat-stopped slot still reports `completed`, so the cascade is generic.

    The next downstream waiter must resolve off the stopped predecessor exactly
    like any other completed producer -- the chop never inspects `repeat_stopped`.
    """
    waiter_dir = _make_waiting_agent(tmp_path, "foo.2")
    producer_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo.2",
        done=True,
        outcome="completed",
    )
    # Mark the predecessor as a repeat-stopped slot, as the runner would.
    done = json.loads((producer_dir / "done.json").read_text(encoding="utf-8"))
    done.update({"repeat_stopped": True, "stopped_by": "foo.1"})
    (producer_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo.2"]}


def test_failed_workflow_name_dependency_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "wf")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="failed",
    )

    _run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_successful_workflow_name_dependency_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "wf")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "wf.2",
        workflow_name="wf",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["wf"]}


def test_shared_resolver_matches_wait_checks_workflow_fixture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "wf")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "wf.2",
        workflow_name="wf",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )
    assert dependencies_resolved(index, ["wf"])

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["wf"]}


def test_successful_plan_family_dependency_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "planfam")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="-plan",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "planfam-code",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="-code",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planfam"]}


def test_completed_plan_chain_handoff_without_done_resolves_family_dependency(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "33.r1")
    make_agent(
        tmp_path,
        "proj",
        "20260606094012",
        "33.r1",
        workflow_name="33.r1",
        agent_family="33.r1",
        done=True,
        outcome="completed",
    )
    feedback_dir = make_agent(
        tmp_path,
        "proj",
        "20260606095139",
        "33.r1--2",
        workflow_name="33.r1",
        agent_family="33.r1",
        role_suffix="--2",
        parent_timestamp="20260606094012",
    )
    _write_workflow_state(feedback_dir)
    make_agent(
        tmp_path,
        "proj",
        "20260606100411",
        "33.r1--code",
        workflow_name="33.r1",
        agent_family="33.r1",
        role_suffix="--code",
        parent_timestamp="20260606094012",
        done=True,
        outcome="completed",
    )

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["33.r1"]}


def test_completed_plan_root_handoff_without_done_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    # A `--plan` root that merely completed its handoff (completed
    # workflow_state.json, no terminal done.json anywhere in the family) must
    # not resolve the wait barrier: the plan chain is still in flight.
    waiter_dir = _make_waiting_agent(tmp_path, "3j")
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260607083133",
        "3j",
        workflow_name="3j",
        agent_family="3j",
        role_suffix="--plan",
    )
    _write_workflow_state(root_dir)

    _run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize("outcome", ["failed", "killed"])
def test_failed_or_killed_plan_chain_handoff_done_blocks_family_dependency(
    tmp_path: Path, monkeypatch, outcome: str
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "planfam")
    make_agent(
        tmp_path,
        "proj",
        "20260606094012",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        done=True,
        outcome="completed",
    )
    feedback_dir = make_agent(
        tmp_path,
        "proj",
        "20260606095139",
        "planfam--2",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--2",
        parent_timestamp="20260606094012",
        done=True,
        outcome=outcome,
    )
    _write_workflow_state(feedback_dir)
    make_agent(
        tmp_path,
        "proj",
        "20260606100411",
        "planfam--code",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--code",
        parent_timestamp="20260606094012",
        done=True,
        outcome="completed",
    )

    _run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize(
    ("workflow_status", "step_status", "marker_status"),
    [
        ("running", "completed", "completed"),
        ("completed", "in_progress", "in_progress"),
    ],
)
def test_incomplete_plan_chain_handoff_blocks_family_dependency(
    tmp_path: Path,
    monkeypatch,
    workflow_status: str,
    step_status: str,
    marker_status: str,
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "planfam")
    make_agent(
        tmp_path,
        "proj",
        "20260606094012",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        done=True,
        outcome="completed",
    )
    feedback_dir = make_agent(
        tmp_path,
        "proj",
        "20260606095139",
        "planfam--2",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--2",
        parent_timestamp="20260606094012",
    )
    _write_workflow_state(
        feedback_dir,
        status=workflow_status,
        step_status=step_status,
        marker_status=marker_status,
    )

    _run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_failed_latest_plan_family_child_blocks_dependency(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "planfam")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="-plan",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "planfam-code",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="-code",
        parent_timestamp="20260506010101",
        done=True,
        outcome="failed",
    )

    _run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_killed_latest_plan_family_child_blocks_dependency(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "planfam")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="-plan",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "planfam-code",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="-code",
        parent_timestamp="20260506010101",
        done=True,
        outcome="killed",
    )

    _run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_legacy_dot_plan_family_dependency_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "legacy")
    make_agent(
        tmp_path,
        "proj",
        "20260406010101",
        "legacy.plan",
        workflow_name="legacy",
        role_suffix=".plan",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260406010202",
        "legacy.code",
        workflow_name="legacy",
        role_suffix=".code",
        parent_timestamp="20260406010101",
        done=True,
        outcome="completed",
    )

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["legacy"]}


def test_submitted_planner_resolves_plan_row_wait(tmp_path: Path, monkeypatch) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "planner--plan")
    planner_dir = _make_submitted_planner(tmp_path, "20260625184716", "planner")
    # A real submitted planner finalizes its handoff workflow_state as completed
    # before blocking in review (still no done.json anywhere).
    _write_workflow_state(planner_dir)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )
    assert dependencies_resolved(index, ["planner--plan"])
    # The whole plan chain is still in review, so the family/root wait stays
    # parked even though the planner row resolves.
    assert not dependencies_resolved(index, ["planner"])

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planner--plan"]}


def test_submitted_planner_legacy_dot_plan_alias_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "planner.plan")
    _make_submitted_planner(tmp_path, "20260625184716", "planner")

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planner.plan"]}


def test_submitted_planner_does_not_resolve_family_wait(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "planner")
    _make_submitted_planner(tmp_path, "20260625184716", "planner")

    _run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_submitted_planner_minimal_meta_resolves_plan_row_wait(
    tmp_path: Path, monkeypatch
) -> None:
    # A freshly submitted plan (no replan/promotion yet) carries only its base
    # name, role suffix, submission marker, and plan path.
    waiter_dir = _make_waiting_agent(tmp_path, "planner--plan")
    _make_submitted_planner(tmp_path, "20260625184716", "planner", promoted=False)

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planner--plan"]}


def test_submitted_planner_without_plan_path_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "planner--plan")
    _make_submitted_planner(tmp_path, "20260625184716", "planner", plan_path=None)

    _run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_completed_named_agent_success_path_writes_ready(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}
    out = capsys.readouterr().out
    assert "[wait_checks] Dependencies satisfied for waiter-cl" in out
    assert "wait_checks: projects=1 artifacts=2 waiting=1 ready_written=1" in out


def test_concrete_indexed_wait_marker_resolves_without_template_marker(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = _make_waiting_agent(tmp_path, "build-3")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "build-3",
        done=True,
        outcome="completed",
    )

    waiting = json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
    assert waiting["waiting_for"] == ["build-3"]
    assert all("-@" not in dep for dep in waiting["waiting_for"])

    _run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["build-3"]}


def test_multiple_waiting_dependencies_scan_artifacts_once(
    tmp_path: Path, monkeypatch
) -> None:
    first_waiter = _make_waiting_agent(tmp_path, "foo", "wf", suffix="waiter-1")
    second_waiter = _make_waiting_agent(tmp_path, "foo", suffix="waiter-2")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "wf",
        workflow_name="wf",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010303",
        "wf.child",
        workflow_name="wf",
        parent_timestamp="20260506010202",
        done=True,
        outcome="completed",
    )

    original_read_json_dict = wait_checks_module._read_json_dict
    agent_meta_reads = 0

    def counting_read_json_dict(path: Path) -> dict[str, Any] | None:
        nonlocal agent_meta_reads
        if path.name == "agent_meta.json":
            agent_meta_reads += 1
        return original_read_json_dict(path)

    monkeypatch.setattr(
        wait_checks_module,
        "_read_json_dict",
        counting_read_json_dict,
    )

    _run_wait_checks(tmp_path, monkeypatch)

    assert (first_waiter / "ready.json").exists()
    assert (second_waiter / "ready.json").exists()
    assert agent_meta_reads == 5


def test_wait_checks_no_projects_dir_emits_noop_summary(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _run_wait_checks(tmp_path, monkeypatch)

    assert capsys.readouterr().out == (
        "wait_checks: projects=0 artifacts=0 waiting=0 ready_written=0 "
        "reason=no_projects_dir\n"
    )


def test_wait_checks_unresolved_dependency_emits_noop_reason(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _make_waiting_agent(tmp_path, "missing-agent")

    _run_wait_checks(tmp_path, monkeypatch)

    out = capsys.readouterr().out
    assert "wait_checks: projects=1 artifacts=1 waiting=1 ready_written=0" in out
    assert "unresolved=1 reason=dependencies_not_ready" in out
