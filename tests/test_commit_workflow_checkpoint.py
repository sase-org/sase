"""Tests for the commit-workflow checkpoint persistence module."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workflows.commit import checkpoint
from sase.workflows.commit.checkpoint import _CommitCheckpoint


def _make_cp(**overrides: object) -> _CommitCheckpoint:
    """Build a populated checkpoint with sensible defaults."""
    base: dict[str, object] = {
        "method": "create_commit",
        "payload": {"message": "fix: bug", "files": ["a.py"]},
        "cwd": "/tmp/work",
        "cl_name": "my-cl",
        "project_file": "/tmp/work/proj.gp",
        "diff_path": "/tmp/work/.sase/commit_diff.diff",
        "base_cl_name": "my-cl",
        "reserved_name": "my-cl_1",
        "parent_cl_name": "parent-cl",
        "dispatch_result": "abc123",
        "cs_name": "my-cl_1",
        "entry_id": "42",
        "completed_steps": ["dispatch", "write_result_marker"],
    }
    base.update(overrides)
    return _CommitCheckpoint(**base)  # type: ignore[arg-type]


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    cp = _make_cp()
    target = tmp_path / "commit_state.json"

    written = checkpoint.save(cp, str(target))

    assert written == str(target)
    loaded = checkpoint.load(str(target))
    assert loaded is not None
    assert loaded.method == cp.method
    assert loaded.payload == cp.payload
    assert loaded.cwd == cp.cwd
    assert loaded.cl_name == cp.cl_name
    assert loaded.project_file == cp.project_file
    assert loaded.diff_path == cp.diff_path
    assert loaded.base_cl_name == cp.base_cl_name
    assert loaded.reserved_name == cp.reserved_name
    assert loaded.parent_cl_name == cp.parent_cl_name
    assert loaded.dispatch_result == cp.dispatch_result
    assert loaded.cs_name == cp.cs_name
    assert loaded.entry_id == cp.entry_id
    assert loaded.completed_steps == cp.completed_steps
    assert loaded.version == cp.version
    assert loaded.created_at == pytest.approx(cp.created_at)


def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    assert checkpoint.load(str(tmp_path / "nope.json")) is None


def test_load_returns_none_for_unknown_version(tmp_path: Path) -> None:
    target = tmp_path / "future.json"
    target.write_text(
        json.dumps(
            {
                "version": 999,
                "method": "create_commit",
                "payload": {},
                "cwd": "/tmp",
            }
        )
    )

    assert checkpoint.load(str(target)) is None


def test_get_checkpoint_path_uses_artifacts_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))

    path = checkpoint.get_checkpoint_path()

    assert path == str(tmp_path / "commit_state.json")
    assert os.path.isdir(os.path.dirname(path))


def test_get_checkpoint_path_falls_back_to_session_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "2026-04-17T12-00-00")
    monkeypatch.setenv("HOME", str(tmp_path))

    path = checkpoint.get_checkpoint_path()

    expected = str(tmp_path / ".sase" / "commit_state" / "2026-04-17T12-00-00.json")
    assert path == expected
    assert os.path.isdir(os.path.dirname(path))


def test_get_checkpoint_path_falls_back_to_pid_when_no_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    path = checkpoint.get_checkpoint_path()

    expected = str(tmp_path / ".sase" / "commit_state" / f"{os.getpid()}.json")
    assert path == expected


def test_delete_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "gone.json"
    target.write_text("{}")
    assert target.exists()

    checkpoint.delete(str(target))
    assert not target.exists()
    # Second call must not raise.
    checkpoint.delete(str(target))


def test_save_writes_atomically(tmp_path: Path) -> None:
    target = tmp_path / "commit_state.json"
    tmp_sibling = tmp_path / "commit_state.json.tmp"
    tmp_sibling.write_text("garbage that should be replaced")

    cp = _make_cp(payload={"message": "atomic"})
    written = checkpoint.save(cp, str(target))

    assert written == str(target)
    assert target.exists()
    data = json.loads(target.read_text())
    assert data["payload"] == {"message": "atomic"}
    # The temp file is consumed by os.replace.
    assert not tmp_sibling.exists()


def test_save_tolerates_unwritable_path(tmp_path: Path) -> None:
    target = tmp_path / "commit_state.json"
    cp = _make_cp()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    with patch("sase.workflows.commit.checkpoint.open", _boom, create=True):
        result = checkpoint.save(cp, str(target))

    assert result is None
    assert not target.exists()
