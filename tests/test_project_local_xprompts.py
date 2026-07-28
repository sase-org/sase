"""Tests for project-local xprompt loading in TUI panels."""

from pathlib import Path
from unittest.mock import patch

from sase.xprompt._parsing import extract_project_from_vcs_tag
from sase.xprompt.loader import (
    get_all_prompts,
    get_all_project_local_prompts,
    get_all_xprompts,
    get_known_project_workspaces,
    load_project_local_xprompts,
)
from sase.xprompt.models import XPrompt
from sase.xprompt.processor import process_xprompt_references


# --- extract_project_from_vcs_tag ---


class TestExtractProjectFromVcsTag:
    def test_colon_format(self) -> None:
        assert extract_project_from_vcs_tag("#gh:sase ") == "sase"

    def test_colon_format_git(self) -> None:
        assert extract_project_from_vcs_tag("#git:myproject ") == "myproject"

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
        gp = proj_dir / "myproj.sase"
        ws = tmp_path / "workspace"
        ws.mkdir()
        gp.write_text(f"WORKSPACE_DIR: {ws}\n")

        with patch.object(Path, "home", return_value=tmp_path):
            # Patch projects dir to be tmp_path (since home()/.sase/projects)
            sase_dir = tmp_path / ".sase" / "projects"
            sase_dir.mkdir(parents=True)
            real_proj_dir = sase_dir / "myproj"
            real_proj_dir.mkdir()
            real_gp = real_proj_dir / "myproj.sase"
            real_gp.write_text(f"WORKSPACE_DIR: {ws}\n")

            result = get_known_project_workspaces()
            assert "myproj" in result
            assert result["myproj"] == ws

    def test_skips_missing_workspace_dir(self, tmp_path: Path) -> None:
        sase_dir = tmp_path / ".sase" / "projects" / "bad"
        sase_dir.mkdir(parents=True)
        gp = sase_dir / "bad.sase"
        gp.write_text("WORKSPACE_DIR: /nonexistent/path\n")

        with patch.object(Path, "home", return_value=tmp_path):
            result = get_known_project_workspaces()
            assert "bad" not in result

    def test_defaults_to_active_project_workspaces(self, tmp_path: Path) -> None:
        active_ws = tmp_path / "active_ws"
        inactive_ws = tmp_path / "inactive_ws"
        active_ws.mkdir()
        inactive_ws.mkdir()
        projects = tmp_path / ".sase" / "projects"
        active_dir = projects / "active"
        inactive_dir = projects / "inactive"
        active_dir.mkdir(parents=True)
        inactive_dir.mkdir(parents=True)
        (active_dir / "active.sase").write_text(f"WORKSPACE_DIR: {active_ws}\n")
        (inactive_dir / "inactive.sase").write_text(
            f"PROJECT_STATE: inactive\nWORKSPACE_DIR: {inactive_ws}\n"
        )

        with patch.object(Path, "home", return_value=tmp_path):
            assert get_known_project_workspaces() == {"active": active_ws}
            assert get_known_project_workspaces(include_states="all") == {
                "active": active_ws,
                "inactive": inactive_ws,
            }

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


class TestRegistryBackedProjectResolution:
    @staticmethod
    def _isolate_loader(monkeypatch, workspace: Path | None) -> None:
        from sase.xprompt import loader, processor

        namespaces = {} if workspace is None else {"proj": workspace}
        monkeypatch.setattr(loader, "canonical_xprompt_project", lambda ref: ref)
        monkeypatch.setattr(loader, "known_project_namespaces", lambda: namespaces)
        monkeypatch.setattr(loader, "detect_project", lambda: None)
        monkeypatch.setattr(loader, "load_xprompts_from_internal", lambda: {})
        monkeypatch.setattr(loader, "load_xprompts_from_default_files", lambda: {})
        monkeypatch.setattr(loader, "load_xprompts_from_plugins", lambda: {})
        monkeypatch.setattr(loader, "load_xprompts_from_config", lambda project: {})
        monkeypatch.setattr(loader, "load_xprompts_from_project", lambda project: {})
        monkeypatch.setattr(loader, "load_xprompts_from_files", lambda project: {})
        monkeypatch.setattr(
            "sase.xprompt.workflow_loader.get_all_workflows",
            lambda project=None: {},
        )
        monkeypatch.setattr(
            processor,
            "canonical_xprompt_project",
            lambda ref: ref,
        )
        monkeypatch.setattr(
            processor,
            "known_project_namespaces",
            lambda: namespaces,
        )
        monkeypatch.setattr(processor, "resolve_xprompt_aliases", lambda prompt: prompt)

    def test_loads_and_expands_project_xprompt_outside_workspace(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        workspace = tmp_path / "primary"
        xprompts_dir = workspace / "sase" / "xprompts"
        xprompts_dir.mkdir(parents=True)
        (xprompts_dir / "thing.md").write_text(
            "Registry-backed body.\n",
            encoding="utf-8",
        )
        outside = tmp_path / "outside"
        outside.mkdir()
        monkeypatch.chdir(outside)
        self._isolate_loader(monkeypatch, workspace)

        prompts = get_all_prompts(project="proj")

        assert prompts["proj/thing"].get_prompt_part_content().strip() == (
            "Registry-backed body."
        )
        assert process_xprompt_references("#proj/thing").strip() == (
            "Registry-backed body."
        )

    def test_current_checkout_copy_wins_without_registry_read(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        primary = tmp_path / "primary"
        primary.mkdir()
        self._isolate_loader(monkeypatch, primary)

        from sase.xprompt import loader

        monkeypatch.setattr(loader, "detect_project", lambda: "proj")
        monkeypatch.setattr(
            loader,
            "load_xprompts_from_files",
            lambda project: {
                "proj/thing": XPrompt(
                    name="proj/thing",
                    content="Alternate checkout body.",
                )
            },
        )
        registry_loader = patch(
            "sase.xprompt.loader.load_project_file_xprompts",
            side_effect=AssertionError("registry copy should not be read"),
        )

        with registry_loader:
            xprompts = get_all_xprompts(project="proj")

        assert xprompts["proj/thing"].content == "Alternate checkout body."

    def test_disabled_project_stays_unresolved(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        self._isolate_loader(monkeypatch, None)
        monkeypatch.chdir(tmp_path)

        assert "proj/thing" not in get_all_xprompts(project="proj")
        assert process_xprompt_references("#proj/thing") == "#proj/thing"


# --- classify_source for project_local_config ---


class TestClassifySourceProjectLocal:
    def test_project_local_config_source(self) -> None:
        from sase.ace.tui.modals.xprompt_browser_helpers import classify_source

        cat, display, editable = classify_source("project_local_config:sase")
        assert cat == "Project (sase) sase.yml"
        assert "sase" in display
        assert editable is True

    def test_project_local_config_source_humanizes_project_key(
        self,
        monkeypatch,
        project_display_case,
    ) -> None:
        from sase.ace.tui.modals import xprompt_browser_helpers as helpers

        monkeypatch.setattr(
            helpers,
            "project_display_name_for",
            lambda key: (
                project_display_case.project_label
                if key == project_display_case.project_key
                else key
            ),
        )

        category, _display, _editable = helpers.classify_source(
            f"project_local_config:{project_display_case.project_key}"
        )

        assert category == f"Project ({project_display_case.project_label}) sase.yml"
        assert project_display_case.project_key not in category

    def test_project_local_config_resolve(self, tmp_path: Path) -> None:
        from sase.ace.tui.modals.xprompt_browser_helpers import (
            resolve_source_to_file_path,
        )

        with patch(
            "sase.xprompt.loader.get_known_project_workspaces",
            return_value={"myproj": tmp_path},
        ):
            result = resolve_source_to_file_path("project_local_config:myproj")
            assert result == str(tmp_path / "sase" / "sase.yml")
