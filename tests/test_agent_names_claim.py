"""Claim and collision tests for sase.agent.names."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import NameCollisionError, claim_agent_name

from tests._agent_names_fixtures import DEAD_PID as _DEAD_PID
from tests._agent_names_fixtures import make_agent as _make_agent


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

    def test_preserves_stale_agent_names(self, tmp_path: Path) -> None:
        """Claiming a name never mutates a previous agent."""
        stale_dir = _make_agent(tmp_path, "proj", "run-old", "foo", pid=_DEAD_PID)
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir))

        stale_meta = json.loads((stale_dir / "agent_meta.json").read_text())
        assert stale_meta["name"] == "foo"
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


class TestClaimAgentNameExplicit:
    def test_rejects_running_collision(self, tmp_path: Path) -> None:
        existing = _make_agent(tmp_path, "proj", "run-old", "foo", pid=os.getpid())
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(NameCollisionError, match="foo1"):
                claim_agent_name("foo", str(new_dir), explicit=True)

        existing_meta = json.loads((existing / "agent_meta.json").read_text())
        assert existing_meta["name"] == "foo"
        assert existing_meta["model"] == "test"

        new_meta = json.loads((new_dir / "agent_meta.json").read_text())
        assert new_meta["name"] == "foo"

    def test_rejects_done_collision(self, tmp_path: Path) -> None:
        existing = _make_agent(tmp_path, "proj", "run-old", "foo", done=True)
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(NameCollisionError):
                claim_agent_name("foo", str(new_dir), explicit=True)

        existing_meta = json.loads((existing / "agent_meta.json").read_text())
        assert existing_meta["name"] == "foo"

    def test_reject_keeps_done_json_name(self, tmp_path: Path) -> None:
        existing = _make_agent(tmp_path, "proj", "run-old", "foo", done=True)
        # Augment done.json with a name field, mirroring the save path.
        done_path = existing / "done.json"
        done_data = json.loads(done_path.read_text())
        done_data["name"] = "foo"
        done_path.write_text(json.dumps(done_data))

        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")
        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(NameCollisionError):
                claim_agent_name("foo", str(new_dir), explicit=True)

        existing_meta = json.loads((existing / "agent_meta.json").read_text())
        assert existing_meta["name"] == "foo"
        existing_done = json.loads(done_path.read_text())
        assert existing_done["name"] == "foo"

    def test_workflow_name_collision_rejected(self, tmp_path: Path) -> None:
        child_dir = _make_agent(
            tmp_path,
            "proj",
            "run-old",
            "a.1",
            workflow_name="a",
            parent_timestamp="run-root",
            done=True,
        )
        new_dir = _make_agent(tmp_path, "proj", "run-new", "a")

        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(NameCollisionError):
                claim_agent_name("a", str(new_dir), explicit=True)

        child_meta = json.loads((child_dir / "agent_meta.json").read_text())
        assert child_meta["workflow_name"] == "a"
        assert child_meta["name"] == "a.1"

        new_meta = json.loads((new_dir / "agent_meta.json").read_text())
        assert new_meta["name"] == "a"

    def test_multiple_collisions_are_not_renamed(self, tmp_path: Path) -> None:
        first = _make_agent(tmp_path, "proj", "run-1", "foo", pid=os.getpid())
        second = _make_agent(tmp_path, "proj", "run-2", "foo", pid=os.getpid())
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(NameCollisionError):
                claim_agent_name("foo", str(new_dir), explicit=True)

        names = sorted(
            [
                json.loads((first / "agent_meta.json").read_text())["name"],
                json.loads((second / "agent_meta.json").read_text())["name"],
            ]
        )
        assert names == ["foo", "foo"]

    def test_non_explicit_does_not_strip_previous_agents(self, tmp_path: Path) -> None:
        stale_dir = _make_agent(tmp_path, "proj", "run-old", "foo", pid=os.getpid())
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir))  # explicit defaults to False

        stale_meta = json.loads((stale_dir / "agent_meta.json").read_text())
        assert stale_meta["name"] == "foo"

    def test_explicit_reject_does_not_rewrite_wait_references(
        self, tmp_path: Path
    ) -> None:
        """Rejecting a collision leaves existing wait markers untouched."""
        existing = _make_agent(tmp_path, "proj", "run-old", "foo", pid=os.getpid())
        waiter = _make_agent(tmp_path, "proj", "run-waiter", "bar", pid=os.getpid())
        waiter_meta_path = waiter / "agent_meta.json"
        waiter_meta = json.loads(waiter_meta_path.read_text())
        waiter_meta["wait_for"] = ["foo"]
        waiter_meta_path.write_text(json.dumps(waiter_meta))

        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")
        with patch.object(Path, "home", return_value=tmp_path):
            with pytest.raises(NameCollisionError):
                claim_agent_name("foo", str(new_dir), explicit=True)

        existing_meta = json.loads((existing / "agent_meta.json").read_text())
        assert existing_meta["name"] == "foo"
        waiter_after = json.loads(waiter_meta_path.read_text())
        assert waiter_after["wait_for"] == ["foo"]
