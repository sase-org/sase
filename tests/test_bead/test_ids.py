"""Tests for ID generation."""

import pytest

from sase.bead.ids import IdGenerator, from_base36, to_base36


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
