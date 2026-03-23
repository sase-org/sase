"""Tests for project-local xprompt loading in TUI panels."""

from pathlib import Path
from unittest.mock import patch

from sase.xprompt._parsing import extract_project_from_vcs_tag
from sase.xprompt.loader import (
    get_all_project_local_prompts,
    get_known_project_workspaces,
    load_project_local_xprompts,
)


# --- extract_project_from_vcs_tag ---


class TestExtractProjectFromVcsTag:
    def test_colon_format(self) -> None:
        assert extract_project_from_vcs_tag("#gh:sase ") == "sase"

    def test_colon_format_hg(self) -> None:
        assert extract_project_from_vcs_tag("#hg:myproject ") == "myproject"

    def test_hitl_bang_suffix(self) -> None:
        assert extract_project_from_vcs_tag("#gh!!:sase ") == "sase"

    def test_hitl_question_suffix(self) -> None:
        assert extract_project_from_vcs_tag("#gh??:sase ") == "sase"

    def test_paren_format(self) -> None:
        assert extract_project_from_vcs_tag("#git(myrepo) ") == "myrepo"

    def test_plus_format_returns_none(self) -> None:
        assert extract_project_from_vcs_tag("#gh+ ") is None

    def test_bare_tag_returns_none(self) -> None:
        assert extract_project_from_vcs_tag("#gh ") is None

    def test_no_hash_returns_none(self) -> None:
        assert extract_project_from_vcs_tag("gh:sase ") is None

    def test_empty_colon_ref(self) -> None:
        assert extract_project_from_vcs_tag("#gh: ") is None

    def test_empty_paren_ref(self) -> None:
        assert extract_project_from_vcs_tag("#git() ") is None

    def test_hyphenated_project(self) -> None:
        assert extract_project_from_vcs_tag("#gh:sase-org ") == "sase-org"


# --- get_known_project_workspaces ---


class TestGetKnownProjectWorkspaces:
    def test_reads_workspace_dir_from_gp_files(self, tmp_path: Path) -> None:
        proj_dir = tmp_path / "myproj"
        proj_dir.mkdir()
        gp = proj_dir / "myproj.gp"
        ws = tmp_path / "workspace"
        ws.mkdir()
        gp.write_text(f"WORKSPACE_DIR: {ws}\n")

        with patch.object(Path, "home", return_value=tmp_path):
            # Patch projects dir to be tmp_path (since home()/.sase/projects)
            sase_dir = tmp_path / ".sase" / "projects"
            sase_dir.mkdir(parents=True)
            real_proj_dir = sase_dir / "myproj"
            real_proj_dir.mkdir()
            real_gp = real_proj_dir / "myproj.gp"
            real_gp.write_text(f"WORKSPACE_DIR: {ws}\n")

            result = get_known_project_workspaces()
            assert "myproj" in result
            assert result["myproj"] == ws

    def test_skips_missing_workspace_dir(self, tmp_path: Path) -> None:
        sase_dir = tmp_path / ".sase" / "projects" / "bad"
        sase_dir.mkdir(parents=True)
        gp = sase_dir / "bad.gp"
        gp.write_text("WORKSPACE_DIR: /nonexistent/path\n")

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_known_project_workspaces()
            assert "bad" not in result

    def test_empty_projects_dir(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = get_known_project_workspaces()
            assert result == {}


# --- load_project_local_xprompts ---


class TestLoadProjectLocalXprompts:
    def test_loads_xprompts_from_sase_yml(self, tmp_path: Path) -> None:
        sase_yml = tmp_path / "sase.yml"
        sase_yml.write_text(
            "xprompts:\n"
            "  docs: 'Write documentation for the code'\n"
            "  test: 'Write tests for the code'\n"
        )

        result = load_project_local_xprompts(tmp_path, "myproj")
        assert "myproj/docs" in result
        assert "myproj/test" in result
        assert result["myproj/docs"].content == "Write documentation for the code"
        assert result["myproj/docs"].source_path == "project_local_config:myproj"

    def test_empty_xprompts_section(self, tmp_path: Path) -> None:
        sase_yml = tmp_path / "sase.yml"
        sase_yml.write_text("xprompts:\n")

        result = load_project_local_xprompts(tmp_path, "myproj")
        assert result == {}

    def test_no_sase_yml(self, tmp_path: Path) -> None:
        result = load_project_local_xprompts(tmp_path, "myproj")
        assert result == {}

    def test_no_xprompts_key(self, tmp_path: Path) -> None:
        sase_yml = tmp_path / "sase.yml"
        sase_yml.write_text("some_other_key: value\n")

        result = load_project_local_xprompts(tmp_path, "myproj")
        assert result == {}

    def test_structured_xprompt_entry(self, tmp_path: Path) -> None:
        sase_yml = tmp_path / "sase.yml"
        sase_yml.write_text(
            "xprompts:\n"
            "  review:\n"
            "    input:\n"
            "      file: str\n"
            "    content: 'Review the file {{file}}'\n"
        )

        result = load_project_local_xprompts(tmp_path, "proj")
        assert "proj/review" in result
        assert result["proj/review"].content == "Review the file {{file}}"
        assert len(result["proj/review"].inputs) == 1


# --- get_all_project_local_prompts ---


class TestGetAllProjectLocalPrompts:
    def test_aggregates_from_multiple_projects(self, tmp_path: Path) -> None:
        # Set up two project workspaces with sase.yml
        ws1 = tmp_path / "ws1"
        ws1.mkdir()
        (ws1 / "sase.yml").write_text("xprompts:\n  foo: 'Foo content'\n")

        ws2 = tmp_path / "ws2"
        ws2.mkdir()
        (ws2 / "sase.yml").write_text("xprompts:\n  bar: 'Bar content'\n")

        with patch(
            "sase.xprompt.loader.get_known_project_workspaces",
            return_value={"proj1": ws1, "proj2": ws2},
        ):
            result = get_all_project_local_prompts()

        assert "proj1/foo" in result
        assert "proj2/bar" in result
        # Results are Workflow objects
        assert result["proj1/foo"].get_prompt_part_content() == "Foo content"
        assert result["proj2/bar"].get_prompt_part_content() == "Bar content"

    def test_empty_when_no_projects(self) -> None:
        with patch(
            "sase.xprompt.loader.get_known_project_workspaces",
            return_value={},
        ):
            result = get_all_project_local_prompts()
            assert result == {}


# --- classify_source for project_local_config ---


class TestClassifySourceProjectLocal:
    def test_project_local_config_source(self) -> None:
        from sase.ace.tui.modals.xprompt_browser_helpers import classify_source

        cat, display, editable = classify_source("project_local_config:sase")
        assert cat == "Project (sase) sase.yml"
        assert "sase" in display
        assert editable is True

    def test_project_local_config_resolve(self, tmp_path: Path) -> None:
        from sase.ace.tui.modals.xprompt_browser_helpers import (
            resolve_source_to_file_path,
        )

        with patch(
            "sase.xprompt.loader.get_known_project_workspaces",
            return_value={"myproj": tmp_path},
        ):
            result = resolve_source_to_file_path("project_local_config:myproj")
            assert result == str(tmp_path / "sase.yml")
