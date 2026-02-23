"""Tests for sase.agent_names module."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent_names import claim_agent_name, find_named_agent


def _make_agent(
    base: Path,
    project: str,
    suffix: str,
    name: str,
    *,
    done: bool = False,
    outcome: str | None = None,
) -> Path:
    """Create a fake agent artifact directory with agent_meta.json."""
    artifact_dir = (
        base / ".sase" / "projects" / project / "artifacts" / "ace-run" / suffix
    )
    artifact_dir.mkdir(parents=True)
    meta = {"name": name, "model": "test"}
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
