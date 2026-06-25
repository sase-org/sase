"""Regression tests for the wait_checks chop script."""

import json
from pathlib import Path
from typing import Any

import sase.scripts.sase_chop_wait_checks as wait_checks_module
from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependencies_resolved,
)

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


def test_named_agent_killed_newest_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(tmp_path, "proj", "20260506010101", "foo", done=True)
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "foo",
        done=True,
        outcome="killed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_later_same_name_completed_agent_resolves_after_killed(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
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

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}


def test_repeat_stopped_completed_marker_resolves_downstream_wait(
    tmp_path: Path, monkeypatch
) -> None:
    """A repeat-stopped slot still reports `completed`, so the cascade is generic.

    The next downstream waiter must resolve off the stopped predecessor exactly
    like any other completed producer -- the chop never inspects `repeat_stopped`.
    """
    waiter_dir = make_waiting_agent(tmp_path, "foo.2")
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

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo.2"]}


def test_failed_workflow_name_dependency_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "wf")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "wf.1",
        workflow_name="wf",
        done=True,
        outcome="failed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_successful_workflow_name_dependency_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "wf")
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

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["wf"]}


def test_shared_resolver_matches_wait_checks_workflow_fixture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "wf")
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

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["wf"]}


def test_completed_named_agent_success_path_writes_ready(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["foo"]}
    out = capsys.readouterr().out
    assert "[wait_checks] Dependencies satisfied for waiter-cl" in out
    assert "wait_checks: projects=1 artifacts=2 waiting=1 ready_written=1" in out


def test_concrete_indexed_wait_marker_resolves_without_template_marker(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "build-3")
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

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["build-3"]}


def test_multiple_waiting_dependencies_scan_artifacts_once(
    tmp_path: Path, monkeypatch
) -> None:
    first_waiter = make_waiting_agent(tmp_path, "foo", "wf", suffix="waiter-1")
    second_waiter = make_waiting_agent(tmp_path, "foo", suffix="waiter-2")
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

    run_wait_checks(tmp_path, monkeypatch)

    assert (first_waiter / "ready.json").exists()
    assert (second_waiter / "ready.json").exists()
    assert agent_meta_reads == 5


def test_wait_checks_no_projects_dir_emits_noop_summary(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    run_wait_checks(tmp_path, monkeypatch)

    assert capsys.readouterr().out == (
        "wait_checks: projects=0 artifacts=0 waiting=0 ready_written=0 "
        "reason=no_projects_dir\n"
    )


def test_wait_checks_unresolved_dependency_emits_noop_reason(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    make_waiting_agent(tmp_path, "missing-agent")

    run_wait_checks(tmp_path, monkeypatch)

    out = capsys.readouterr().out
    assert "wait_checks: projects=1 artifacts=1 waiting=1 ready_written=0" in out
    assert "unresolved=1 reason=dependencies_not_ready" in out
