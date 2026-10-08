from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
from pathlib import Path
import subprocess

import pytest

import sase.sdd._store_maintenance as maintenance
from sase.sdd._store_maintenance import (
    maintain_hidden_sidecar_clones,
    _maybe_gc_hidden_sidecar_clone,
    maybe_gc_sidecar_clone,
)


def _clone_dir(tmp_path: Path) -> Path:
    clone_dir = tmp_path / "sidecar"
    (clone_dir / ".git" / "objects" / "pack").mkdir(parents=True)
    return clone_dir


def _write_pack_files(clone_dir: Path, count: int) -> None:
    pack_dir = clone_dir / ".git" / "objects" / "pack"
    for index in range(count):
        (pack_dir / f"pack-{index}.pack").write_text("pack\n", encoding="utf-8")


def _write_loose_objects(clone_dir: Path, count: int) -> None:
    bucket = clone_dir / ".git" / "objects" / "ab"
    bucket.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (bucket / f"{index:038x}").write_text("object\n", encoding="utf-8")


def test_under_fragmentation_thresholds_skips_gc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clone_dir = _clone_dir(tmp_path)
    monkeypatch.setattr(maintenance, "_PACK_FILE_THRESHOLD", 3)
    monkeypatch.setattr(maintenance, "_LOOSE_OBJECT_THRESHOLD", 3)
    monkeypatch.setattr(maintenance, "_LOOSE_OBJECT_BYTES_THRESHOLD", 10**9)
    _write_pack_files(clone_dir, 3)
    _write_loose_objects(clone_dir, 3)
    monkeypatch.setattr(
        "sase.sdd._commit.run_sdd_git",
        lambda *_a, **_kw: pytest.fail("unfragmented clone ran git gc"),
    )

    assert maybe_gc_sidecar_clone(clone_dir, tmp_path / "primary") is False


def test_loose_bytes_above_threshold_runs_gc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Few loose objects still trigger gc when their bytes are heavy.

    Regression test for byte-heavy bead clones (one ~21 MB ``issues.jsonl``
    blob per mutation) that stay below the count threshold.
    """

    clone_dir = _clone_dir(tmp_path)
    primary = tmp_path / "primary"
    monkeypatch.setattr(maintenance, "_PACK_FILE_THRESHOLD", 3)
    monkeypatch.setattr(maintenance, "_LOOSE_OBJECT_THRESHOLD", 10)
    # Three 7-byte objects: count 3 stays below threshold, bytes 21 exceed it.
    monkeypatch.setattr(maintenance, "_LOOSE_OBJECT_BYTES_THRESHOLD", 20)
    _write_loose_objects(clone_dir, 3)

    calls: list[dict[str, object]] = []

    def run_git(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"args": list(args), **kwargs})
        return subprocess.CompletedProcess(
            args=["git", *args], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", run_git)

    assert maybe_gc_sidecar_clone(clone_dir, primary) is True
    assert [call["args"] for call in calls] == [["gc"]]


def test_loose_bytes_below_threshold_skips_gc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clone_dir = _clone_dir(tmp_path)
    monkeypatch.setattr(maintenance, "_PACK_FILE_THRESHOLD", 3)
    monkeypatch.setattr(maintenance, "_LOOSE_OBJECT_THRESHOLD", 10)
    monkeypatch.setattr(maintenance, "_LOOSE_OBJECT_BYTES_THRESHOLD", 21)
    _write_loose_objects(clone_dir, 3)
    monkeypatch.setattr(
        "sase.sdd._commit.run_sdd_git",
        lambda *_a, **_kw: pytest.fail("unfragmented clone ran git gc"),
    )

    assert maybe_gc_sidecar_clone(clone_dir, tmp_path / "primary") is False


def test_loose_object_stats_counts_bytes(tmp_path: Path) -> None:
    clone_dir = _clone_dir(tmp_path)
    _write_loose_objects(clone_dir, 3)

    assert maintenance._loose_object_stats(clone_dir / ".git") == (
        3,
        3 * len("object\n"),
    )


@pytest.mark.parametrize(
    ("pack_count", "loose_count"),
    [
        (4, 0),
        (0, 4),
    ],
)
def test_fragmented_clone_runs_gc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pack_count: int,
    loose_count: int,
) -> None:
    clone_dir = _clone_dir(tmp_path)
    primary = tmp_path / "primary"
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(maintenance, "_PACK_FILE_THRESHOLD", 3)
    monkeypatch.setattr(maintenance, "_LOOSE_OBJECT_THRESHOLD", 3)
    _write_pack_files(clone_dir, pack_count)
    _write_loose_objects(clone_dir, loose_count)

    def run_git(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"args": list(args), **kwargs})
        return subprocess.CompletedProcess(
            args=["git", *args], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", run_git)

    assert maybe_gc_sidecar_clone(clone_dir, primary) is True
    assert calls == [
        {
            "args": ["gc"],
            "cwd": clone_dir,
            "op": "sdd.maintenance.gc",
            "timeout": maintenance._GC_TIMEOUT_SECONDS,
            "check": False,
            "capture_output": True,
            "text": True,
        }
    ]


@pytest.mark.parametrize("failure", ["nonzero", "timeout"])
def test_gc_failure_is_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    clone_dir = _clone_dir(tmp_path)
    monkeypatch.setattr(maintenance, "_PACK_FILE_THRESHOLD", 0)
    _write_pack_files(clone_dir, 1)

    def run_git(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if failure == "timeout":
            from sase.sdd._commit import SddGitCommandTimeout

            raise SddGitCommandTimeout("injected timeout")
        return subprocess.CompletedProcess(
            args=["git", *args],
            returncode=128,
            stdout="",
            stderr="gc failed",
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", run_git)

    assert maybe_gc_sidecar_clone(clone_dir, tmp_path / "primary") is False


def test_contended_materialization_lock_skips_gc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clone_dir = _clone_dir(tmp_path)
    monkeypatch.setattr(maintenance, "_PACK_FILE_THRESHOLD", 0)
    _write_pack_files(clone_dir, 1)

    @contextmanager
    def busy_lock(_primary: Path) -> Iterator[bool]:
        yield False

    monkeypatch.setattr(maintenance, "try_materialization_lock", busy_lock)
    monkeypatch.setattr(
        "sase.sdd._commit.run_sdd_git",
        lambda *_a, **_kw: pytest.fail("busy lock ran git gc"),
    )

    assert maybe_gc_sidecar_clone(clone_dir, tmp_path / "primary") is False


def _redirect_projects_dir(monkeypatch: pytest.MonkeyPatch, projects_dir: Path) -> None:
    projects_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("sase.core.paths.sase_projects_dir", lambda: projects_dir)


def _hidden_clone(projects_dir: Path, project: str, role: str) -> Path:
    clone_dir = projects_dir / project / "repos" / role
    (clone_dir / ".git" / "objects" / "pack").mkdir(parents=True)
    return clone_dir


def _run_git_spy(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def run_git(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"args": list(args), **kwargs})
        return subprocess.CompletedProcess(
            args=["git", *args], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", run_git)
    return calls


def test_hidden_clone_dirs_ignores_non_clones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_dir = tmp_path / "projects"
    _hidden_clone(projects_dir, "proj", "beads")
    (projects_dir / "proj" / "repos" / "not-a-clone").mkdir(parents=True)
    (projects_dir / "proj" / "repos" / "plain-file").write_text("x", encoding="utf-8")
    _redirect_projects_dir(monkeypatch, projects_dir)

    assert maintenance._hidden_sidecar_clone_dirs("proj") == [
        projects_dir / "proj" / "repos" / "beads"
    ]
    assert maintenance._hidden_sidecar_clone_dirs("missing") == []


def test_maintain_hidden_clones_visits_each_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_dir = tmp_path / "projects"
    _redirect_projects_dir(monkeypatch, projects_dir)
    beads = _hidden_clone(projects_dir, "proj", "beads")
    plans = _hidden_clone(projects_dir, "proj", "plans")
    monkeypatch.setattr(maintenance, "_PACK_FILE_THRESHOLD", 0)
    _write_pack_files(beads, 1)
    _write_pack_files(plans, 1)
    calls = _run_git_spy(monkeypatch)

    assert maintain_hidden_sidecar_clones("proj", tmp_path / "primary") == 2
    gc_dirs = sorted(call["cwd"] for call in calls)
    assert gc_dirs == sorted([beads, plans])


def test_hidden_clone_gc_skips_when_materialization_lock_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_dir = tmp_path / "projects"
    _redirect_projects_dir(monkeypatch, projects_dir)
    clone_dir = _hidden_clone(projects_dir, "proj", "beads")
    monkeypatch.setattr(maintenance, "_PACK_FILE_THRESHOLD", 0)
    _write_pack_files(clone_dir, 1)

    @contextmanager
    def busy_lock(_primary: Path) -> Iterator[bool]:
        yield False

    monkeypatch.setattr(maintenance, "try_materialization_lock", busy_lock)
    monkeypatch.setattr(
        "sase.sdd._commit.run_sdd_git",
        lambda *_a, **_kw: pytest.fail("busy lock ran git gc"),
    )

    assert (
        _maybe_gc_hidden_sidecar_clone(
            clone_dir, tmp_path / "primary", project_key="proj"
        )
        is False
    )


def test_hidden_clone_gc_skips_when_machine_writer_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_dir = tmp_path / "projects"
    _redirect_projects_dir(monkeypatch, projects_dir)
    clone_dir = _hidden_clone(projects_dir, "proj", "beads")
    monkeypatch.setattr(maintenance, "_PACK_FILE_THRESHOLD", 0)
    _write_pack_files(clone_dir, 1)
    monkeypatch.setattr(
        "sase.sdd._commit.run_sdd_git",
        lambda *_a, **_kw: pytest.fail("busy writer ran git gc"),
    )

    lock_path = projects_dir / "proj" / "artifact-link-events.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            assert (
                _maybe_gc_hidden_sidecar_clone(
                    clone_dir, tmp_path / "primary", project_key="proj"
                )
                is False
            )
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def test_hidden_clone_gc_runs_when_locks_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_dir = tmp_path / "projects"
    _redirect_projects_dir(monkeypatch, projects_dir)
    clone_dir = _hidden_clone(projects_dir, "proj", "beads")
    primary = tmp_path / "primary"
    monkeypatch.setattr(maintenance, "_PACK_FILE_THRESHOLD", 0)
    _write_pack_files(clone_dir, 1)
    calls = _run_git_spy(monkeypatch)

    assert (
        _maybe_gc_hidden_sidecar_clone(clone_dir, primary, project_key="proj") is True
    )
    assert [call["args"] for call in calls] == [["gc"]]
