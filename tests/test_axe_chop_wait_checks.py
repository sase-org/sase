"""Regression tests for the wait_checks chop script."""

import json
import sys
from pathlib import Path
from typing import Any

import sase.scripts.sase_chop_wait_checks as wait_checks_module
from sase.axe.chop_script_context import ChopScriptContext, write_chop_context
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
