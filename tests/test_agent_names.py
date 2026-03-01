"""Tests for sase.agent_names module."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from sase.agent_names import claim_agent_name, find_named_agent, get_next_auto_name

# A PID that is guaranteed not to exist (beyond kernel PID_MAX_LIMIT)
_DEAD_PID = 99_999_999


def _make_agent(
    base: Path,
    project: str,
    suffix: str,
    name: str,
    *,
    done: bool = False,
    outcome: str | None = None,
    pid: int | None = None,
) -> Path:
    """Create a fake agent artifact directory with agent_meta.json."""
    artifact_dir = (
        base / ".sase" / "projects" / project / "artifacts" / "ace-run" / suffix
    )
    artifact_dir.mkdir(parents=True)
    meta: dict[str, object] = {"name": name, "model": "test"}
    if pid is not None:
        meta["pid"] = pid
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta))
    if done:
        done_data: dict[str, object] = {}
        if outcome:
            done_data["outcome"] = outcome
        (artifact_dir / "done.json").write_text(json.dumps(done_data))
    return artifact_dir


class TestFindNamedAgent:
    def test_finds_done_agent(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo", done=True, outcome="success")
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is not None
        assert result.is_done
        assert result.outcome == "success"

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo")
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("bar")
        assert result is None

    def test_returns_none_when_no_projects_dir(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is None

    def test_prefers_running_over_done(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run-old", "foo", done=True)
        running_dir = _make_agent(tmp_path, "proj", "run-new", "foo")
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is not None
        assert not result.is_done
        assert result.artifacts_dir == str(running_dir)


class TestClaimAgentName:
    def test_strips_name_from_other_agents(self, tmp_path: Path) -> None:
        old_dir = _make_agent(tmp_path, "proj", "run-old", "foo", done=True)
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir))

        # Old agent should have name stripped
        old_meta = json.loads((old_dir / "agent_meta.json").read_text())
        assert "name" not in old_meta
        assert old_meta["model"] == "test"  # other fields preserved

        # New agent keeps name
        new_meta = json.loads((new_dir / "agent_meta.json").read_text())
        assert new_meta["name"] == "foo"

    def test_does_not_strip_different_name(self, tmp_path: Path) -> None:
        other_dir = _make_agent(tmp_path, "proj", "run-other", "bar")
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir))

        # "bar" agent should be untouched
        other_meta = json.loads((other_dir / "agent_meta.json").read_text())
        assert other_meta["name"] == "bar"

    def test_no_projects_dir(self, tmp_path: Path) -> None:
        # Should not raise
        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", "/nonexistent")


class TestGetNextAutoName:
    def test_returns_a_when_no_agents(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "a"

    def test_skips_active_names(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "a", pid=os.getpid())
        _make_agent(tmp_path, "proj", "run2", "b", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "c"

    def test_reuses_done_agent_name(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "a", done=True)
        _make_agent(tmp_path, "proj", "run2", "b", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "a"

    def test_wraps_to_double_letter(self, tmp_path: Path) -> None:
        for i, letter in enumerate("abcdefghijklmnopqrstuvwxyz"):
            _make_agent(tmp_path, "proj", f"run{i}", letter, pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "aa"

    def test_reuses_name_of_dead_process(self, tmp_path: Path) -> None:
        """Agent without done.json but with a dead PID gets its name reused."""
        _make_agent(tmp_path, "proj", "run1", "a", pid=_DEAD_PID)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "a"

    def test_reuses_name_when_no_pid(self, tmp_path: Path) -> None:
        """Agent without done.json and no PID info gets its name reused."""
        _make_agent(tmp_path, "proj", "run1", "a")
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "a"
