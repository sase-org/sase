from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import subprocess

import pytest

import sase.sdd._store_maintenance as maintenance
from sase.sdd._store_maintenance import maybe_gc_sidecar_clone


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
    _write_pack_files(clone_dir, 3)
    _write_loose_objects(clone_dir, 3)
    monkeypatch.setattr(
        "sase.sdd._commit.run_sdd_git",
        lambda *_a, **_kw: pytest.fail("unfragmented clone ran git gc"),
    )

    assert maybe_gc_sidecar_clone(clone_dir, tmp_path / "primary") is False


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
