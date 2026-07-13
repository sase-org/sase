"""Wait and retry derived-name tests for sase.agent.names."""

from pathlib import Path
from unittest.mock import patch

from sase.agent.names import (
    allocate_retry_name,
    allocate_wait_name,
    allocate_wait_names,
    retry_agent_name_template,
    single_wait_agent_name,
    wait_agent_name_template,
)

from tests._agent_names_fixtures import make_agent as _make_agent


class TestWaitDerivedAgentNames:
    def test_wait_template_uses_natural_marker_shape(self) -> None:
        assert wait_agent_name_template("foo") == "foo.w@"

    def test_single_wait_agent_name_finds_explicit_waits(self) -> None:
        assert single_wait_agent_name("%wait:foo do work") == "foo"
        assert single_wait_agent_name("%w(foo) do work") == "foo"
        assert single_wait_agent_name("%wait:`foo bar` do work") == "foo bar"

    def test_single_wait_agent_name_requires_one_explicit_dependency(self) -> None:
        assert single_wait_agent_name("%wait:foo\n%wait:bar\nwork") is None
        assert single_wait_agent_name("%wait:foo,bar\nwork") is None
        assert single_wait_agent_name("%wait(time=5m)\nwork") is None
        assert single_wait_agent_name("%wait\nwork") is None

    def test_single_wait_agent_name_ignores_fenced_and_disabled_regions(self) -> None:
        prompt = (
            "%wait:real\n"
            "```\n%wait:fenced\n```\n"
            "%xprompts_enabled:false\n%wait:disabled\n%xprompts_enabled:true\n"
        )
        assert single_wait_agent_name(prompt) == "real"

    def test_allocates_first_wait_slot(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_wait_name("foo") == "foo.w0"

    def test_allocates_wait_slot_gap(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.w0", done=True)
        _make_agent(tmp_path, "proj", "run3", "foo.w2", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_wait_name("foo") == "foo.w1"

    def test_suffixed_descendants_reserve_wait_slot(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.w0.codex", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_wait_name("foo") == "foo.w1"

    def test_resume_descendants_do_not_reserve_wait_slot(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.f0.codex", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_wait_name("foo") == "foo.w0"

    def test_historical_no_dash_numeric_descendant_reserves_wait_slot(self) -> None:
        reserved = {"foo.w0", "foo.w1.codex"}

        assert allocate_wait_name("foo", reserved=reserved) == "foo.w2"

    def test_historical_dash_numeric_descendant_does_not_reserve_wait_slot(
        self,
    ) -> None:
        reserved = {"foo.w0", "foo.w-1.codex"}

        assert allocate_wait_name("foo", reserved=reserved) == "foo.w1"

    def test_historical_dash_letter_descendant_reserves_wait_slot(self) -> None:
        reserved = {
            *(f"foo.w{token}" for token in "0123456789"),
            "foo.w-a.codex",
        }

        assert allocate_wait_name("foo", reserved=reserved) == "foo.w-b"

    def test_wait_allocation_inserts_dash_at_letter_boundary(self) -> None:
        reserved: set[str] = set()

        assert [allocate_wait_name("foo", reserved=reserved) for _ in range(11)] == [
            "foo.w0",
            "foo.w1",
            "foo.w2",
            "foo.w3",
            "foo.w4",
            "foo.w5",
            "foo.w6",
            "foo.w7",
            "foo.w8",
            "foo.w9",
            "foo.w-a",
        ]

    def test_allocates_multiple_wait_names_from_one_snapshot(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_wait_names("foo", 3) == [
                "foo.w0",
                "foo.w1",
                "foo.w2",
            ]


class TestRetryAgentNames:
    def test_retry_template_uses_natural_marker_shape(self) -> None:
        assert retry_agent_name_template("foo") == "foo.r@"

    def test_allocates_first_retry_slot(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_retry_name("foo") == "foo.r0"

    def test_skips_retry_slots_reserved_by_descendants(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo", done=True)
        _make_agent(tmp_path, "proj", "run2", "foo.r0", done=True)
        _make_agent(tmp_path, "proj", "run3", "foo.r1.plan", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_retry_name("foo") == "foo.r2"

    def test_legacy_numeric_names_do_not_reserve_retry_slots(
        self, tmp_path: Path
    ) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.1", done=True)
        _make_agent(tmp_path, "proj", "run2", "foo.2.plan", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_retry_name("foo") == "foo.r0"

    def test_historical_no_dash_numeric_descendant_reserves_retry_slot(self) -> None:
        reserved = {"foo.r0", "foo.r1.plan"}

        assert allocate_retry_name("foo", reserved=reserved) == "foo.r2"

    def test_historical_dash_numeric_descendant_does_not_reserve_retry_slot(
        self,
    ) -> None:
        reserved = {"foo.r0", "foo.r-1.plan"}

        assert allocate_retry_name("foo", reserved=reserved) == "foo.r1"

    def test_historical_dash_letter_descendant_reserves_retry_slot(self) -> None:
        reserved = {
            *(f"foo.r{token}" for token in "0123456789"),
            "foo.r-a.plan",
        }

        assert allocate_retry_name("foo", reserved=reserved) == "foo.r-b"

    def test_retry_allocation_inserts_dash_at_letter_boundary(self) -> None:
        reserved: set[str] = set()

        assert [allocate_retry_name("foo", reserved=reserved) for _ in range(11)] == [
            "foo.r0",
            "foo.r1",
            "foo.r2",
            "foo.r3",
            "foo.r4",
            "foo.r5",
            "foo.r6",
            "foo.r7",
            "foo.r8",
            "foo.r9",
            "foo.r-a",
        ]

    def test_chains_allocations_through_reserved_set(self) -> None:
        reserved = {"foo", "foo.r0.plan"}
        assert allocate_retry_name("foo", reserved=reserved) == "foo.r1"
        assert allocate_retry_name("foo", reserved=reserved) == "foo.r2"
        assert reserved == {"foo", "foo.r0.plan", "foo.r1", "foo.r2"}
