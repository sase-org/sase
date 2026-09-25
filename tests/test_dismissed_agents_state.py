"""Tests for dismissed agent identity persistence."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    add_dismissed_agents,
    load_dismissed_agents,
    remove_dismissed_agents,
    update_dismissed_agents,
)
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
        assert add_dismissed_agents(dismissed) == dismissed
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
        add_dismissed_agents(dismissed)
        result = load_dismissed_agents()
        assert len(result) == total


def test_add_dismissed_agents_merges_and_returns_result(tmp_path: Path) -> None:
    """Additive adds compose instead of overwriting the on-disk set."""
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        first = {(AgentType.RUNNING, "cl_a", "00000000000001")}
        second = {(AgentType.WORKFLOW, "cl_b", "00000000000002")}

        assert add_dismissed_agents(first) == first
        assert add_dismissed_agents(second) == first | second
        assert load_dismissed_agents() == first | second


def test_remove_dismissed_agents_keeps_other_identities(
    tmp_path: Path,
) -> None:
    """Revive-style removals drop only their own identities."""
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        both = {
            (AgentType.RUNNING, "cl_a", "00000000000001"),
            (AgentType.RUNNING, "cl_b", "00000000000002"),
        }
        assert add_dismissed_agents(both) == both

        remaining = {(AgentType.RUNNING, "cl_b", "00000000000002")}
        assert (
            remove_dismissed_agents({(AgentType.RUNNING, "cl_a", "00000000000001")})
            == remaining
        )
        assert load_dismissed_agents() == remaining


def test_update_dismissed_agents_applies_removals_then_additions(
    tmp_path: Path,
) -> None:
    """An identity in both lists ends up present: removals run first."""
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        keep = (AgentType.RUNNING, "cl_a", "00000000000001")
        drop = (AgentType.RUNNING, "cl_b", "00000000000002")
        both = (AgentType.RUNNING, "cl_c", "00000000000003")
        add_dismissed_agents({keep, drop, both})

        result = update_dismissed_agents(additions={both}, removals={drop, both})

        assert result == {keep, both}
        assert load_dismissed_agents() == {keep, both}


def test_update_dismissed_agents_without_changes_does_not_write(
    tmp_path: Path,
) -> None:
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        assert update_dismissed_agents() == set()
        assert not test_file.exists()


def test_concurrent_additions_from_threads_lose_nothing(tmp_path: Path) -> None:
    """Writers adding disjoint identities at once must all reach disk."""
    import threading

    test_file = tmp_path / "dismissed_agents.json"
    per_thread = 25
    thread_count = 8
    expected = {
        (AgentType.RUNNING, f"cl_{t}", f"{i:014d}")
        for t in range(thread_count)
        for i in range(per_thread)
    }
    errors: list[BaseException] = []

    def _writer(t: int) -> None:
        try:
            for i in range(per_thread):
                add_dismissed_agents({(AgentType.RUNNING, f"cl_{t}", f"{i:014d}")})
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assert
            errors.append(exc)

    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        threads = [
            threading.Thread(target=_writer, args=(t,)) for t in range(thread_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        assert load_dismissed_agents() == expected


def test_concurrent_additions_from_processes_lose_nothing(tmp_path: Path) -> None:
    """Separate processes (persist-cleanup procs, runners) compose too."""
    import subprocess
    import sys

    test_file = tmp_path / "dismissed_agents.json"
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from sase.ace.dismissed_agents_state import add_dismissed_agents\n"
        "from sase.core.agent_types import AgentType\n"
        "path, tag = Path(sys.argv[1]), sys.argv[2]\n"
        "for i in range(20):\n"
        "    add_dismissed_agents(path, {(AgentType.RUNNING, tag, f'{i:014d}')})\n"
    )
    procs = [
        subprocess.Popen([sys.executable, "-c", script, str(test_file), f"proc_{n}"])
        for n in range(4)
    ]
    for proc in procs:
        assert proc.wait(timeout=120) == 0

    expected = {
        (AgentType.RUNNING, f"proc_{n}", f"{i:014d}")
        for n in range(4)
        for i in range(20)
    }
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        assert load_dismissed_agents() == expected


def test_update_raises_when_the_index_cannot_be_written(tmp_path: Path) -> None:
    """A failed write is reported instead of pretending the merge landed."""
    import pytest

    blocker = tmp_path / "not_a_dir"
    blocker.write_text("file in the way")
    test_file = blocker / "dismissed_agents.json"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file),
        pytest.raises(OSError),
    ):
        add_dismissed_agents({(AgentType.RUNNING, "cl_a", "00000000000001")})
