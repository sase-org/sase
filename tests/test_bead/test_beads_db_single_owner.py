"""Single-owner regression: Python never opens ``beads.db`` via SQLite.

Covers a new store and a legacy JSONL store prepared in a separate completed
subprocess. Reopens across Rust mutations, asserts canonical data, and uses a
coordinated subprocess writer to prove real mutations keep unique child IDs,
retained updates, and lock exclusion. Never mocks Rust mutations; stdlib
SQLite opens of ``beads.db`` fail deterministically.
"""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
import subprocess
import sys
import unittest.mock as _mock
from pathlib import Path

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BeadProject

_PROCESS_TIMEOUT_SECONDS = 120.0


def _guarded_sqlite_connect(
    opened: list[str],
    real_connect: object,
) -> object:
    def _guard(*args: object, **kwargs: object) -> object:
        target = str(args[0]) if args else str(kwargs.get("database", ""))
        if target.endswith("beads.db"):
            opened.append(target)
            raise AssertionError(f"Python must not open {target} via stdlib sqlite3")
        return real_connect(*args, **kwargs)  # type: ignore[arg-type]

    return _guard


def _prepare_legacy_store_in_subprocess(store_parent: Path) -> None:
    """Write a legacy JSONL store in a separate completed subprocess."""
    script = (
        "import json; from pathlib import Path; "
        f"base = Path({str(store_parent)!r}) / 'beads'; "
        "base.mkdir(parents=True, exist_ok=True); "
        "(base / 'config.json').write_text(json.dumps("
        "{'issue_prefix': 'legacy', 'next_counter': 3, 'owner': ''})); "
        "(base / 'issues.jsonl').write_text("
        "json.dumps({'id': 'legacy-1', 'title': 'Legacy epic', 'status': 'open', "
        "'issue_type': 'plan', 'tier': 'epic', "
        "'created_at': '2026-01-01T00:00:00Z', "
        "'updated_at': '2026-01-01T00:00:00Z', 'dependencies': []}) + '\\n' + "
        "json.dumps({'id': 'legacy-1.1', 'title': 'Legacy child', 'status': 'open', "
        "'issue_type': 'phase', 'parent_id': 'legacy-1', "
        "'created_at': '2026-01-01T00:00:00Z', "
        "'updated_at': '2026-01-01T00:00:00Z', 'dependencies': []}) + '\\n'); "
    )
    subprocess.run([sys.executable, "-c", script], check=True, timeout=60)


def _child_creator(
    project_dir: str,
    epic_id: str,
    worker_index: int,
    ready_queue: object,
    result_queue: object,
) -> None:
    result: dict[str, object] = {"ok": True, "worker": worker_index, "error": ""}
    try:
        with BeadProject(Path(project_dir)) as project:
            ready_queue.put(worker_index)  # type: ignore[attr-defined]
            child = project.create(
                f"Concurrent child {worker_index}",
                IssueType.PHASE,
                parent_id=epic_id,
            )
            project.update(child.id, description=f"worker {worker_index}")
            result["child_id"] = child.id
    except BaseException as exc:  # noqa: BLE001
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    result_queue.put(result)  # type: ignore[attr-defined]


def test_new_store_never_opens_beads_db(tmp_path: Path) -> None:
    opened: list[str] = []
    real_connect = sqlite3.connect
    with _mock.patch(
        "sqlite3.connect",
        side_effect=_guarded_sqlite_connect(opened, real_connect),
    ):
        with BeadProject.init(tmp_path) as project:
            epic = project.create("Epic", IssueType.PLAN)
            child = project.create("Child", IssueType.PHASE, parent_id=epic.id)
            project.add_dependency(child.id, epic.id)
            assert project.show(epic.id).id == epic.id
            assert [i.id for i in project.list_issues()] == [epic.id, child.id]
            project._export()
            assert "Epic" in (project.beads_dir / "issues.jsonl").read_text()

        with BeadProject(tmp_path) as reopened:
            assert reopened.show(child.id).dependencies[0].depends_on_id == epic.id
            second = reopened.create("Second", IssueType.PHASE, parent_id=epic.id)
            assert second.id == f"{epic.id}.2"
            reopened._export()

        with BeadProject(tmp_path) as final:
            assert sorted(i.id for i in final.list_issues()) == sorted(
                [epic.id, child.id, second.id]
            )
        assert opened == []


def test_legacy_store_adoption_never_opens_beads_db(tmp_path: Path) -> None:
    _prepare_legacy_store_in_subprocess(tmp_path)
    beads_dir = tmp_path / "beads"
    assert (beads_dir / "issues.jsonl").exists()
    assert not (beads_dir / "beads.db").exists()

    opened: list[str] = []
    real_connect = sqlite3.connect
    with _mock.patch(
        "sqlite3.connect",
        side_effect=_guarded_sqlite_connect(opened, real_connect),
    ):
        with BeadProject(tmp_path, beads_dirname="beads") as project:
            assert project.show("legacy-1").title == "Legacy epic"
            assert sorted(i.id for i in project.list_issues()) == [
                "legacy-1",
                "legacy-1.1",
            ]
            project._export()
            assert "legacy-1" in (beads_dir / "issues.jsonl").read_text()

        with BeadProject(tmp_path, beads_dirname="beads") as reopened:
            created = reopened.create("Adopted", IssueType.PLAN)
            assert created.id.startswith("legacy-")
            assert reopened.show("legacy-1.1").title == "Legacy child"

        with BeadProject(tmp_path, beads_dirname="beads") as final:
            assert "legacy-1" in {i.id for i in final.list_issues()}
            assert created.id in {i.id for i in final.list_issues()}
        assert opened == []


def test_coordinated_writers_keep_unique_child_ids(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path) as project:
        epic = project.create("Epic", IssueType.PLAN)
        epic_id = epic.id

    ctx = multiprocessing.get_context("spawn")
    ready_queue = ctx.Queue()
    result_queue = ctx.Queue()
    workers = 4
    procs = [
        ctx.Process(
            target=_child_creator,
            args=(str(tmp_path), epic_id, idx, ready_queue, result_queue),
        )
        for idx in range(workers)
    ]
    try:
        for proc in procs:
            proc.start()
        ready = {ready_queue.get(timeout=_PROCESS_TIMEOUT_SECONDS) for _ in procs}
        assert ready == set(range(workers))
        results = [result_queue.get(timeout=_PROCESS_TIMEOUT_SECONDS) for _ in procs]
    finally:
        for proc in procs:
            proc.join(timeout=_PROCESS_TIMEOUT_SECONDS)
            if proc.is_alive():
                proc.terminate()
    assert [r for r in results if not r["ok"]] == []
    child_ids = sorted(str(r["child_id"]) for r in results)
    assert len(set(child_ids)) == workers
    assert child_ids == sorted(f"{epic_id}.{n}" for n in range(1, workers + 1))

    expected_description = {
        str(r["child_id"]): f"worker {r['worker']}" for r in results
    }
    with BeadProject(tmp_path) as project:
        children = project.get_epic_children(epic_id)
        assert sorted(c.id for c in children) == child_ids
        for child_id in child_ids:
            assert project.show(child_id).description == expected_description[child_id]
