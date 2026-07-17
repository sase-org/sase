"""Lookup/history tests for sase.agent.names."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import (
    find_agent_family,
    find_named_agent,
    get_most_recent_agent_name,
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

        Historical references like ``%w:260428.foo`` and ``#fork:260428.foo``
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
        # Older active name + newer dismissed-prefixed name. Without the
        # filter, the dismissed entry would win because its directory
        # name sorts later.
        _make_agent(tmp_path, "proj", "20260427000000", "foo", done=True)
        _make_agent(tmp_path, "proj", "20260428000000", "260428.bar", pid=_DEAD_PID)
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_most_recent_agent_name()
        assert result == "foo"

    def test_returns_none_when_only_dismissed_prefixed(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "20260428000000", "260428.foo", pid=_DEAD_PID)
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_most_recent_agent_name()
        assert result is None


def test_find_agent_family_includes_sequential_descendants(tmp_path: Path) -> None:
    _make_agent(
        tmp_path,
        "proj",
        "20260701010101",
        "foo--0",
        workflow_name="foo",
        agent_family="foo",
        role_suffix="--0",
        done=True,
    )
    _make_agent(
        tmp_path,
        "proj",
        "20260701010202",
        "foo--review",
        workflow_name="foo",
        agent_family="foo",
        role_suffix="--review",
        parent_timestamp="20260701010101",
        done=True,
    )
    _make_agent(
        tmp_path,
        "proj",
        "20260701010303",
        "foo--land",
        workflow_name="foo",
        agent_family="foo",
        role_suffix="--land",
        parent_timestamp="20260701010202",
        done=True,
    )

    with patch.object(Path, "home", return_value=tmp_path):
        family = find_agent_family("foo")

    assert family is not None
    assert [member.name for member in family.members] == [
        "foo--0",
        "foo--review",
        "foo--land",
    ]
