"""Resume and fork reference tests for sase.agent.names."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    AgentNameTemplateNotFoundError,
    allocate_resume_name,
    allocate_resume_names,
    first_fork_agent_name,
    first_resume_agent_name,
    fork_agent_names,
    has_fork_reference,
    resume_agent_name_template,
    resolve_resume_agent_name,
    sole_resume_agent_name,
)
from sase.core.agent_tribe import InvalidTribeError

from tests._agent_names_fixtures import make_agent as _make_agent


class TestResumeAgentNames:
    def test_resume_template_uses_natural_marker_shape(self) -> None:
        assert resume_agent_name_template("foo") == "foo.f@"

    def test_finds_resume_colon_paren_and_backtick(self) -> None:
        assert first_resume_agent_name("#fork:foo do work") == "foo"
        assert first_resume_agent_name("#fork(foo) do work") == "foo"
        assert first_resume_agent_name("#fork:`foo bar` do work") == "foo bar"

    def test_accepts_legacy_resume_references(self) -> None:
        assert first_resume_agent_name("#resume:foo do work") == "foo"
        assert first_resume_agent_name("#resume(foo) do work") == "foo"
        assert first_resume_agent_name("#resume:`foo bar` do work") == "foo bar"

    def test_ignores_fork_by_chat(self) -> None:
        assert first_resume_agent_name("#fork_by_chat:foo.md") is None
        assert first_resume_agent_name("#resume_by_chat:foo.md") is None

    def test_ignores_fenced_and_disabled_regions(self) -> None:
        prompt = (
            "```\n#fork:fenced\n```\n"
            "%xprompts_enabled:false\n#fork:disabled\n%xprompts_enabled:true\n"
            "#fork:real"
        )
        assert first_resume_agent_name(prompt) == "real"

    def test_first_resume_wins(self) -> None:
        assert first_resume_agent_name("#fork:first then #fork:second") == "first"

    @pytest.mark.parametrize(
        "prompt",
        ["#fork:planner,coder do work", "#fork(planner, coder) do work"],
    )
    def test_multi_parent_fork_exposes_all_parents_but_no_naming_parent(
        self, prompt: str
    ) -> None:
        assert fork_agent_names(prompt) == ["planner", "coder"]
        assert sole_resume_agent_name(prompt) is None

    def test_fork_parent_list_is_ordered_and_deduplicated(self) -> None:
        assert fork_agent_names("#fork:planner,coder,planner") == [
            "planner",
            "coder",
        ]

    def test_single_parent_remains_the_sole_naming_parent(self) -> None:
        assert fork_agent_names("#fork:planner") == ["planner"]
        assert sole_resume_agent_name("#fork:planner") == "planner"

    @pytest.mark.parametrize(
        "prompt",
        ["#fork:@epic", "#fork(@epic)", "#fork:`@epic`"],
    )
    def test_tribe_fork_passes_through_without_naming_parent(self, prompt: str) -> None:
        assert fork_agent_names(prompt) == ["@epic"]
        assert first_fork_agent_name(prompt) == "@epic"
        assert sole_resume_agent_name(prompt) is None

    def test_tribe_fork_mixes_with_named_parent(self) -> None:
        assert fork_agent_names("#fork:@epic,builder") == ["@epic", "builder"]
        assert sole_resume_agent_name("#fork:@epic,builder") is None

    @pytest.mark.parametrize("reference", ["#fork:@", "#fork:@bad+name"])
    def test_malformed_tribe_fork_is_rejected(self, reference: str) -> None:
        with pytest.raises(InvalidTribeError):
            fork_agent_names(reference)

    def test_first_fork_finds_colon_paren_and_backtick(self) -> None:
        assert first_fork_agent_name("#fork:foo do work") == "foo"
        assert first_fork_agent_name("#fork(foo) do work") == "foo"
        assert first_fork_agent_name("#fork:`foo bar` do work") == "foo bar"

    def test_first_fork_ignores_legacy_resume_references(self) -> None:
        assert first_fork_agent_name("#resume:foo do work") is None
        assert first_fork_agent_name("#resume(foo) do work") is None

    def test_first_fork_ignores_fork_by_chat_and_bare_fork(self) -> None:
        assert first_fork_agent_name("#fork_by_chat:foo.md") is None
        assert first_fork_agent_name("#fork do work") is None
        assert first_fork_agent_name("#fork() do work") is None

    def test_first_fork_ignores_fenced_and_disabled_regions(self) -> None:
        prompt = (
            "```\n#fork:fenced\n```\n"
            "%xprompts_enabled:false\n#fork:disabled\n%xprompts_enabled:true\n"
            "#fork:real"
        )
        assert first_fork_agent_name(prompt) == "real"

    def test_first_fork_wins(self) -> None:
        assert first_fork_agent_name("#fork:first then #fork:second") == "first"

    def test_first_fork_resolves_template_reference(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "build-1")
        _make_agent(tmp_path, "proj", "run2", "build-4")

        with patch.object(Path, "home", return_value=tmp_path):
            assert first_fork_agent_name("#fork:build-@ do work") == "build-4"

    def test_has_fork_reference_finds_colon_paren_and_backtick(self) -> None:
        assert has_fork_reference("#fork:foo do work") is True
        assert has_fork_reference("#fork(foo) do work") is True
        assert has_fork_reference("#fork:`foo bar` do work") is True

    def test_has_fork_reference_ignores_non_explicit_forks(self) -> None:
        assert has_fork_reference("#resume:foo do work") is False
        assert has_fork_reference("#resume(foo) do work") is False
        assert has_fork_reference("#fork_by_chat:foo.md") is False
        assert has_fork_reference("#fork do work") is False
        assert has_fork_reference("#fork() do work") is False

    def test_has_fork_reference_ignores_fenced_and_disabled_regions(self) -> None:
        prompt = (
            "```\n#fork:fenced\n```\n"
            "%xprompts_enabled:false\n#fork:disabled\n%xprompts_enabled:true\n"
            "#fork:real"
        )
        assert has_fork_reference(prompt) is True

        prompt_without_live_fork = (
            "```\n#fork:fenced\n```\n"
            "%xprompts_enabled:false\n#fork:disabled\n%xprompts_enabled:true\n"
        )
        assert has_fork_reference(prompt_without_live_fork) is False

    def test_has_fork_reference_does_not_resolve_templates(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert has_fork_reference("#fork:build-@ do work") is True

    def test_template_resume_reference_resolves_latest_concrete_name(
        self, tmp_path: Path
    ) -> None:
        _make_agent(tmp_path, "proj", "run1", "build-1")
        _make_agent(tmp_path, "proj", "run2", "build-4")

        with patch.object(Path, "home", return_value=tmp_path):
            assert first_resume_agent_name("#fork:build-@ do work") == "build-4"
            assert first_resume_agent_name("#resume(build-@) do work") == "build-4"

    def test_template_suffix_resume_reference_resolves_latest_concrete_name(
        self, tmp_path: Path
    ) -> None:
        _make_agent(tmp_path, "proj", "run1", "cld.0")
        _make_agent(tmp_path, "proj", "run2", "cld.1")

        with patch.object(Path, "home", return_value=tmp_path):
            assert first_resume_agent_name("#fork:cld.@ do work") == "cld.1"

    def test_allocates_first_resume_slot(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("foo") == "foo.f0"

    def test_allocates_resume_slot_gap(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.f0", done=True)
        _make_agent(tmp_path, "proj", "run3", "foo.f2", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("foo") == "foo.f1"

    def test_suffixed_descendants_reserve_resume_slot(self, tmp_path: Path) -> None:
        _make_agent(tmp_path, "proj", "run1", "foo.f0.cld", done=True)
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_name("foo") == "foo.f1"

    def test_historical_no_dash_numeric_descendant_reserves_fork_slot(self) -> None:
        reserved = {"foo.f0", "foo.f1.cld"}

        assert allocate_resume_name("foo", reserved=reserved) == "foo.f2"

    def test_historical_dash_numeric_descendant_does_not_reserve_fork_slot(
        self,
    ) -> None:
        reserved = {"foo.f0", "foo.f-1.cld"}

        assert allocate_resume_name("foo", reserved=reserved) == "foo.f1"

    def test_historical_dash_letter_descendant_reserves_fork_slot(self) -> None:
        reserved = {
            *(f"foo.f{token}" for token in "0123456789"),
            "foo.f-a.cld",
        }

        assert allocate_resume_name("foo", reserved=reserved) == "foo.f-b"

    def test_fork_allocation_inserts_dash_at_letter_boundary(self) -> None:
        reserved: set[str] = set()

        assert [allocate_resume_name("foo", reserved=reserved) for _ in range(11)] == [
            "foo.f0",
            "foo.f1",
            "foo.f2",
            "foo.f3",
            "foo.f4",
            "foo.f5",
            "foo.f6",
            "foo.f7",
            "foo.f8",
            "foo.f9",
            "foo.f-a",
        ]

    def test_allocates_multiple_resume_names_from_one_snapshot(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            assert allocate_resume_names("foo", 3) == [
                "foo.f0",
                "foo.f1",
                "foo.f2",
            ]

    def test_resolve_resume_root_uses_latest_completed_family_member(
        self, tmp_path: Path
    ) -> None:
        _make_agent(
            tmp_path,
            "proj",
            "20260506010000",
            "family",
            done=True,
            outcome="completed",
        )
        _make_agent(
            tmp_path,
            "proj",
            "20260506010101",
            "family",
            workflow_name="family",
            agent_family="family",
            role_suffix="-plan",
            done=True,
            outcome="completed",
        )
        child_dir = _make_agent(
            tmp_path,
            "proj",
            "20260506010202",
            "family-code",
            workflow_name="family",
            agent_family="family",
            role_suffix="-code",
            parent_timestamp="20260506010101",
            done=True,
            outcome="completed",
        )

        with patch.object(Path, "home", return_value=tmp_path):
            result = resolve_resume_agent_name("family")

        assert result is not None
        assert result.name == "family-code"
        assert result.artifacts_dir == str(child_dir)

    def test_resolve_resume_child_keeps_exact_reference(self, tmp_path: Path) -> None:
        child_dir = _make_agent(
            tmp_path,
            "proj",
            "20260506010202",
            "family-code",
            workflow_name="family",
            agent_family="family",
            role_suffix="-code",
            parent_timestamp="20260506010101",
            done=True,
            outcome="completed",
        )

        with patch.object(Path, "home", return_value=tmp_path):
            result = resolve_resume_agent_name("family-code")

        assert result is not None
        assert result.artifacts_dir == str(child_dir)

    def test_resolve_resume_template_uses_latest_concrete_name(
        self, tmp_path: Path
    ) -> None:
        _make_agent(
            tmp_path,
            "proj",
            "20260506010101",
            "build-1",
            done=True,
            outcome="completed",
        )
        latest_dir = _make_agent(
            tmp_path,
            "proj",
            "20260506010202",
            "build-3",
            done=True,
            outcome="completed",
        )

        with patch.object(Path, "home", return_value=tmp_path):
            result = resolve_resume_agent_name("build-@")

        assert result is not None
        assert result.name == "build-3"
        assert result.artifacts_dir == str(latest_dir)

    def test_resolve_resume_template_suffix_uses_latest_concrete_name(
        self, tmp_path: Path
    ) -> None:
        _make_agent(
            tmp_path,
            "proj",
            "20260506010101",
            "0.cld",
            done=True,
            outcome="completed",
        )
        latest_dir = _make_agent(
            tmp_path,
            "proj",
            "20260506010202",
            "1.cld",
            done=True,
            outcome="completed",
        )

        with patch.object(Path, "home", return_value=tmp_path):
            result = resolve_resume_agent_name("@.cld")

        assert result is not None
        assert result.name == "1.cld"
        assert result.artifacts_dir == str(latest_dir)

    def test_first_resume_template_without_existing_name_raises(
        self, tmp_path: Path
    ) -> None:
        with (
            patch.object(Path, "home", return_value=tmp_path),
            pytest.raises(AgentNameTemplateNotFoundError, match="build-@"),
        ):
            first_resume_agent_name("#fork:build-@")
