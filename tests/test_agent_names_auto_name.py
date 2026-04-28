"""Tests for sase.agent.names.get_next_auto_name."""

import os
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import get_next_auto_name

from tests._agent_names_fixtures import DEAD_PID as _DEAD_PID
from tests._agent_names_fixtures import make_agent as _make_agent


class TestGetNextAutoName:
    def test_returns_a_when_no_agents(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "a"

    def test_skips_active_names(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "a", pid=os.getpid())
        _make_agent(tmp_path, "proj", "run2", "b", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "c"

    def test_done_agent_reserves_name(self, tmp_path: Path) -> None:
        """Done but not-dismissed agent keeps its name slot reserved."""
        _make_agent(tmp_path, "proj", "run1", "a", done=True)
        _make_agent(tmp_path, "proj", "run2", "b", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "c"

    def test_reuses_dismissed_agent_name(self, tmp_path: Path) -> None:
        """Name is freed once artifacts are deleted (dismissed)."""
        agent_dir = _make_agent(tmp_path, "proj", "run1", "a", done=True)
        _make_agent(tmp_path, "proj", "run2", "b", pid=os.getpid())

        # Simulate dismissal by removing the artifact directory
        import shutil

        shutil.rmtree(agent_dir)

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

    def test_done_workflow_without_appears_as_agent_reserves_name(
        self, tmp_path: Path
    ) -> None:
        """Done workflows with appears_as_agent=False reserve their name."""
        _make_agent(tmp_path, "proj", "run1", "a", done=True, appears_as_agent=False)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "b"

    def test_done_workflow_with_appears_as_agent_reserves_name(
        self, tmp_path: Path
    ) -> None:
        """Done workflows with appears_as_agent=True reserve their name."""
        _make_agent(tmp_path, "proj", "run1", "a", done=True, appears_as_agent=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "b"

    def test_done_mixed_workflow_and_agent_names_reserve(self, tmp_path: Path) -> None:
        """All done agents reserve their slot regardless of appears_as_agent."""
        _make_agent(tmp_path, "proj", "run1", "a", done=True, appears_as_agent=False)
        _make_agent(tmp_path, "proj", "run2", "b", done=True, appears_as_agent=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "c"

    def test_workflow_name_reserves_base_name(self, tmp_path: Path) -> None:
        """Promoted initial agent reserves base workflow name, not child name."""
        _make_agent(tmp_path, "proj", "run1", "a.1", workflow_name="a", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            # "a" should be reserved (via workflow_name), not "a.1"
            assert get_next_auto_name() == "b"

    def test_dotted_suffix_reserves_prefix(self, tmp_path: Path) -> None:
        """``m.plan`` (no workflow_name) reserves the base letter ``m``."""
        _make_agent(tmp_path, "proj", "run1", "m.plan", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "a"
        # And once ``a`` is taken too, the next pick skips ``m``.
        _make_agent(tmp_path, "proj", "run2", "a", pid=os.getpid())
        for letter in "bcdefghijkl":
            _make_agent(tmp_path, "proj", f"run-{letter}", letter, pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "n"

    def test_multi_segment_dotted_suffix_reserves_prefix(self, tmp_path: Path) -> None:
        """``m.claude.plan`` with workflow ``m.claude`` reserves ``m`` too."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "m.claude.plan",
            workflow_name="m.claude",
            pid=os.getpid(),
        )
        for letter in "abcdefghijkl":
            _make_agent(tmp_path, "proj", f"run-{letter}", letter, pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            # ``m`` must be skipped even though no agent has the bare name ``m``.
            assert get_next_auto_name() == "n"

    def test_parent_tracked_child_reserves_prefix(self, tmp_path: Path) -> None:
        """A ``parent_timestamp`` child still reserves the auto-name prefix."""
        _make_agent(
            tmp_path,
            "proj",
            "run-parent",
            "m.claude.plan",
            workflow_name="m.claude",
            pid=os.getpid(),
        )
        _make_agent(
            tmp_path,
            "proj",
            "run-child",
            "m.claude.code",
            workflow_name="m.claude",
            parent_timestamp="run-parent",
            pid=os.getpid(),
        )
        for letter in "abcdefghijkl":
            _make_agent(tmp_path, "proj", f"run-{letter}", letter, pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "n"

    def test_done_parent_tracked_child_reserves_prefix(self, tmp_path: Path) -> None:
        """A done ``parent_timestamp`` child reserves the auto-name prefix."""
        for letter in "abcdefghijkl":
            _make_agent(tmp_path, "proj", f"run-{letter}", letter, pid=os.getpid())
        _make_agent(
            tmp_path,
            "proj",
            "run-child",
            "m.claude.code",
            workflow_name="m.claude",
            parent_timestamp="run-parent",
            pid=os.getpid(),
            done=True,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "n"

    def test_dead_parent_tracked_child_releases_prefix(self, tmp_path: Path) -> None:
        """A dead ``parent_timestamp`` child without done.json releases the prefix."""
        for letter in "abcdefghijkl":
            _make_agent(tmp_path, "proj", f"run-{letter}", letter, pid=os.getpid())
        _make_agent(
            tmp_path,
            "proj",
            "run-child",
            "m.claude.code",
            workflow_name="m.claude",
            parent_timestamp="run-parent",
            pid=_DEAD_PID,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "m"

    def test_live_parent_tracked_child_reserves_prefix_without_root(
        self, tmp_path: Path
    ) -> None:
        """A live ``parent_timestamp`` child reserves the prefix on its own."""
        for letter in "abcdefghijkl":
            _make_agent(tmp_path, "proj", f"run-{letter}", letter, pid=os.getpid())
        _make_agent(
            tmp_path,
            "proj",
            "run-child",
            "m.claude.code",
            workflow_name="m.claude",
            parent_timestamp="run-parent",
            pid=os.getpid(),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "n"

    def test_multi_segment_user_base_does_not_pollute_pool(
        self, tmp_path: Path
    ) -> None:
        """``sase-z.2`` does not reserve any auto-name letter."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "sase-z.2",
            workflow_name="sase-z",
            pid=os.getpid(),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "a"

    def test_orphaned_dotted_agent_does_not_reserve_prefix(
        self, tmp_path: Path
    ) -> None:
        """``m.claude.plan`` with a dead PID and no done.json frees ``m``."""
        for letter in "abcdefghijkl":
            _make_agent(tmp_path, "proj", f"run-{letter}", letter, pid=os.getpid())
        _make_agent(
            tmp_path,
            "proj",
            "run-dead",
            "m.claude.plan",
            workflow_name="m.claude",
            pid=_DEAD_PID,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "m"

    def test_dotted_done_agent_reserves_prefix(self, tmp_path: Path) -> None:
        """A done (not dismissed) ``m.claude.plan`` reserves ``m``."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "m.claude.plan",
            workflow_name="m.claude",
            done=True,
        )
        for letter in "abcdefghijkl":
            _make_agent(tmp_path, "proj", f"run-{letter}", letter, pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "n"

    def test_done_codex_plan_agent_reserves_prefix(self, tmp_path: Path) -> None:
        """A done ``m.codex.plan`` artifact reserves the root auto name."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "m.codex.plan",
            workflow_name="m.codex",
            done=True,
        )
        for letter in "abcdefghijkl":
            _make_agent(tmp_path, "proj", f"run-{letter}", letter, pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "n"

    def test_done_multi_model_reserves_base_name(self, tmp_path: Path) -> None:
        """Done multi-model children (a.codex / a.claude) reserve ``a``.

        Regression: visible done multi-model children with workflow_name ``a``
        still claim the auto-assignable root until dismissed.
        """
        _make_agent(
            tmp_path,
            "proj",
            "run-codex",
            "a.codex",
            workflow_name="a",
            done=True,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run-claude",
            "a.claude",
            workflow_name="a",
            done=True,
        )
        _make_agent(tmp_path, "proj", "run-aw", "aw", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "b"

    def test_running_follow_up_still_reserves_prefix(self, tmp_path: Path) -> None:
        """Live parent-tracked follow-up still reserves the auto-name prefix."""
        _make_agent(
            tmp_path,
            "proj",
            "run-parent",
            "a",
            pid=os.getpid(),
        )
        _make_agent(
            tmp_path,
            "proj",
            "run-followup",
            "a.plan",
            parent_timestamp="run-parent",
            pid=os.getpid(),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "b"

    def test_dismissed_suffix_does_not_hold_name(self, tmp_path: Path) -> None:
        """Dismissed agent suffixes are excluded from auto-name reservation."""
        _make_agent(tmp_path, "proj", "run1", "a", pid=os.getpid())
        _make_agent(tmp_path, "proj", "run2", "b", pid=os.getpid())
        dismissed_file = tmp_path / ".sase" / "dismissed_agents.json"
        dismissed_file.parent.mkdir(parents=True, exist_ok=True)
        dismissed_file.write_text('[["run", "proj", "run1"]]')
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", dismissed_file),
        ):
            assert get_next_auto_name() == "a"

    def test_dismissed_done_suffix_does_not_hold_name(self, tmp_path: Path) -> None:
        """Dismissal releases a completed agent's reserved auto-name slot."""
        _make_agent(tmp_path, "proj", "run1", "a", done=True)
        _make_agent(tmp_path, "proj", "run2", "b", pid=os.getpid())
        dismissed_file = tmp_path / ".sase" / "dismissed_agents.json"
        dismissed_file.parent.mkdir(parents=True, exist_ok=True)
        dismissed_file.write_text('[["run", "proj", "run1"]]')
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", dismissed_file),
        ):
            assert get_next_auto_name() == "a"
