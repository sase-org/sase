"""Tests for project-based workflow loading in workflow_loader."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.xprompt.workflow_loader import (
    _discover_workflow_files,
    _load_workflow_from_file,
    _load_workflows_from_config,
    get_all_workflows,
)
from sase.xprompt.workflow_models import Workflow


def _load_workflows_from_project_with_base(
    project: str, base_config_dir: Path
) -> dict[str, Workflow]:
    """Helper to test project loading with a custom base directory.

    This replicates the logic of _load_workflows_from_project but allows
    specifying a custom base directory for testing.
    """
    project_dir = base_config_dir / ".config" / "sase" / "xprompts" / project
    if not project_dir.is_dir():
        return {}

    workflows: dict[str, Workflow] = {}
    for yml_file in project_dir.glob("*.yml"):
        if yml_file.is_file():
            workflow = _load_workflow_from_file(yml_file)
            if workflow:
                namespaced_name = f"{project}/{workflow.name}"
                workflows[namespaced_name] = Workflow(
                    name=namespaced_name,
                    inputs=workflow.inputs,
                    steps=workflow.steps,
                    source_path=workflow.source_path,
                )

    for yaml_file in project_dir.glob("*.yaml"):
        if yaml_file.is_file():
            workflow = _load_workflow_from_file(yaml_file)
            if workflow:
                namespaced_name = f"{project}/{workflow.name}"
                if namespaced_name not in workflows:  # .yml takes precedence
                    workflows[namespaced_name] = Workflow(
                        name=namespaced_name,
                        inputs=workflow.inputs,
                        steps=workflow.steps,
                        source_path=workflow.source_path,
                    )
    return workflows


def test_load_workflows_from_project_nonexistent_dir() -> None:
    """Test that nonexistent project directory returns empty dict."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        workflows = _load_workflows_from_project_with_base(
            "nonexistent_project", Path(tmp_dir)
        )
        assert workflows == {}


def test_load_workflows_from_project_with_inputs() -> None:
    """Test that project workflows preserve inputs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        project_dir = Path(tmp_dir) / ".config" / "sase" / "xprompts" / "myproj"
        project_dir.mkdir(parents=True)

        content = """
input:
  target: word
steps:
  - name: greet
    bash: echo "Hello {{ target }}"
"""
        (project_dir / "greet_workflow.yml").write_text(content)

        workflows = _load_workflows_from_project_with_base("myproj", Path(tmp_dir))

        assert len(workflows) == 1
        assert "myproj/greet_workflow" in workflows
        wf = workflows["myproj/greet_workflow"]
        assert wf.name == "myproj/greet_workflow"
        assert len(wf.inputs) == 1
        assert wf.inputs[0].name == "target"


def test_get_all_workflows_without_project_excludes_project_workflows() -> None:
    """Test that get_all_workflows without project param doesn't load project workflows."""
    with (
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_files", return_value={}
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_internal",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_config",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_project"
        ) as mock_load_project,
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_project_workspace"
        ) as mock_load_project_workspace,
        patch("sase.xprompt.workflow_loader.detect_project", return_value=None),
    ):
        get_all_workflows()  # No project param

    # Should not have called _load_workflows_from_project
    mock_load_project.assert_not_called()
    mock_load_project_workspace.assert_not_called()


def test_get_all_workflows_file_overrides_project() -> None:
    """Test that file-based workflows override project workflows."""
    project_workflow = Workflow(
        name="test",
        inputs=[],
        steps=[],
        source_path="/project/test.yml",
    )
    file_workflow = Workflow(
        name="test",
        inputs=[],
        steps=[],
        source_path="/file/test.yml",
    )

    with (
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_files",
            return_value={"test": file_workflow},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_internal",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_config",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_project",
            return_value={"test": project_workflow},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_project_workspace",
            return_value={},
        ),
    ):
        workflows = get_all_workflows(project="testproj")

    # File-based should win
    assert workflows["test"].source_path == "/file/test.yml"


def test_yml_files_discovered_as_workflow_files() -> None:
    """Test that .yml files in search dirs are discovered as workflow files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        search_dir = Path(tmp_dir) / ".xprompts"
        search_dir.mkdir()

        (search_dir / "real_workflow.yml").write_text(
            "steps:\n  - name: step1\n    bash: echo hi\n"
        )

        with patch(
            "sase.xprompt.workflow_loader.get_xprompt_search_paths",
            return_value=[search_dir],
        ):
            discovered = _discover_workflow_files()

        filenames = [path.name for path, _, _ in discovered]
        assert "real_workflow.yml" in filenames


def test_load_workflows_from_config_global_overlay_not_namespaced() -> None:
    """User/overlay config workflows remain global even when a project is detected."""
    workflow_data = {
        "refresh_docs": {
            "input": {"threshold": {"type": "int", "default": 50}},
            "steps": [{"name": "count", "bash": "echo {{ threshold }}"}],
        }
    }

    with patch(
        "sase.xprompt.workflow_loader.load_workflows_by_source",
        return_value=[("config_overlay:sase_athena.yml", workflow_data)],
    ):
        workflows = _load_workflows_from_config(project="sase")

    assert "refresh_docs" in workflows
    assert "sase/refresh_docs" not in workflows
    assert workflows["refresh_docs"].source_path == "config_overlay:sase_athena.yml"
    assert workflows["refresh_docs"].inputs[0].name == "threshold"


def test_load_workflows_from_config_local_config_is_namespaced() -> None:
    """CWD-local sase.yml workflows are namespaced to the detected project."""
    workflow_data = {
        "local_task": {
            "steps": [{"name": "run", "bash": "echo local"}],
        }
    }

    with patch(
        "sase.xprompt.workflow_loader.load_workflows_by_source",
        return_value=[("local_config", workflow_data)],
    ):
        workflows = _load_workflows_from_config(project="sase")

    assert "sase/local_task" in workflows
    workflow = workflows["sase/local_task"]
    assert workflow.name == "sase/local_task"
    assert workflow.source_path == "local_config"


def test_get_all_workflows_config_overrides_plugin_and_file_overrides_config() -> None:
    """Config workflows sit above plugins/internal and below file workflows."""
    plugin_workflow = Workflow(
        name="refresh_docs",
        inputs=[],
        steps=[],
        source_path="plugin:sase/foo.yml",
    )
    config_workflow = Workflow(
        name="refresh_docs",
        inputs=[],
        steps=[],
        source_path="config_overlay:sase_athena.yml",
    )
    file_workflow = Workflow(
        name="refresh_docs",
        inputs=[],
        steps=[],
        source_path="/repo/xprompts/refresh_docs.yml",
    )

    with (
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_internal",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_plugins",
            return_value={"refresh_docs": plugin_workflow},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_config",
            return_value={"refresh_docs": config_workflow},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_project",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_project_workspace",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_files",
            return_value={"refresh_docs": file_workflow},
        ),
    ):
        workflows = get_all_workflows(project="sase")

    assert workflows["refresh_docs"].source_path == "/repo/xprompts/refresh_docs.yml"


def test_get_all_workflows_config_visible_as_refresh_docs() -> None:
    """A config workflow resolves by its global name."""
    config_workflow = Workflow(
        name="refresh_docs",
        inputs=[],
        steps=[],
        source_path="config_overlay:sase_athena.yml",
    )

    with (
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_internal",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_plugins",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_config",
            return_value={"refresh_docs": config_workflow},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_project",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_project_workspace",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_files",
            return_value={},
        ),
    ):
        workflows = get_all_workflows(project="sase")

    assert workflows["refresh_docs"].source_path == "config_overlay:sase_athena.yml"


def test_get_all_workflows_loads_known_project_workspace_from_other_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """Project-scoped workflows load from the known primary checkout."""
    workspace = tmp_path / "sase"
    other_cwd = tmp_path / "other"
    xprompts = workspace / "xprompts"
    xprompts.mkdir(parents=True)
    other_cwd.mkdir()
    (xprompts / "fix_just.yml").write_text(
        "steps:\n  - name: run\n    bash: echo fix\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(other_cwd)

    with (
        patch(
            "sase.xprompt.workflow_loader.get_known_project_workspaces",
            return_value={"sase": workspace},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_internal",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_plugins",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_config",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_project",
            return_value={},
        ),
    ):
        workflows = get_all_workflows(project="sase")

    assert "sase/fix_just" in workflows
    assert workflows["sase/fix_just"].source_path == str(xprompts / "fix_just.yml")
