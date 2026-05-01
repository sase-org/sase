"""Tests for sase.agent.names: find / get-most-recent / claim."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import (
    allocate_revived_name,
    allocate_resume_name,
    allocate_resume_names,
    claim_agent_name,
    dedup_name,
    find_named_agent,
    first_resume_agent_name,
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


class TestResumeAgentNames:
    def test_finds_resume_colon_paren_and_backtick(self) -> None:
        assert first_resume_agent_name("#resume:foo do work") == "foo"
        assert first_resume_agent_name("#resume(foo) do work") == "foo"
        assert first_resume_agent_name("#resume:`foo bar` do work") == "foo bar"

    def test_ignores_resume_by_chat(self) -> None:
        assert first_resume_agent_name("#resume_by_chat:foo.md") is None

    def test_ignores_fenced_and_disabled_regions(self) -> None:
        prompt = (
            "```\n#resume:fenced\n```\n"
            "%xprompts_enabled:false\n#resume:disabled\n%xprompts_enabled:true\n"
            "#resume:real"
        )
        assert first_resume_agent_name(prompt) == "real"

    def test_first_resume_wins(self) -> None:
        assert first_resume_agent_name("#resume:first then #resume:second") == "first"

    def test_allocates_first_resume_slot(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("foo") == "foo.r1"

    def test_allocates_resume_slot_gap(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.r1", done=True)
        _make_agent(tmp_path, "proj", "run3", "foo.r3", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("foo") == "foo.r2"

    def test_suffixed_descendants_reserve_resume_slot(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.r1.cld", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("foo") == "foo.r2"

    def test_allocates_multiple_resume_names_from_one_snapshot(
        self, tmp_path: Path
    ) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.r1", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_names("foo", 3) == ["foo.r2", "foo.r3", "foo.r4"]

    def test_strips_workflow_role_segments(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("ma.code") == "ma.r1"
            assert allocate_resume_name("pb.plan") == "pb.r1"

    def test_increments_existing_resume_generation(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("ma.code.r1.code") == "ma.r2"
            assert allocate_resume_name("foo.plan.r3") == "foo.r4"

    def test_collapses_repeated_resume_generations(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("ma.code.r1.code.r1.code") == "ma.r2"

    def test_preserves_non_role_substrings(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("decode.codegen.planning") == (
                "decode.codegen.planning.r1"
            )

    def test_normalized_resume_allocation_honors_collisions_and_floor(
        self, tmp_path: Path
    ) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.r2", done=True)
        _make_agent(tmp_path, "proj", "run2", "foo.r4.claude", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("foo.code.r3") == "foo.r5"

    def test_normalized_resume_allocation_fills_gaps_without_floor(
        self, tmp_path: Path
    ) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.r1", done=True)
        _make_agent(tmp_path, "proj", "run3", "foo.r3", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("foo.code") == "foo.r2"


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


class TestDedupName:
    def test_returns_base_when_free(self) -> None:
        reserved: set[str] = set()
        assert dedup_name("foo", reserved) == "foo"
        assert reserved == {"foo"}

    def test_returns_dot_2_on_first_collision(self) -> None:
        reserved = {"foo"}
        assert dedup_name("foo", reserved) == "foo.2"
        assert reserved == {"foo", "foo.2"}

    def test_skips_existing_dot_2(self) -> None:
        reserved = {"foo", "foo.2"}
        assert dedup_name("foo", reserved) == "foo.3"
        assert reserved == {"foo", "foo.2", "foo.3"}

    def test_chains_across_calls(self) -> None:
        reserved = {"foo"}
        first = dedup_name("foo", reserved)
        second = dedup_name("foo", reserved)
        assert first == "foo.2"
        assert second == "foo.3"


class TestAllocateRevivedNameDedup:
    def test_collision_falls_back_to_dot_2(self) -> None:
        reserved = {"foo"}
        new, fallback = allocate_revived_name("260428.foo", reserved=reserved)
        assert new == "foo.2"
        assert fallback == "foo"
        assert reserved == {"foo", "foo.2"}

    def test_batch_revive_sequential_suffixes(self) -> None:
        reserved = {"foo"}
        first, fb1 = allocate_revived_name("260427.foo", reserved=reserved)
        second, fb2 = allocate_revived_name("260428.foo", reserved=reserved)
        assert first == "foo.2"
        assert second == "foo.3"
        assert fb1 == "foo"
        assert fb2 == "foo"

    def test_no_collision_keeps_base(self) -> None:
        reserved: set[str] = set()
        new, fallback = allocate_revived_name("260428.foo", reserved=reserved)
        assert new == "foo"
        assert fallback is None
        assert reserved == {"foo"}


class TestClaimAgentNameExplicit:
    def test_renames_running_collision_to_dot_2(self, tmp_path: Path) -> None:
        existing = _make_agent(tmp_path, "proj", "run-old", "foo", pid=os.getpid())
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir), explicit=True)

        existing_meta = json.loads((existing / "agent_meta.json").read_text())
        assert existing_meta["name"] == "foo.2"
        # Other fields preserved
        assert existing_meta["model"] == "test"

        new_meta = json.loads((new_dir / "agent_meta.json").read_text())
        assert new_meta["name"] == "foo"

    def test_renames_done_collision_to_dot_2(self, tmp_path: Path) -> None:
        existing = _make_agent(tmp_path, "proj", "run-old", "foo", done=True)
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir), explicit=True)

        existing_meta = json.loads((existing / "agent_meta.json").read_text())
        assert existing_meta["name"] == "foo.2"

        # done.json is also rewritten so loaders see the dedup'd name.
        # The fixture only writes done.json with outcome; explicit-rename
        # only touches done.json when it carries a ``name`` field, so a
        # bare done.json (no name) is left untouched here.

    def test_renames_done_with_name_in_done_json(self, tmp_path: Path) -> None:
        existing = _make_agent(tmp_path, "proj", "run-old", "foo", done=True)
        # Augment done.json with a name field, mirroring the save path.
        done_path = existing / "done.json"
        done_data = json.loads(done_path.read_text())
        done_data["name"] = "foo"
        done_path.write_text(json.dumps(done_data))

        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")
        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir), explicit=True)

        existing_meta = json.loads((existing / "agent_meta.json").read_text())
        assert existing_meta["name"] == "foo.2"
        existing_done = json.loads(done_path.read_text())
        assert existing_done["name"] == "foo.2"

    def test_workflow_name_collision_renamed(self, tmp_path: Path) -> None:
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
            claim_agent_name("a", str(new_dir), explicit=True)

        child_meta = json.loads((child_dir / "agent_meta.json").read_text())
        assert child_meta["workflow_name"] == "a.2"
        # Child name "a.1" did NOT match "a" so its name field is unchanged.
        assert child_meta["name"] == "a.1"

        new_meta = json.loads((new_dir / "agent_meta.json").read_text())
        assert new_meta["name"] == "a"

    def test_multiple_collisions_get_sequential_suffixes(self, tmp_path: Path) -> None:
        first = _make_agent(tmp_path, "proj", "run-1", "foo", pid=os.getpid())
        second = _make_agent(tmp_path, "proj", "run-2", "foo", pid=os.getpid())
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir), explicit=True)

        names = sorted(
            [
                json.loads((first / "agent_meta.json").read_text())["name"],
                json.loads((second / "agent_meta.json").read_text())["name"],
            ]
        )
        assert names == ["foo.2", "foo.3"]

    def test_non_explicit_retains_strip_behavior(self, tmp_path: Path) -> None:
        # Mirrors test_strips_name_from_stale_agents but verifies the
        # default (explicit=False) explicitly.
        stale_dir = _make_agent(tmp_path, "proj", "run-old", "foo", pid=os.getpid())
        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")

        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir))  # explicit defaults to False

        stale_meta = json.loads((stale_dir / "agent_meta.json").read_text())
        assert "name" not in stale_meta

    def test_explicit_rewrites_wait_references(self, tmp_path: Path) -> None:
        """Other agents' wait_for markers are rewritten to track the rename."""
        existing = _make_agent(tmp_path, "proj", "run-old", "foo", pid=os.getpid())
        # Waiter references "foo" — should follow the rename to "foo.2".
        waiter = _make_agent(tmp_path, "proj", "run-waiter", "bar", pid=os.getpid())
        waiter_meta_path = waiter / "agent_meta.json"
        waiter_meta = json.loads(waiter_meta_path.read_text())
        waiter_meta["wait_for"] = ["foo"]
        waiter_meta_path.write_text(json.dumps(waiter_meta))

        new_dir = _make_agent(tmp_path, "proj", "run-new", "foo")
        with patch.object(Path, "home", return_value=tmp_path):
            claim_agent_name("foo", str(new_dir), explicit=True)

        existing_meta = json.loads((existing / "agent_meta.json").read_text())
        assert existing_meta["name"] == "foo.2"
        waiter_after = json.loads(waiter_meta_path.read_text())
        assert waiter_after["wait_for"] == ["foo.2"]
