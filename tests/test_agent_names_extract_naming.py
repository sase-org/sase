"""Name derivation and precedence tests for agent directive extraction."""

from pathlib import Path
from unittest.mock import patch

from tests._agent_names_extract_fixtures import run_extract


class TestExtractDirectivesNaming:
    def test_resume_prompt_gets_resume_derived_name(self, tmp_path: Path) -> None:
        """A raw top-level #fork picks the first available .f slot."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_multi_parent_fork_gets_neutral_auto_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:planner,coder do stuff",
            )
        assert result["info"].name == "0"
        assert result["meta"].get("name") == "0"

    def test_explicit_name_wins_over_multi_parent_neutral_name(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%name:merged expanded prompt",
                raw_resolved_prompt="%name:merged #fork:planner,coder do stuff",
            )
        assert result["info"].name == "merged"
        assert result["meta"].get("name") == "merged"

    def test_planned_name_wins_for_non_explicit_auto_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="planned",
                prompt="expanded prompt",
            )
        assert result["info"].name == "planned"
        assert result["meta"].get("name") == "planned"

    def test_explicit_name_wins_over_resume(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%name:bar expanded prompt",
                raw_resolved_prompt="%name:bar #fork:foo do stuff",
            )
        assert result["info"].name == "bar"
        assert result["meta"].get("name") == "bar"

    def test_bare_name_uses_resume_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%name expanded prompt",
                raw_resolved_prompt="%name #fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_matching_planned_resume_descendant_name_wins(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.f0.cld",
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0.cld"
        assert result["meta"].get("name") == "foo.f0.cld"

    def test_matching_letter_planned_resume_descendant_name_wins(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.f-a.cld",
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f-a.cld"
        assert result["meta"].get("name") == "foo.f-a.cld"

    def test_noncanonical_planned_resume_descendant_name_is_rejected(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.f-1.cld",
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_auto_dismiss_suppresses_resume_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=True,
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name is None
        assert "name" not in result["meta"]

    def test_wait_prompt_gets_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo do stuff",
            )
        assert result["info"].name == "foo.w0"
        assert result["meta"].get("name") == "foo.w0"

    def test_time_shaped_wait_name_reaches_launch_metadata(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(tmp_path, prompt="%w:4h\nDo work")

        assert result["info"].wait_names == ["4h"]
        assert result["meta"]["wait_for"] == ["4h"]

    def test_explicit_name_wins_over_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%name:bar\n%wait:foo do stuff",
            )
        assert result["info"].name == "bar"
        assert result["meta"].get("name") == "bar"

    def test_resume_name_wins_over_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo expanded prompt",
                raw_resolved_prompt="#fork:bar\n%wait:foo do stuff",
            )
        assert result["info"].name == "bar.f0"
        assert result["meta"].get("name") == "bar.f0"

    def test_resume_name_wins_over_wait_planned_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.w0",
                prompt="%wait:foo expanded prompt",
                raw_resolved_prompt="%wait:foo\n#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_multiple_waits_fall_back_to_auto_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo\n%wait:bar\ndo stuff",
            )
        assert result["info"].name == "0"
        assert result["meta"].get("name") == "0"

    def test_auto_dismiss_suppresses_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=True,
                prompt="%wait:foo do stuff",
            )
        assert result["info"].name is None
        assert "name" not in result["meta"]


class TestExtractDirectivesImplicitForkWait:
    """A top-level #fork:<name> implies %wait:<name> as runner metadata."""

    def test_bare_fork_target_implies_wait(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["meta"].get("wait_for") == ["foo"]
        assert result["info"].wait_names == ["foo"]
        # Fork-derived naming still wins over the implicit wait.
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_multi_parent_fork_waits_for_every_parent(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork(planner, coder) do stuff",
            )
        assert result["meta"].get("wait_for") == ["planner", "coder"]
        assert result["info"].wait_names == ["planner", "coder"]
        assert result["info"].name == "0"

    def test_fork_appends_after_explicit_waits(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:bar expanded prompt",
                raw_resolved_prompt="#fork:foo\n%wait:bar do stuff",
            )
        assert result["meta"].get("wait_for") == ["bar", "foo"]
        assert result["info"].wait_names == ["bar", "foo"]
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_explicit_duplicate_wait_is_not_repeated(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo expanded prompt",
                raw_resolved_prompt="#fork:foo %wait:foo do stuff",
            )
        assert result["meta"].get("wait_for") == ["foo"]
        assert result["info"].wait_names == ["foo"]
        assert result["info"].name == "foo.f0"

    def test_multi_parent_fork_deduplicates_explicit_waits(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:coder expanded prompt",
                raw_resolved_prompt="#fork:planner,coder %wait:coder do stuff",
            )
        assert result["meta"].get("wait_for") == ["coder", "planner"]
        assert result["info"].wait_names == ["coder", "planner"]
        assert result["info"].name == "0"

    def test_bare_fork_without_name_adds_no_implicit_wait(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork do stuff",
            )
        assert "wait_for" not in result["meta"]
        assert result["info"].wait_names == []

    def test_legacy_resume_adds_no_implicit_wait(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#resume:foo do stuff",
            )
        assert "wait_for" not in result["meta"]
        assert result["info"].wait_names == []
