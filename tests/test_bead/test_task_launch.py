"""Detached task-bead launch helper tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.bead.task_launch import (
    _build_task_launch_argv,
    resolve_task_launch_cwd,
    submit_task_launch_task,
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
        resolved = resolve_task_launch_cwd(
            None,
            agent_project_file=project_file,
        )

    assert resolved == primary
    get_workspace_directory.assert_called_once_with("sase", 1)


def test_submit_task_launch_task_submits_literal_detached_command(
    tmp_path: Path,
) -> None:
    task = SimpleNamespace(task_id="k7m2xyz")
    with (
        patch("sase.tasks.tasks_dir", return_value=tmp_path / "tasks"),
        patch("sase.tasks.read_tasks", return_value=[]),
        patch(
            "sase.bead.project_name.infer_project_name_from_cwd",
            return_value="sase",
        ),
        patch(
            "sase.tasks.runner.submit_detached_task",
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
        patch("sase.tasks.tasks_dir", return_value=tmp_path / "tasks"),
        patch("sase.tasks.read_tasks", return_value=[existing]) as read_tasks,
        patch(
            "sase.bead.project_name.infer_project_name_from_cwd",
            return_value="sase",
        ),
        patch("sase.tasks.runner.submit_detached_task") as submit_task,
    ):
        submitted = submit_task_launch_task(
            "sase-42",
            cwd=tmp_path,
            feedback="New feedback must not duplicate the launch.",
        )

    assert submitted is existing
    assert read_tasks.call_args.kwargs == {
        "status": frozenset({"pending", "running"}),
        "kind": "detached",
    }
    submit_task.assert_not_called()
