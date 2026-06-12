"""Tests for dismissed agent identity persistence."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import load_dismissed_agents, save_dismissed_agents
from sase.ace.tui.models.agent import AgentType


def test_load_empty_when_no_file(tmp_path: Path) -> None:
    """Test loading returns empty set when no file exists."""
    with patch(
        "sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE",
        tmp_path / "nonexistent.json",
    ):
        result = load_dismissed_agents()
        assert result == set()


def test_null_raw_suffix(tmp_path: Path) -> None:
    """Test that None raw_suffix is preserved through round-trip."""
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        dismissed = {(AgentType.RUNNING, "my_cl", None)}
        assert save_dismissed_agents(dismissed)
        result = load_dismissed_agents()
        assert result == dismissed


def test_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON files are handled gracefully."""
    test_file = tmp_path / "dismissed_agents.json"
    test_file.write_text("not valid json {")
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        result = load_dismissed_agents()
        assert result == set()


def test_handles_non_list_json(tmp_path: Path) -> None:
    """Test that non-list JSON is handled gracefully."""
    test_file = tmp_path / "dismissed_agents.json"
    test_file.write_text('{"key": "value"}')
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        result = load_dismissed_agents()
        assert result == set()


def test_handles_unknown_agent_type(tmp_path: Path) -> None:
    """Test that unknown AgentType values are skipped."""
    test_file = tmp_path / "dismissed_agents.json"
    test_file.write_text(
        '[["unknown_type", "cl_1", "ts"], ["workflow", "cl_2", "ts2"]]'
    )
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        result = load_dismissed_agents()
        assert result == {(AgentType.WORKFLOW, "cl_2", "ts2")}


def test_handles_malformed_entries(tmp_path: Path) -> None:
    """Test that malformed entries are skipped."""
    test_file = tmp_path / "dismissed_agents.json"
    test_file.write_text(
        '[["workflow", "cl", "ts"], [1, 2], "bad", ["workflow", "cl2"]]'
    )
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        result = load_dismissed_agents()
        assert result == {(AgentType.WORKFLOW, "cl", "ts")}


def test_no_trimming_limit(tmp_path: Path) -> None:
    """Test that all entries are preserved (no MAX_DISMISSED limit)."""
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        total = 1000
        dismissed: set[tuple[AgentType, str, str | None]] = {
            (AgentType.WORKFLOW, "cl", f"{i:014d}") for i in range(total)
        }
        save_dismissed_agents(dismissed)
        result = load_dismissed_agents()
        assert len(result) == total


def test_stale_snapshot_save_is_skipped(tmp_path: Path) -> None:
    """A snapshot superseded by a newer snapshot must not overwrite it.

    Regression test: concurrent kill/dismiss persistence workers each
    blind-write a full-set snapshot; without the generation guard a slow
    older worker could erase a later dismissal from disk.
    """
    from sase.ace.dismissed_agents import snapshot_dismissed_agents

    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        live = {(AgentType.RUNNING, "cl_a", "00000000000001")}
        older = snapshot_dismissed_agents(live)
        live.add((AgentType.RUNNING, "cl_b", "00000000000002"))
        newer = snapshot_dismissed_agents(live)

        assert save_dismissed_agents(newer)
        # The older snapshot's worker finishes late and must be skipped.
        assert not save_dismissed_agents(older)
        assert load_dismissed_agents() == set(newer)


def test_in_order_snapshot_saves_both_persist(tmp_path: Path) -> None:
    """Snapshots persisted in capture order both reach disk."""
    from sase.ace.dismissed_agents import snapshot_dismissed_agents

    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        live = {(AgentType.RUNNING, "cl_a", "00000000000001")}
        older = snapshot_dismissed_agents(live)
        live.add((AgentType.RUNNING, "cl_b", "00000000000002"))
        newer = snapshot_dismissed_agents(live)

        assert save_dismissed_agents(older)
        assert save_dismissed_agents(newer)
        assert load_dismissed_agents() == set(newer)


def test_live_set_save_supersedes_pending_snapshots(tmp_path: Path) -> None:
    """An unstamped live-set save outranks snapshots captured earlier.

    A revive removes an identity from the live set and saves it directly on
    the UI thread; a pending dismiss worker holding an older snapshot that
    still contains the identity must not resurrect it.
    """
    from sase.ace.dismissed_agents import snapshot_dismissed_agents

    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        live = {(AgentType.RUNNING, "cl_a", "00000000000001")}
        pending = snapshot_dismissed_agents(live)
        live.clear()  # revived

        assert save_dismissed_agents(set(live))
        assert not save_dismissed_agents(pending)
        assert load_dismissed_agents() == set()
