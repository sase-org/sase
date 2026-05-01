"""Tests for ID generation."""

import json
from pathlib import Path

import pytest

from sase.bead.ids import (
    IdGenerator,
    from_base36,
    max_child_counter,
    max_top_level_counter,
    to_base36,
)


class TestBase36:
    def test_zero(self) -> None:
        assert to_base36(0) == "0"

    def test_small_numbers(self) -> None:
        assert to_base36(1) == "1"
        assert to_base36(9) == "9"
        assert to_base36(10) == "a"
        assert to_base36(35) == "z"

    def test_larger_numbers(self) -> None:
        assert to_base36(36) == "10"
        assert to_base36(37) == "11"
        assert to_base36(100) == "2s"

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            to_base36(-1)

    def test_roundtrip(self) -> None:
        for n in [0, 1, 35, 36, 100, 999, 10000]:
            assert from_base36(to_base36(n)) == n


class TestIdGenerator:
    def test_first_id(self) -> None:
        gen = IdGenerator("sase", counter=1)
        assert gen.next_id() == "sase-1"

    def test_sequential_ids(self) -> None:
        gen = IdGenerator("proj", counter=1)
        assert gen.next_id() == "proj-1"
        assert gen.next_id() == "proj-2"
        assert gen.next_id() == "proj-3"

    def test_counter_property(self) -> None:
        gen = IdGenerator("x", counter=5)
        assert gen.counter == 5
        gen.next_id()
        assert gen.counter == 6

    def test_custom_start_counter(self) -> None:
        gen = IdGenerator("sase", counter=100)
        assert gen.next_id() == "sase-2s"

    def test_prefix_preserved(self) -> None:
        gen = IdGenerator("my-project", counter=1)
        assert gen.next_id().startswith("my-project-")


class TestWorkspaceCounters:
    def test_max_top_level_counter_scans_valid_ids_only(self, tmp_path: Path) -> None:
        beads_a = tmp_path / "workspace-a" / ".sase_beads"
        beads_b = tmp_path / "workspace-b" / ".sase_beads"
        _write_issue_ids(
            beads_a,
            [
                "sase-1",
                "sase-z",
                "other-100",
                "sase-1.1",
                "sase-not-base36!",
            ],
        )
        _write_issue_ids(beads_b, ["sase-10"])
        with open(beads_b / "issues.jsonl", "a") as f:
            f.write("{not json}\n")

        assert max_top_level_counter("sase", [beads_a, beads_b]) == 36

    def test_max_child_counter_scans_direct_children_only(self, tmp_path: Path) -> None:
        beads_dir = tmp_path / ".sase_beads"
        _write_issue_ids(
            beads_dir,
            [
                "sase-1.1",
                "sase-1.4",
                "sase-1.4.1",
                "sase-10.9",
                "sase-1.not-int",
            ],
        )

        assert max_child_counter("sase-1", [beads_dir]) == 4


def _write_issue_ids(beads_dir: Path, issue_ids: list[str]) -> None:
    beads_dir.mkdir(parents=True, exist_ok=True)
    with open(beads_dir / "issues.jsonl", "w") as f:
        for issue_id in issue_ids:
            f.write(json.dumps({"id": issue_id}) + "\n")
