"""Regression tests for the wait_checks chop script."""

import json
import sys
from pathlib import Path

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


def _make_waiting_agent(base: Path, *waiting_for: str) -> Path:
    artifact_dir = base / ".sase/projects/proj/artifacts/ace-run/waiter"
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


def test_completed_named_agent_success_path_writes_ready(
    tmp_path: Path, monkeypatch
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
