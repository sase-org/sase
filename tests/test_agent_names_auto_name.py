"""Tests for sase.agent.names.get_next_auto_name."""

import os
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import get_next_auto_name

from tests._agent_names_fixtures import DEAD_PID as _DEAD_PID
from tests._agent_names_fixtures import make_agent as _make_agent

_AUTO_SINGLE_CHARS = "0123456789abcdefghijklmnopqrstuvwxyz"
_AUTO_SINGLE_CHARS_BEFORE_M = "0123456789abcdefghijkl"


class TestGetNextAutoName:
    def test_returns_0_when_no_agents(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "0"

    def test_skips_active_names(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "0", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "1"

    def test_done_agent_reserves_name(self, tmp_path: Path) -> None:
        """Done but not-dismissed agent keeps its name slot reserved."""
        _make_agent(tmp_path, "proj", "run1", "0", done=True)
        _make_agent(tmp_path, "proj", "run2", "1", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "2"

    def test_reuses_deleted_agent_name(self, tmp_path: Path) -> None:
        """Name is freed once the owning artifact state is deleted."""
        agent_dir = _make_agent(tmp_path, "proj", "run1", "0", done=True)
        _make_agent(tmp_path, "proj", "run2", "1", pid=os.getpid())

        # Simulate forced-reuse wipe/delete by removing the artifact directory.
        import shutil

        shutil.rmtree(agent_dir)

        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "0"

    def test_wraps_to_two_char_name(self, tmp_path: Path) -> None:
        for i, char in enumerate(_AUTO_SINGLE_CHARS):
            _make_agent(tmp_path, "proj", f"run{i}", char, pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "00"

    def test_uses_nine_after_zero_through_eight_in_tail(self, tmp_path: Path) -> None:
        for i, char in enumerate(_AUTO_SINGLE_CHARS):
            _make_agent(tmp_path, "proj", f"single-{i}", char, pid=os.getpid())
        for i, suffix in enumerate("012345678"):
            _make_agent(
                tmp_path, "proj", f"zero-suffix-{i}", f"0{suffix}", pid=os.getpid()
            )
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "09"

    def test_wraps_two_char_tail_to_next_first_char(self, tmp_path: Path) -> None:
        for i, char in enumerate(_AUTO_SINGLE_CHARS):
            _make_agent(tmp_path, "proj", f"single-{i}", char, pid=os.getpid())
        for i, suffix in enumerate(_AUTO_SINGLE_CHARS):
            _make_agent(
                tmp_path, "proj", f"zero-suffix-{i}", f"0{suffix}", pid=os.getpid()
            )
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "10"

    def test_dead_process_still_reserves_name(self, tmp_path: Path) -> None:
        """Existing artifact state keeps a permanent name reserved."""
        _make_agent(tmp_path, "proj", "run1", "0", pid=_DEAD_PID)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "1"

    def test_artifact_without_pid_still_reserves_name(self, tmp_path: Path) -> None:
        """Names are reserved by state existence, not process liveness."""
        _make_agent(tmp_path, "proj", "run1", "0")
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "1"

    def test_done_workflow_without_appears_as_agent_reserves_name(
        self, tmp_path: Path
    ) -> None:
        """Done workflows with appears_as_agent=False reserve their name."""
        _make_agent(tmp_path, "proj", "run1", "0", done=True, appears_as_agent=False)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "1"

    def test_done_workflow_with_appears_as_agent_reserves_name(
        self, tmp_path: Path
    ) -> None:
        """Done workflows with appears_as_agent=True reserve their name."""
        _make_agent(tmp_path, "proj", "run1", "0", done=True, appears_as_agent=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "1"

    def test_done_mixed_workflow_and_agent_names_reserve(self, tmp_path: Path) -> None:
        """All done agents reserve their slot regardless of appears_as_agent."""
        _make_agent(tmp_path, "proj", "run1", "0", done=True, appears_as_agent=False)
        _make_agent(tmp_path, "proj", "run2", "1", done=True, appears_as_agent=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "2"

    def test_workflow_name_reserves_base_name(self, tmp_path: Path) -> None:
        """Promoted initial agent reserves base workflow name, not child name."""
        _make_agent(tmp_path, "proj", "run1", "0.1", workflow_name="0", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            # "0" should be reserved (via workflow_name), not "0.1"
            assert get_next_auto_name() == "1"

    def test_dotted_suffix_reserves_prefix(self, tmp_path: Path) -> None:
        """``m.plan`` (no workflow_name) reserves the base letter ``m``."""
        _make_agent(tmp_path, "proj", "run1", "m.plan", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "0"
        # And once earlier single-char names are taken too, the next pick skips
        # ``m``.
        for char in _AUTO_SINGLE_CHARS_BEFORE_M:
            _make_agent(tmp_path, "proj", f"run-{char}", char, pid=os.getpid())
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
        for char in _AUTO_SINGLE_CHARS_BEFORE_M:
            _make_agent(tmp_path, "proj", f"run-{char}", char, pid=os.getpid())
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
        for char in _AUTO_SINGLE_CHARS_BEFORE_M:
            _make_agent(tmp_path, "proj", f"run-{char}", char, pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "n"

    def test_done_parent_tracked_child_reserves_prefix(self, tmp_path: Path) -> None:
        """A done ``parent_timestamp`` child reserves the auto-name prefix."""
        for char in _AUTO_SINGLE_CHARS_BEFORE_M:
            _make_agent(tmp_path, "proj", f"run-{char}", char, pid=os.getpid())
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

    def test_dead_parent_tracked_child_still_reserves_prefix(
        self, tmp_path: Path
    ) -> None:
        """A dead child still reserves the prefix while its artifact exists."""
        for char in _AUTO_SINGLE_CHARS_BEFORE_M:
            _make_agent(tmp_path, "proj", f"run-{char}", char, pid=os.getpid())
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
            assert get_next_auto_name() == "n"

    def test_live_parent_tracked_child_reserves_prefix_without_root(
        self, tmp_path: Path
    ) -> None:
        """A live ``parent_timestamp`` child reserves the prefix on its own."""
        for char in _AUTO_SINGLE_CHARS_BEFORE_M:
            _make_agent(tmp_path, "proj", f"run-{char}", char, pid=os.getpid())
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
        """``sase-z.2`` does not reserve any auto-name root."""
        _make_agent(
            tmp_path,
            "proj",
            "run1",
            "sase-z.2",
            workflow_name="sase-z",
            pid=os.getpid(),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "0"

    def test_orphaned_dotted_agent_still_reserves_prefix(self, tmp_path: Path) -> None:
        """``m.claude.plan`` reserves ``m`` while its artifact exists."""
        for char in _AUTO_SINGLE_CHARS_BEFORE_M:
            _make_agent(tmp_path, "proj", f"run-{char}", char, pid=os.getpid())
        _make_agent(
            tmp_path,
            "proj",
            "run-dead",
            "m.claude.plan",
            workflow_name="m.claude",
            pid=_DEAD_PID,
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "n"

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
        for char in _AUTO_SINGLE_CHARS_BEFORE_M:
            _make_agent(tmp_path, "proj", f"run-{char}", char, pid=os.getpid())
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
        for char in _AUTO_SINGLE_CHARS_BEFORE_M:
            _make_agent(tmp_path, "proj", f"run-{char}", char, pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "n"

    def test_done_multi_model_reserves_base_name(self, tmp_path: Path) -> None:
        """Done multi-model children (0.codex / 0.claude) reserve ``0``.

        Regression: visible done multi-model children with workflow_name ``0``
        still claim the auto-assignable root until dismissed.
        """
        _make_agent(
            tmp_path,
            "proj",
            "run-codex",
            "0.codex",
            workflow_name="0",
            done=True,
        )
        _make_agent(
            tmp_path,
            "proj",
            "run-claude",
            "0.claude",
            workflow_name="0",
            done=True,
        )
        _make_agent(tmp_path, "proj", "run-0a", "0a", pid=os.getpid())
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "1"

    def test_running_follow_up_still_reserves_prefix(self, tmp_path: Path) -> None:
        """Live parent-tracked follow-up still reserves the auto-name prefix."""
        _make_agent(
            tmp_path,
            "proj",
            "run-parent",
            "0",
            pid=os.getpid(),
        )
        _make_agent(
            tmp_path,
            "proj",
            "run-followup",
            "0.plan",
            parent_timestamp="run-parent",
            pid=os.getpid(),
        )
        with patch.object(Path, "home", return_value=tmp_path):
            assert get_next_auto_name() == "1"

    def test_dismissed_suffix_holds_name(self, tmp_path: Path) -> None:
        """Dismissed agents remain reserved until their state is wiped."""
        _make_agent(tmp_path, "proj", "run1", "0", pid=os.getpid())
        _make_agent(tmp_path, "proj", "run2", "1", pid=os.getpid())
        dismissed_file = tmp_path / ".sase" / "dismissed_agents.json"
        dismissed_file.parent.mkdir(parents=True, exist_ok=True)
        dismissed_file.write_text('[["run", "proj", "run1"]]')
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", dismissed_file),
        ):
            assert get_next_auto_name() == "2"

    def test_dismissed_done_suffix_holds_name(self, tmp_path: Path) -> None:
        """Dismissed completed agents remain reserved until wiped."""
        _make_agent(tmp_path, "proj", "run1", "0", done=True)
        _make_agent(tmp_path, "proj", "run2", "1", pid=os.getpid())
        dismissed_file = tmp_path / ".sase" / "dismissed_agents.json"
        dismissed_file.parent.mkdir(parents=True, exist_ok=True)
        dismissed_file.write_text('[["run", "proj", "run1"]]')
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", dismissed_file),
        ):
            assert get_next_auto_name() == "2"
