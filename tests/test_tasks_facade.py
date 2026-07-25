"""Tests for durable task models, ids, logs, config, and Rust facade."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.config import core as config_core
from sase.tasks import (
    TASK_WIRE_SCHEMA_VERSION,
    BackgroundTask,
    TaskRefError,
    TaskUpdate,
    append_task,
    delete_task_logs,
    filter_tasks,
    get_task,
    new_task_id,
    open_task_log,
    prune_tasks,
    read_task_log_tail,
    read_tasks,
    resolve_task_ref,
    short_task_id,
    task_log_path,
    update_task,
)
from sase.tasks.ids import TASK_ID_ALPHABET, TASK_ID_LENGTH


def _task(
    task_id: str,
    *,
    status: str = "pending",
    created_at: str = "2026-07-25T12:00:00Z",
    label: str = "Build docs",
    project: str | None = "sase",
    session_id: str | None = "session-a",
    tags: list[str] | None = None,
    command: list[str] | None = None,
    cl_name: str | None = "docs_refresh",
) -> BackgroundTask:
    return BackgroundTask(
        task_id=task_id,
        label=label,
        kind="command",
        status=status,
        command=command or ["just", "docs"],
        cwd="/tmp",
        project=project,
        session_id=session_id,
        origin="test",
        cl_name=cl_name,
        tags=tags or ["docs"],
        created_at=created_at,
        log_path=f"/tmp/{task_id}.log",
    )


def test_task_wire_round_trip_ignores_unknown_fields() -> None:
    task = _task("0123456789ab")
    payload = task.to_dict()
    payload["future_field"] = {"new": True}

    restored = BackgroundTask.from_dict(payload)

    assert restored == task
    assert restored.to_dict()["project"] == "sase"


def test_task_update_distinguishes_omitted_from_explicit_null() -> None:
    update = TaskUpdate(task_id="0123456789ab", phase=None, pid=42)

    assert update.to_dict() == {
        "task_id": "0123456789ab",
        "pid": 42,
        "phase": None,
    }
    assert TaskUpdate.from_dict(
        {"task_id": "0123456789ab", "phase": None, "future": "ignored"}
    ).to_dict() == {"task_id": "0123456789ab", "phase": None}


def test_task_id_generation_and_short_form() -> None:
    ids = {new_task_id() for _ in range(100)}

    assert len(ids) == 100
    assert all(len(task_id) == TASK_ID_LENGTH for task_id in ids)
    assert all(set(task_id) <= set(TASK_ID_ALPHABET) for task_id in ids)
    assert short_task_id("0123456789ab") == "012345"


def test_resolve_task_ref_handles_unique_short_unknown_and_ambiguous() -> None:
    first = _task("abc012345678", label="First")
    second = _task("abc112345678", label="Second")
    tasks = [first, second]

    assert resolve_task_ref("ABC0", tasks) is first
    with pytest.raises(TaskRefError, match="at least 3"):
        resolve_task_ref("ab", tasks)
    with pytest.raises(TaskRefError, match="no task"):
        resolve_task_ref("zzz", tasks)
    with pytest.raises(TaskRefError, match=r"abc012.*First.*abc112.*Second"):
        resolve_task_ref("abc", tasks)


def test_task_log_pipe_bounds_subprocess_output(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setenv("SASE_TASK_LOG_MAX_BYTES", "64")

    with open_task_log("task-one") as output:
        subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; print('A' * 100); sys.stdout.flush(); "
                    "print('tail', file=sys.stderr)"
                ),
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            check=True,
        )

    path = task_log_path("task-one")
    assert path.stat().st_size <= 64
    assert "tail" in path.read_text(encoding="utf-8")


def test_task_log_tail_spans_rotation_and_delete(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    path = task_log_path("task-one")
    path.parent.mkdir(parents=True)
    path.with_name(f"{path.name}.1").write_text("one\ntwo\n", encoding="utf-8")
    path.write_text("three\nfour\n", encoding="utf-8")

    assert read_task_log_tail("task-one", 3) == "two\nthree\nfour\n"
    delete_task_logs(["task-one", "missing"])
    assert not path.exists()
    assert not path.with_name(f"{path.name}.1").exists()


def test_task_log_path_rejects_traversal(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    with pytest.raises(ValueError, match="invalid task id"):
        task_log_path("../escape")


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, 100),
        ({"tasks": {"history_limit": 7}}, 7),
        ({"tasks": {"history_limit": 0}}, 100),
        ({"tasks": {"history_limit": True}}, 100),
        ({"tasks": {"history_limit": "7"}}, 100),
        ({"tasks": []}, 100),
    ],
)
def test_task_history_limit_validation(
    monkeypatch: Any, config: dict[str, Any], expected: int
) -> None:
    monkeypatch.setattr(config_core, "load_merged_config", lambda: config)
    assert config_core.get_task_history_limit() == expected


def test_task_history_config_default_and_schema() -> None:
    root = Path(__file__).parents[1]
    defaults = yaml.safe_load(
        (root / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (root / "src/sase/config/sase.schema.json").read_text(encoding="utf-8")
    )

    assert defaults["tasks"]["history_limit"] == 100
    history = schema["properties"]["tasks"]["properties"]["history_limit"]
    assert history["type"] == "integer"
    assert history["minimum"] == 1
    assert history["default"] == 100
    assert schema["properties"]["tasks"]["additionalProperties"] is False


def test_filter_tasks_applies_every_supported_filter() -> None:
    wanted = _task("wanted-task1", label="Compile Docs", command=["mkdocs", "build"])
    other = _task(
        "other-task22",
        status="error",
        label="Tests",
        project="other",
        session_id=None,
        tags=["ci"],
        command=["pytest"],
        cl_name="test_suite",
    )
    tasks = [wanted, other]

    assert filter_tasks(tasks, status="pending") == [wanted]
    assert filter_tasks(tasks, status={"error"}) == [other]
    assert filter_tasks(tasks, session_id="session-a") == [wanted]
    assert filter_tasks(tasks, session_id=None) == [other]
    assert filter_tasks(tasks, project="other") == [other]
    assert filter_tasks(tasks, tag="docs") == [wanted]
    assert filter_tasks(tasks, query="MKDOCS BUILD") == [wanted]
    assert filter_tasks(tasks, query="test_suite") == [other]


def test_rust_facade_round_trip_update_and_get(tmp_path: Path) -> None:
    store = tmp_path / "tasks.jsonl"
    task = _task("0123456789ab")

    appended = append_task(task, path=store, history_limit=5)
    updated = update_task(
        task.task_id,
        path=store,
        status="running",
        phase=None,
        pid=4321,
    )

    assert appended.schema_version == TASK_WIRE_SCHEMA_VERSION
    assert updated.matched is True
    assert updated.task is not None
    assert updated.task.status == "running"
    assert updated.task.phase is None
    assert updated.task.pid == 4321
    assert get_task(task.task_id, path=store) == updated.task
    assert read_tasks(path=store, status="running") == [updated.task]


def test_retention_and_pruning_delete_corresponding_logs(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    store = tmp_path / "tasks.jsonl"
    first = _task(
        "first-task01",
        status="success",
        created_at="2026-07-25T12:00:00Z",
    )
    second = _task(
        "second-task2",
        status="success",
        created_at="2026-07-25T12:01:00Z",
    )
    running = _task(
        "running-task",
        status="running",
        created_at="2026-07-25T11:00:00Z",
    )
    for task in (first, second, running):
        log = task_log_path(task.task_id)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(task.task_id, encoding="utf-8")
        append_task(task, path=store, history_limit=2)

    outcome = prune_tasks(path=store, history_limit=1)

    assert outcome.pruned_task_ids == [first.task_id]
    assert [task.task_id for task in outcome.snapshot.tasks] == [
        second.task_id,
        running.task_id,
    ]
    assert not task_log_path(first.task_id).exists()
    assert task_log_path(second.task_id).exists()
    assert task_log_path(running.task_id).exists()
