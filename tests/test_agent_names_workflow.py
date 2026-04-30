"""Tests for sase.agent.names.is_workflow_complete."""

import os
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import is_workflow_complete

from tests._agent_names_fixtures import DEAD_PID as _DEAD_PID
from tests._agent_names_fixtures import make_agent as _make_agent


class TestIsWorkflowComplete:
    def test_no_workflow_agents_returns_none(self, tmp_path: Path) -> None:
        """Returns None when no agents have matching workflow_name."""
        _make_agent(tmp_path, "proj", "run1", "b", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is None

    def test_no_projects_dir_returns_none(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is None

    def test_root_alive_no_done(self, tmp_path: Path) -> None:
        """Root alive without done.json → False."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=os.getpid(),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is False

    def test_root_done_all_children_done(self, tmp_path: Path) -> None:
        """Root + coder both have done.json → True."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
            done=True,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=_DEAD_PID,
            done=True,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is True

    def test_root_done_child_alive(self, tmp_path: Path) -> None:
        """Root done but coder still alive without done.json → False."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
            done=True,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=os.getpid(),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is False

    def test_root_done_child_dead_no_done(self, tmp_path: Path) -> None:
        """Root done, intermediate child dead without done.json → True."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
            done=True,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=_DEAD_PID,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is True

    def test_root_dead_no_done_children_done(self, tmp_path: Path) -> None:
        """Root dead without done.json but all children done → True."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=_DEAD_PID,
            done=True,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is True

    def test_root_dead_no_done_child_alive(self, tmp_path: Path) -> None:
        """Root dead without done.json, child still alive → False."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=os.getpid(),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is False

    def test_root_dead_no_done_no_children(self, tmp_path: Path) -> None:
        """Root dead without done.json and no children → False."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is False

    def test_single_root_with_done(self, tmp_path: Path) -> None:
        """Promoted root with no children yet, has done.json → True."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
            done=True,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is True

    def test_no_root_children_exist(self, tmp_path: Path) -> None:
        """Children exist but no root agent found → None."""
        _make_agent(
            tmp_path,
            "proj",
            "run2",
            "a.2",
            workflow_name="a",
            parent_timestamp="run1",
            pid=_DEAD_PID,
            done=True,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_workflow_complete("a") is None

    def test_does_not_route_through_snapshot(self, tmp_path: Path) -> None:
        """Targeted Python path must not materialize the agent-scan snapshot.

        Routing this hot predicate through ``scan_agent_artifacts`` would
        force the snapshot to be materialized (the Phase 3H regression).
        Importing :mod:`sase.core.agent_scan_facade` here and asserting it
        is never called proves the targeted walk is in effect.
        """
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "a.1",
            workflow_name="a",
            pid=_DEAD_PID,
            done=True,
        )

        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch(
                "sase.core.agent_scan_facade.scan_agent_artifacts",
                side_effect=AssertionError(
                    "is_workflow_complete must not route through the snapshot facade"
                ),
            ) as mocked_scan,
        ):
            assert is_workflow_complete("a") is True
            assert mocked_scan.call_count == 0
