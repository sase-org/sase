"""Tests for repeat-batch name reservation in sase.agent.names."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    NameCollisionError,
    _get_active_child_names,
    reserve_repeat_name_base,
)


def _write_meta(
    base: Path,
    suffix: str,
    name: str,
    *,
    done: bool = False,
    pid: int | None = None,
) -> Path:
    artifact_dir = (
        base / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifact_dir.mkdir(parents=True)
    meta: dict[str, object] = {"name": name, "model": "test"}
    if pid is not None:
        meta["pid"] = pid
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta))
    if done:
        (artifact_dir / "done.json").write_text(json.dumps({"outcome": "completed"}))
    return artifact_dir


class TestGetActiveChildNames:
    def test_finds_child_names(self, tmp_path: Path) -> None:
        _write_meta(tmp_path, "ts1", "sase-z.1", pid=os.getpid())
        _write_meta(tmp_path, "ts2", "sase-z.2", pid=os.getpid())
        _write_meta(tmp_path, "ts3", "other.1", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            names = _get_active_child_names("sase-z")
        assert names == {"sase-z.1", "sase-z.2"}

    def test_done_children_still_held(self, tmp_path: Path) -> None:
        _write_meta(tmp_path, "ts1", "foo.1", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            names = _get_active_child_names("foo")
        assert names == {"foo.1"}

    def test_no_projects_dir(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            names = _get_active_child_names("foo")
        assert names == set()

    def test_ignores_non_matching_pattern(self, tmp_path: Path) -> None:
        _write_meta(tmp_path, "ts1", "foo", pid=os.getpid())
        _write_meta(tmp_path, "ts2", "foo.bar", pid=os.getpid())  # not \d+
        with patch.object(Path, "home", return_value=tmp_path):
            names = _get_active_child_names("foo")
        assert names == set()


class TestReserveRepeatNameBase:
    def test_explicit_no_collision(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert reserve_repeat_name_base("sase-z", 4) == "sase-z"

    def test_explicit_collision_raises(self, tmp_path: Path) -> None:
        _write_meta(tmp_path, "ts1", "sase-z.2", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(NameCollisionError, match="sase-z"):
                reserve_repeat_name_base("sase-z", 4)

    def test_auto_delegates_to_get_next_auto_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            with patch("sase.agent.names.get_next_auto_name", return_value="c"):
                assert reserve_repeat_name_base(None, 3) == "c"

    def test_invalid_count_raises(self) -> None:
        with pytest.raises(ValueError):
            reserve_repeat_name_base("foo", 0)
