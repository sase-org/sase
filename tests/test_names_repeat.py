"""Tests for repeat-batch name reservation in sase.agent.names."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    NameCollisionError,
    get_active_agent_name_map,
    get_active_agent_names,
    get_active_child_names,
    get_next_auto_name,
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
            names = get_active_child_names("sase-z")
        assert names == {"sase-z.1", "sase-z.2"}

    def test_done_children_still_held(self, tmp_path: Path) -> None:
        _write_meta(tmp_path, "ts1", "foo.1", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            names = get_active_child_names("foo")
        assert names == {"foo.1"}

    def test_no_projects_dir(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            names = get_active_child_names("foo")
        assert names == set()

    def test_ignores_non_matching_pattern(self, tmp_path: Path) -> None:
        _write_meta(tmp_path, "ts1", "foo", pid=os.getpid())
        _write_meta(tmp_path, "ts2", "foo.bar", pid=os.getpid())  # not \d+
        with patch.object(Path, "home", return_value=tmp_path):
            names = get_active_child_names("foo")
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


class TestAutoNameChildAware:
    def test_done_child_reserves_letter(self, tmp_path: Path) -> None:
        # Undismissed orphan from an old %r:3 batch: name="q.2", done.
        # Done agents reserve their slot and prefix until dismissed.
        _write_meta(tmp_path, "ts1", "q.2", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            active = get_active_agent_names()
            auto = get_next_auto_name()
        assert "q" in active
        assert "q.2" in active
        assert auto == "a"

    def test_skips_letter_with_live_child(self, tmp_path: Path) -> None:
        _write_meta(tmp_path, "ts1", "b.1", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            active = get_active_agent_names()
        assert "b" in active

    def test_repeat_launch_after_orphan_picks_safe_base(self, tmp_path: Path) -> None:
        # Reproduces the Telegram bug: orphan "q.2" must prevent
        # reserve_repeat_name_base(None, 3) from returning "q".
        _write_meta(tmp_path, "ts1", "q.2", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            base = reserve_repeat_name_base(None, 3)
        assert base != "q"

    def test_non_child_name_not_treated_as_prefix(self, tmp_path: Path) -> None:
        # Multi-segment names like "sase-z.2" must NOT reserve "sase-z"
        # via the new prefix path — the auto sequence can't reach them.
        _write_meta(tmp_path, "ts1", "sase-z.2", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            active = get_active_agent_names()
        assert "sase-z" not in active


class TestGetActiveAgentNameMap:
    def test_returns_artifact_dirs(self, tmp_path: Path) -> None:
        live = _write_meta(tmp_path, "ts1", "sase-12.1", pid=os.getpid())
        done = _write_meta(tmp_path, "ts2", "sase-12.land", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            mapping = get_active_agent_name_map()
        assert mapping["sase-12.1"] == str(live)
        assert mapping["sase-12.land"] == str(done)

    def test_skips_dead_non_done_agents(self, tmp_path: Path) -> None:
        # PID 1 is init — not a sase agent, treated as dead.
        _write_meta(tmp_path, "ts1", "sase-12.1", pid=1)
        with patch.object(Path, "home", return_value=tmp_path):
            mapping = get_active_agent_name_map()
        assert "sase-12.1" not in mapping

    def test_no_projects_dir(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_active_agent_name_map() == {}

    def test_does_not_include_auto_name_prefix(self, tmp_path: Path) -> None:
        # An agent named "a.claude.plan" must not surface as a "a" entry —
        # only full claimed names are returned.
        _write_meta(tmp_path, "ts1", "a.claude.plan", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            mapping = get_active_agent_name_map()
        assert "a" not in mapping
        assert "a.claude.plan" in mapping
