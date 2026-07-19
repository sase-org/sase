"""Indexed-template tests for agent directive extraction."""

from pathlib import Path
from unittest.mock import patch

from tests._agent_names_extract_fixtures import run_extract
from tests._agent_names_fixtures import make_agent


class TestExtractDirectivesTemplates:
    def test_indexed_name_template_allocates_concrete_name(
        self, tmp_path: Path
    ) -> None:
        make_agent(tmp_path, "proj", "run1", "build-0")

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(tmp_path, prompt="%id:build-@\nDo work")

        assert result["info"].name == "build-1"
        assert result["meta"]["name"] == "build-1"
        assert result["meta"]["agent_name_template"] == "build-@"

    def test_indexed_name_template_uses_matching_planned_name(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                planned_name="build-7",
                prompt="%id:build-@\nDo work",
            )

        assert result["info"].name == "build-7"
        assert result["meta"]["name"] == "build-7"
        assert result["meta"]["agent_name_template"] == "build-@"

    def test_indexed_name_template_ignores_unrelated_planned_name(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                planned_name="other-1",
                prompt="%id:build-@\nDo work",
            )

        assert result["info"].name == "build-0"
        assert result["meta"]["name"] == "build-0"

    def test_agent_name_template_suffix_shape_uses_matching_planned_name(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                planned_name="7.cld",
                prompt="%id:@.cld\nDo work",
            )

        assert result["info"].name == "7.cld"
        assert result["meta"]["name"] == "7.cld"
        assert result["meta"]["agent_name_template"] == "@.cld"

    def test_generated_template_name_uses_planned_name_without_explicit_claim(
        self, tmp_path: Path
    ) -> None:
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch("sase.agent.names.claim_agent_name") as claim,
        ):
            result = run_extract(
                tmp_path,
                planned_name="7.cld",
                generated_name=True,
                prompt="%id:@.cld\nDo work",
            )

        assert result["info"].name == "7.cld"
        assert result["meta"]["name"] == "7.cld"
        assert result["meta"]["agent_name_template"] == "@.cld"
        assert claim.call_args.kwargs["explicit"] is False

    def test_agent_name_template_suffix_shape_falls_back_without_planned_name(
        self, tmp_path: Path
    ) -> None:
        make_agent(tmp_path, "proj", "run1", "0.cld")

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(tmp_path, prompt="%id:@.cld\nDo work")

        assert result["info"].name == "1.cld"
        assert result["meta"]["name"] == "1.cld"
        assert result["meta"]["agent_name_template"] == "@.cld"

    def test_indexed_wait_template_persists_concrete_latest_name(
        self, tmp_path: Path
    ) -> None:
        make_agent(tmp_path, "proj", "run1", "build-1")
        make_agent(tmp_path, "proj", "run2", "build-3")

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(tmp_path, prompt="%wait:build-@\nDo work")

        assert result["info"].wait_names == ["build-3"]
        assert result["meta"]["wait_for"] == ["build-3"]
        assert result["meta"]["name"] == "build-3.w0"

    def test_wait_template_trailing_marker_persists_concrete_latest_name(
        self, tmp_path: Path
    ) -> None:
        make_agent(tmp_path, "proj", "run1", "cld-0")
        make_agent(tmp_path, "proj", "run2", "cld-1")

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(tmp_path, prompt="%wait:cld-@\nDo work")

        assert result["info"].wait_names == ["cld-1"]
        assert result["meta"]["wait_for"] == ["cld-1"]
        assert result["meta"]["name"] == "cld-1.w0"

    def test_indexed_wait_resolves_before_same_segment_indexed_name(
        self, tmp_path: Path
    ) -> None:
        make_agent(tmp_path, "proj", "run1", "build-0")

        with patch.object(Path, "home", return_value=tmp_path):
            result = run_extract(
                tmp_path,
                prompt="%wait:build-@\n%id:build-@\nDo work",
            )

        assert result["info"].wait_names == ["build-0"]
        assert result["meta"]["wait_for"] == ["build-0"]
        assert result["meta"]["name"] == "build-1"
