"""Wait and retry derived-name tests for sase.agent.names."""

from pathlib import Path
from unittest.mock import patch

from sase.agent.names import (
    allocate_retry_name,
    allocate_wait_name,
    allocate_wait_names,
    single_wait_agent_name,
)

from tests._agent_names_fixtures import make_agent as _make_agent


class TestWaitDerivedAgentNames:
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
            assert allocate_wait_name("foo") == "foo.w1"

    def test_allocates_wait_slot_gap(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.w1", done=True)
        _make_agent(tmp_path, "proj", "run3", "foo.w3", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_wait_name("foo") == "foo.w2"

    def test_suffixed_descendants_reserve_wait_slot(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.w1.codex", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_wait_name("foo") == "foo.w2"

    def test_resume_descendants_do_not_reserve_wait_slot(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.f1.codex", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_wait_name("foo") == "foo.w1"

    def test_allocates_multiple_wait_names_from_one_snapshot(
        self, tmp_path: Path
    ) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.w1", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_wait_names("foo", 3) == ["foo.w2", "foo.w3", "foo.w4"]


class TestRetryAgentNames:
    def test_allocates_first_retry_slot(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_retry_name("foo") == "foo.r1"

    def test_skips_retry_slots_reserved_by_descendants(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo", done=True)
        _make_agent(tmp_path, "proj", "run2", "foo.r1", done=True)
        _make_agent(tmp_path, "proj", "run3", "foo.r2.plan", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_retry_name("foo") == "foo.r3"

    def test_legacy_numeric_names_do_not_reserve_retry_slots(
        self, tmp_path: Path
    ) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.1", done=True)
        _make_agent(tmp_path, "proj", "run2", "foo.2.plan", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_retry_name("foo") == "foo.r1"

    def test_chains_allocations_through_reserved_set(self) -> None:
        reserved = {"foo", "foo.r1.plan"}
        assert allocate_retry_name("foo", reserved=reserved) == "foo.r2"
        assert allocate_retry_name("foo", reserved=reserved) == "foo.r3"
        assert reserved == {"foo", "foo.r1.plan", "foo.r2", "foo.r3"}
