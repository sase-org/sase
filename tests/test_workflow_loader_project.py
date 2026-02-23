"""Tests for project-based workflow loading in workflow_loader."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.xprompt.workflow_loader import (
    _discover_workflow_files,
    _load_workflow_from_file,
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
            "sase.xprompt.workflow_loader._load_workflows_from_project"
        ) as mock_load_project,
    ):
        get_all_workflows()  # No project param

    # Should not have called _load_workflows_from_project
    mock_load_project.assert_not_called()


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
            "sase.xprompt.workflow_loader._load_workflows_from_project",
            return_value={"test": project_workflow},
        ),
    ):
        workflows = get_all_workflows(project="testproj")

    # File-based should win
    assert workflows["test"].source_path == "/file/test.yml"


def test_xprompts_yml_skipped_during_workflow_discovery() -> None:
    """Test that xprompts.yml/yaml files are not discovered as workflow files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        search_dir = Path(tmp_dir) / ".xprompts"
        search_dir.mkdir()

        # Create an xprompts.yml (should be skipped)
        (search_dir / "xprompts.yml").write_text('foo: "content"\n')
        # Create an xprompts.yaml (should also be skipped)
        (search_dir / "xprompts.yaml").write_text('bar: "content"\n')
        # Create a real workflow (should be discovered)
        (search_dir / "real_workflow.yml").write_text(
            "steps:\n  - name: step1\n    bash: echo hi\n"
        )

        with patch(
            "sase.xprompt.workflow_loader.get_xprompt_search_paths",
            return_value=[search_dir],
        ):
            discovered = _discover_workflow_files()

        filenames = [path.name for path, _ in discovered]
        assert "xprompts.yml" not in filenames
        assert "xprompts.yaml" not in filenames
        assert "real_workflow.yml" in filenames
