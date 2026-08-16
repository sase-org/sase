"""Detached task-bead launch helper tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.bead.task_launch import (
    _active_task_launch,
    _build_task_launch_argv,
    _resolve_task_launch_cwd,
    active_task_launch_bead_ids,
    submit_task_launch_task,
    submit_task_launch_for_project,
    task_launch_origin_from_gate_source,
)


def test_build_task_launch_argv_carries_optional_feedback() -> None:
    assert _build_task_launch_argv(
        "sase-42",
        feedback="  Keep the compatibility shim.  ",
    ) == [
        "sase",
        "bead",
        "work",
        "sase-42",
        "--yes-to-all",
        "--launch-feedback",
        "Keep the compatibility shim.",
    ]
    assert _build_task_launch_argv("sase-42", yes_to_all=False) == [
        "sase",
        "bead",
        "work",
        "sase-42",
        "--yes",
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("tui", "ace"),
        ("telegram", "telegram"),
        ("auto_resolution", "axe"),
        ("host", "api"),
        (None, "api"),
    ],
)
def test_task_launch_origin_maps_gate_response_sources(
    source: str | None,
    expected: str,
) -> None:
    assert task_launch_origin_from_gate_source(source) == expected


def test_resolve_task_launch_cwd_reuses_canonical_project_resolution(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "projects" / "sase" / "sase.sase"
    primary = tmp_path / "primary"
    primary.mkdir()

    with patch(
        "sase.running_field.get_workspace_directory",
        return_value=str(primary),
    ) as get_workspace_directory:
        resolved = _resolve_task_launch_cwd(
            None,
            agent_project_file=project_file,
        )

    assert resolved == primary
    get_workspace_directory.assert_called_once_with("sase", 1)


def test_submit_task_launch_task_submits_literal_unattributed_command(
    tmp_path: Path,
) -> None:
    task = SimpleNamespace(task_id="k7m2xyz")
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[]),
        patch(
            "sase.bead.project_name.infer_project_name_from_cwd",
            return_value="sase",
        ),
        patch(
            "sase.procs.runner.submit_proc",
            return_value=task,
        ) as submit_task,
    ):
        submitted = submit_task_launch_task(
            "sase-42",
            cwd=tmp_path,
            feedback="Focus on rollback.",
            origin="telegram",
        )

    assert submitted is task
    assert submit_task.call_args.args[0] == [
        "sase",
        "bead",
        "work",
        "sase-42",
        "--yes-to-all",
        "--launch-feedback",
        "Focus on rollback.",
    ]
    assert submit_task.call_args.kwargs == {
        "label": "Task launch · sase-42",
        "cwd": tmp_path,
        "origin": "telegram",
        "project": "sase",
        "session_id": None,
        "tags": ("task", "launch"),
    }


def test_submit_task_launch_task_deduplicates_active_bead_id(
    tmp_path: Path,
) -> None:
    existing = SimpleNamespace(
        task_id="existing",
        command=["sase", "bead", "work", "sase-42", "--yes-to-all"],
        cwd=str(tmp_path),
        tags=["launch", "task"],
    )
    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[existing]) as read_tasks,
        patch(
            "sase.bead.project_name.infer_project_name_from_cwd",
            return_value="sase",
        ),
        patch("sase.procs.runner.submit_proc") as submit_task,
    ):
        submitted = submit_task_launch_task(
            "sase-42",
            cwd=tmp_path,
            feedback="New feedback must not duplicate the launch.",
        )

    assert submitted is existing
    assert read_tasks.call_args.kwargs == {
        "status": frozenset({"pending", "running", "settling"}),
        "kind": {"command", "detached"},
    }
    submit_task.assert_not_called()


def _task_row(
    task_id: str,
    *,
    status: str = "running",
    kind: str = "command",
    command: list[str] | None = None,
    tags: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        task_id=task_id,
        status=status,
        kind=kind,
        command=command or ["sase", "bead", "work", "sase-42", "--yes-to-all"],
        tags=tags or ["task", "launch"],
    )


def test_active_task_launch_bead_ids_returns_active_task_bead_launches() -> None:
    rows = [
        _task_row("active-1", command=["sase", "bead", "work", "sase-42"]),
        _task_row("active-2", command=["sase", "bead", "work", "sase-99"]),
        _task_row("terminal", status="success"),
        _task_row("command-kind", kind="command"),
        _task_row("untagged", tags=["launch"]),
        _task_row("other-command", command=["sase", "agent", "run", "sase-77"]),
        _task_row(
            "epic-plan",
            command=["sase", "bead", "work", "plans/epic.md", "--yes-to-all"],
            tags=["epic", "launch"],
        ),
    ]

    def read_tasks(*, status: frozenset[str], kind: set[str]) -> list[SimpleNamespace]:
        assert status == frozenset({"pending", "running", "settling"})
        assert kind == {"command", "detached"}
        return [row for row in rows if row.status in status and row.kind in kind]

    with patch("sase.procs.read_procs", side_effect=read_tasks):
        assert active_task_launch_bead_ids() == frozenset({"sase-42", "sase-99"})


def test_active_task_launch_returns_newest_matching_active_row() -> None:
    newest = _task_row("newest", command=["sase", "bead", "work", "sase-42"])
    older = _task_row("older", command=["sase", "bead", "work", "sase-42"])
    other = _task_row("other", command=["sase", "bead", "work", "sase-99"])

    with patch("sase.procs.read_procs", return_value=[other, newest, older]):
        assert _active_task_launch("sase-42") is newest


def test_submit_task_launch_for_project_reuses_project_resolution(
    tmp_path: Path,
) -> None:
    task = SimpleNamespace(task_id="submitted")
    with (
        patch(
            "sase.bead.task_launch.resolve_task_launch_cwd_for_project",
            return_value=tmp_path,
        ) as resolve,
        patch(
            "sase.bead.task_launch.submit_task_launch_task", return_value=task
        ) as submit,
    ):
        result = submit_task_launch_for_project(
            "sase",
            "sase-42",
            feedback="Focus the fix",
            origin="ace",
        )

    assert result is task
    resolve.assert_called_once_with("sase")
    submit.assert_called_once_with(
        "sase-42",
        cwd=tmp_path,
        feedback="Focus the fix",
        origin="ace",
    )
