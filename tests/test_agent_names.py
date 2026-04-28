"""Tests for sase.agent.names: find / get-most-recent / claim."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import (
    claim_agent_name,
    find_named_agent,
)

from tests._agent_names_fixtures import DEAD_PID as _DEAD_PID
from tests._agent_names_fixtures import make_agent as _make_agent


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
        running_dir = _make_agent(tmp_path, "proj", "run-new", "foo", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is not None
        assert not result.is_done
        assert result.artifacts_dir == str(running_dir)

    def test_finds_agent_by_workflow_name(self, tmp_path: Path) -> None:
        """Resolves workflow name to the most recent done child agent."""
        _make_agent(tmp_path, "proj", "run1", "a.1", workflow_name="a", pid=_DEAD_PID)
        child_dir = _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            done=True,
            outcome="completed",
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("a")
        assert result is not None
        assert result.is_done
        assert result.outcome == "completed"
        assert result.artifacts_dir == str(child_dir)

    def test_exact_name_preferred_over_workflow(self, tmp_path: Path) -> None:
        """Exact name match takes priority over workflow_name match."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            done=True,
            outcome="completed",
        )
        exact_dir = _make_agent(
            tmp_path, "proj", "run2", "a", done=True, outcome="completed"
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("a")
        assert result is not None
        assert result.artifacts_dir == str(exact_dir)

    def test_skips_dead_agent_without_done(self, tmp_path: Path) -> None:
        """Dead parent phases (no done.json, dead PID) are skipped."""
        _make_agent(tmp_path, "proj", "run-old", "foo", pid=_DEAD_PID)
        done_dir = _make_agent(
            tmp_path, "proj", "run-new", "foo", done=True, outcome="completed"
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo")
        assert result is not None
        assert result.is_done
        assert result.outcome == "completed"
        assert result.artifacts_dir == str(done_dir)

    def test_only_done_skips_running(self, tmp_path: Path) -> None:
        """only_done=True skips running agents and returns done one."""
        _make_agent(tmp_path, "proj", "run-new", "foo", pid=os.getpid())
        done_dir = _make_agent(
            tmp_path, "proj", "run-old", "foo", done=True, outcome="completed"
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo", only_done=True)
        assert result is not None
        assert result.is_done
        assert result.artifacts_dir == str(done_dir)

    def test_only_done_returns_none_when_no_done(self, tmp_path: Path) -> None:
        """only_done=True returns None when only running agents exist."""
        _make_agent(tmp_path, "proj", "run1", "foo", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("foo", only_done=True)
        assert result is None

    def test_finds_dismissed_prefixed_artifact_without_done(
        self, tmp_path: Path
    ) -> None:
        """Dismissal removes done.json but keeps the prefixed agent_meta.json.

        Historical references like ``%w:260428.foo`` and ``#resume:260428.foo``
        must still resolve, so dismissed-prefixed artifacts are treated as
        completed-historical even when their done.json is gone.
        """
        artifact_dir = _make_agent(
            tmp_path, "proj", "run-old", "260428.foo", pid=_DEAD_PID
        )
        with patch.object(Path, "home", return_value=tmp_path):
            result = find_named_agent("260428.foo")
        assert result is not None
        assert result.is_done
        assert result.outcome == "dismissed"
        assert result.artifacts_dir == str(artifact_dir)

    def test_finds_dismissed_name_via_bundle_when_artifact_gone(
        self, tmp_path: Path
    ) -> None:
        """Bundles are the source of truth when the artifact dir is purged."""
        bundles_dir = tmp_path / ".sase" / "dismissed_bundles" / "202604"
        bundles_dir.mkdir(parents=True)
        (bundles_dir / "20260428103000.json").write_text(
            json.dumps(
                {
                    "agent_name": "260428.bar",
                    "raw_suffix": "20260428103000",
                    "cl_name": "bar",
                }
            )
        )
        with (
            patch(
                "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
                tmp_path / ".sase" / "dismissed_bundles",
            ),
            patch.object(Path, "home", return_value=tmp_path),
        ):
            result = find_named_agent("260428.bar")
        assert result is not None
        assert result.is_done
        assert result.outcome == "dismissed"


class TestGetMostRecentAgentName:
    """Bare ``%wait`` should never resolve to a dismissed historical name."""

    def test_skips_dismissed_prefixed_names(self, tmp_path: Path) -> None:
        from sase.agent.names import get_most_recent_agent_name

        # Older active name + newer dismissed-prefixed name. Without the
        # filter, the dismissed entry would win because its directory
        # name sorts later.
        _make_agent(tmp_path, "proj", "20260427000000", "foo", done=True)
        _make_agent(tmp_path, "proj", "20260428000000", "260428.bar", pid=_DEAD_PID)
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_most_recent_agent_name()
        assert result == "foo"

    def test_returns_none_when_only_dismissed_prefixed(self, tmp_path: Path) -> None:
        from sase.agent.names import get_most_recent_agent_name

        _make_agent(tmp_path, "proj", "20260428000000", "260428.foo", pid=_DEAD_PID)
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_most_recent_agent_name()
        assert result is None


class TestClaimAgentName:
    def test_preserves_done_agent_names(self, tmp_path: Path) -> None:
        """Completed agents keep their name when another agent claims it."""
        old_dir = _make_agent(tmp_path, "proj", "run-old", "foo", done=True)
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir))

        # Done agent should keep its name
        old_meta = json.loads((old_dir / "agent_meta.json").read_text())
        assert old_meta["name"] == "foo"

        # New agent keeps name too
        new_meta = json.loads((new_dir / "agent_meta.json").read_text())
        assert new_meta["name"] == "foo"

    def test_strips_name_from_stale_agents(self, tmp_path: Path) -> None:
        """Non-done agents (dead PID) still have their name stripped."""
        stale_dir = _make_agent(tmp_path, "proj", "run-old", "foo", pid=_DEAD_PID)
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir))

        # Stale agent should have name stripped
        stale_meta = json.loads((stale_dir / "agent_meta.json").read_text())
        assert "name" not in stale_meta
        assert stale_meta["model"] == "test"  # other fields preserved

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

    def test_preserves_done_workflow_name_matches(self, tmp_path: Path) -> None:
        """Claiming a name preserves done agents with matching workflow_name."""
        child_dir = _make_agent(
            tmp_path,
            "proj",
            "run-old",
            "a.2",
            workflow_name="a",
            parent_timestamp="run-root",
            done=True,
        )
        new_dir = _make_agent(tmp_path, "proj", "run-new", "a")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("a", str(new_dir))

        # Done child keeps its workflow_name
        child_meta = json.loads((child_dir / "agent_meta.json").read_text())
        assert child_meta["workflow_name"] == "a"

        new_meta = json.loads((new_dir / "agent_meta.json").read_text())
        assert new_meta["name"] == "a"

    def test_no_projects_dir(self, tmp_path: Path) -> None:
        # Should not raise
        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", "/nonexistent")
