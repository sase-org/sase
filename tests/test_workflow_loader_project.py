"""Tests for project-based workflow loading in workflow_loader."""

import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.xprompt.workflow_loader import (
    _discover_workflow_files,
    _load_workflow_from_file,
    _namespace_workflow,
    get_all_workflows,
)
from sase.xprompt.models import InputArg
from sase.xprompt.project_identity import invalidate_xprompt_project_identity
from sase.xprompt.workflow_models import Workflow
from tests.main.project_handler_helpers import _disk_project_records, _write_project


@pytest.fixture
def workflow_project_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    from sase import project_aliases, project_display_names
    from sase.xprompt import loader_sources

    projects_root = tmp_path / "sase-home" / "projects"
    projects_root.mkdir(parents=True)
    monkeypatch.setenv("SASE_HOME", str(projects_root.parent))
    monkeypatch.setattr(project_aliases, "list_project_records", _disk_project_records)
    monkeypatch.setattr(
        project_display_names,
        "list_project_records",
        _disk_project_records,
    )
    monkeypatch.setattr(loader_sources, "list_project_records", _disk_project_records)
    invalidate_xprompt_project_identity()
    yield projects_root
    invalidate_xprompt_project_identity()


def _write_registered_workflow_project(
    projects_root: Path,
    workspace: Path,
    *,
    state: str = "enabled",
) -> Path:
    xprompts = workspace / "sase" / "xprompts"
    xprompts.mkdir(parents=True)
    flow = xprompts / "flow.yml"
    flow.write_text(
        "steps:\n  - name: run\n    bash: echo registry\n",
        encoding="utf-8",
    )
    _write_project(
        projects_root,
        "gh_org__proj",
        "\n".join(
            (
                f"WORKSPACE_DIR: {workspace}",
                f"PROJECT_STATE: {state}",
                "PROJECT_NAME: proj",
                "PROJECT_ALIASES: short",
            )
        )
        + "\n",
    )
    return flow


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


def test_namespace_workflow_preserves_descriptions() -> None:
    workflow = Workflow(
        name="review",
        inputs=[InputArg(name="path", description="Path to review.")],
        source_path="/project/review.yml",
        description="Review project files.",
    )

    namespaced = _namespace_workflow("myproj", workflow)

    assert namespaced.name == "myproj/review"
    assert namespaced.description == "Review project files."
    assert namespaced.inputs[0].description == "Path to review."


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


def test_canonical_workflow_and_steps_override_legacy_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    canonical = tmp_path / "sase" / "xprompts"
    legacy = tmp_path / ".xprompts"
    for directory, command in ((canonical, "canonical"), (legacy, "legacy")):
        (directory / "steps").mkdir(parents=True)
        (directory / "steps" / "shared.yml").write_text(
            f"bash: echo {command}\n",
            encoding="utf-8",
        )
        (directory / "ship.yml").write_text(
            "steps:\n  - name: run\n    use: shared\n",
            encoding="utf-8",
        )
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)

    workflows = get_all_workflows(project="demo")

    workflow = workflows["demo/ship"]
    assert workflow.source_path == str(canonical / "ship.yml")
    assert workflow.steps[0].bash == "echo canonical"


def test_get_all_workflows_file_overrides_plugin() -> None:
    """File-backed workflows override plugin workflows with the same name."""
    plugin_workflow = Workflow(
        name="nightly_docs",
        inputs=[],
        steps=[],
        source_path="plugin:sase/foo.yml",
    )
    file_workflow = Workflow(
        name="nightly_docs",
        inputs=[],
        steps=[],
        source_path="/repo/xprompts/nightly_docs.yml",
    )

    with (
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_internal",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_plugins",
            return_value={"nightly_docs": plugin_workflow},
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
            return_value={"nightly_docs": file_workflow},
        ),
    ):
        workflows = get_all_workflows(project="sase")

    assert workflows["nightly_docs"].source_path == "/repo/xprompts/nightly_docs.yml"


def test_get_all_workflows_ignores_config_workflows_block(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """A top-level ``workflows:`` block in a config file does not resolve as a workflow."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "sase_athena.yml").write_text(
        "workflows:\n"
        "  nightly_docs:\n"
        "    steps:\n"
        "      - name: run\n"
        "        bash: echo legacy\n",
        encoding="utf-8",
    )

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    with (
        patch("sase.config.core.CONFIG_DIR", config_dir),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_internal",
            return_value={},
        ),
        patch(
            "sase.xprompt.workflow_loader._load_workflows_from_plugins",
            return_value={},
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
        workflows = get_all_workflows()

    assert workflows == {}


def test_get_all_workflows_loads_known_project_workspace_from_other_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """Project-scoped workflows load from the known primary checkout."""
    workspace = tmp_path / "sase"
    other_cwd = tmp_path / "other"
    xprompts = workspace / "sase" / "xprompts"
    xprompts.mkdir(parents=True)
    other_cwd.mkdir()
    (xprompts / "maintenance.yml").write_text(
        "steps:\n  - name: run\n    bash: echo maintain\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(other_cwd)

    with (
        patch(
            "sase.xprompt.workflow_loader.known_project_namespaces",
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
            "sase.xprompt.workflow_loader._load_workflows_from_project",
            return_value={},
        ),
        patch("sase.xprompt.workflow_loader.detect_project", return_value=None),
    ):
        workflows = get_all_workflows(project="sase")

    assert "sase/maintenance" in workflows
    assert workflows["sase/maintenance"].source_path == str(
        xprompts / "maintenance.yml"
    )


def test_get_all_workflows_loads_athena_workflows_for_normalized_gh_ref(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """``#gh:sase-org/sase`` resolves to the ``sase`` workspace's workflows.

    Confirms synthetic SASE workflows in ``sase/xprompts/`` are visible through
    the known-project workspace fallback
    once the resolver has normalized ``sase-org/sase`` to the registered
    ``sase`` project name.
    """
    workspace = tmp_path / "sase"
    other_cwd = tmp_path / "other"
    xprompts = workspace / "sase" / "xprompts"
    xprompts.mkdir(parents=True)
    other_cwd.mkdir()
    for name in ("daily_checks", "weekly_cleanup", "release_notes"):
        (xprompts / f"{name}.yml").write_text(
            "steps:\n  - name: run\n    bash: echo " + name + "\n",
            encoding="utf-8",
        )
    monkeypatch.chdir(other_cwd)

    with (
        patch(
            "sase.xprompt.workflow_loader.known_project_namespaces",
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
            "sase.xprompt.workflow_loader._load_workflows_from_project",
            return_value={},
        ),
        patch("sase.xprompt.workflow_loader.detect_project", return_value=None),
    ):
        workflows = get_all_workflows(project="sase")

    assert "sase/daily_checks" in workflows
    assert "sase/weekly_cleanup" in workflows
    assert "sase/release_notes" in workflows


@pytest.mark.parametrize("project_ref", ("proj", "gh_org__proj", "short"))
def test_get_all_workflows_uses_canonical_registered_project_identity(
    project_ref: str,
    workflow_project_registry: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "primary"
    flow = _write_registered_workflow_project(
        workflow_project_registry,
        workspace,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    with patch("sase.xprompt.workflow_loader.detect_project", return_value=None):
        workflows = get_all_workflows(project=project_ref)

    assert set(workflows).issuperset({"proj/flow"})
    assert workflows["proj/flow"].source_path == str(flow)
    assert "gh_org__proj/flow" not in workflows
    assert "short/flow" not in workflows


def test_get_all_workflows_current_checkout_wins_without_registry_read(
    workflow_project_registry: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_registered_workflow_project(
        workflow_project_registry,
        tmp_path / "primary",
    )
    alternate = tmp_path / "alternate"
    flow = alternate / "sase" / "xprompts" / "flow.yml"
    flow.parent.mkdir(parents=True)
    flow.write_text(
        "steps:\n  - name: run\n    bash: echo alternate\n",
        encoding="utf-8",
    )
    (alternate / ".git").mkdir()
    monkeypatch.chdir(alternate)

    with (
        patch(
            "sase.xprompt.workflow_loader.detect_project",
            return_value="gh_org__proj",
        ),
        patch(
            "sase.xprompt.workflow_loader.known_project_namespaces",
            side_effect=AssertionError("registry copy should not be read"),
        ),
    ):
        workflows = get_all_workflows(project="short")

    assert workflows["proj/flow"].source_path == str(flow)
    assert workflows["proj/flow"].steps[0].bash == "echo alternate"


def test_get_all_workflows_does_not_resolve_disabled_registered_project(
    workflow_project_registry: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_registered_workflow_project(
        workflow_project_registry,
        tmp_path / "disabled",
        state="disabled",
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    with patch("sase.xprompt.workflow_loader.detect_project", return_value=None):
        workflows = get_all_workflows(project="short")

    assert "proj/flow" not in workflows
